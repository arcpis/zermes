import json

import pytest

from hermes_cli.worker_agents_product import write_management_state_for_tests
from worker_agents.organization import MAIN_AGENT_ID


def _dashboard_gap_state():
    return {
        "worker_records": {
            "worker-a": {
                "worker_id": "worker-a",
                "display_name": "Worker A",
                "role": "lead",
                "runtime_type": "internal",
                "status": "enabled",
                "metadata": {
                    "department_ids": ["engineering"],
                    "secret_token": "hidden",
                },
            },
            "worker-b": {
                "worker_id": "worker-b",
                "display_name": "Worker B",
                "role": "reviewer",
                "runtime_type": "internal",
                "status": "enabled",
                "metadata": {"department_ids": ["engineering"]},
            },
            "writer": {
                "worker_id": "writer",
                "display_name": "Writer",
                "role": "writer",
                "runtime_type": "internal",
                "status": "enabled",
                "metadata": {"department_ids": ["writing"]},
            },
            "archived-worker": {
                "worker_id": "archived-worker",
                "display_name": "Archived Worker",
                "role": "legacy",
                "runtime_type": "internal",
                "status": "archived",
            },
        },
        "organization_tree": {
            "revision": "1",
            "nodes": {
                "root": {
                    "org_node_id": "root",
                    "name": "Root",
                    "node_type": "root",
                    "lifecycle": "active",
                    "child_ids": ["engineering", "writing"],
                    "leader": {"kind": "main_agent"},
                },
                "engineering": {
                    "org_node_id": "engineering",
                    "name": "Engineering",
                    "node_type": "department",
                    "lifecycle": "active",
                    "parent_id": "root",
                    "child_ids": ["platform"],
                    "leader": {"kind": "worker", "worker_id": "worker-a"},
                    "member_worker_ids": ["worker-a", "worker-b"],
                },
                "platform": {
                    "org_node_id": "platform",
                    "name": "Platform",
                    "node_type": "team",
                    "lifecycle": "active",
                    "parent_id": "engineering",
                    "leader": {"kind": "worker", "worker_id": "worker-b"},
                    "member_worker_ids": ["worker-b"],
                },
                "writing": {
                    "org_node_id": "writing",
                    "name": "Writing",
                    "node_type": "department",
                    "lifecycle": "active",
                    "parent_id": "root",
                    "leader": {"kind": "worker", "worker_id": "writer"},
                    "member_worker_ids": ["writer"],
                },
            },
        },
        "threads": [],
        "department_summaries": [],
    }


@pytest.fixture()
def client(monkeypatch, tmp_path):
    try:
        from starlette.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi/starlette not installed")

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("ZERMES_HOME", str(tmp_path))
    write_management_state_for_tests(_dashboard_gap_state(), tmp_path)

    from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN

    test_client = TestClient(app)
    test_client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN
    return test_client


def test_chats_include_materialized_department_group(client):
    response = client.get("/api/worker-agents/chats")

    assert response.status_code == 200
    chats = response.json()
    engineering = next(chat for chat in chats if chat["thread_id"] == "dept-engineering")
    assert engineering["thread_type"] == "department"
    assert engineering["worker_count"] == 2
    assert engineering["valid_management_boundary"] is True


def test_single_worker_department_exposes_fallback_without_group_thread(client):
    response = client.get("/api/worker-agents/chats")
    organization = client.get("/api/worker-agents/organization")

    assert response.status_code == 200
    assert organization.status_code == 200
    assert "dept-writing" not in {chat["thread_id"] for chat in response.json()}
    rendered = json.dumps(organization.json())
    assert "private_or_parent_chat" in rendered


def test_direct_worker_chat_endpoint_is_idempotent(client):
    first = client.post("/api/worker-agents/workers/worker-a/direct-chat")
    second = client.post("/api/worker-agents/workers/worker-a/direct-chat")
    chats = client.get("/api/worker-agents/chats")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["thread"]["thread_id"] == "direct-user-worker-a"
    assert second.json()["updated_status"] == "existing"
    assert sum(chat["thread_id"] == "direct-user-worker-a" for chat in chats.json()) == 1


def test_direct_worker_chat_rejects_archived_worker(client):
    response = client.post("/api/worker-agents/workers/archived-worker/direct-chat")

    assert response.status_code == 200
    assert response.json()["updated_status"] == "disabled"
    assert "not enabled" in response.json()["disabled_reason"]


def test_department_and_direct_chat_histories_are_isolated(client):
    client.post("/api/worker-agents/workers/worker-a/direct-chat")
    dept_send = client.post(
        "/api/worker-agents/chats/dept-engineering/send",
        json={"sender_id": "user", "text": "department update"},
    )
    direct_send = client.post(
        "/api/worker-agents/chats/direct-user-worker-a/send",
        json={"sender_id": "user", "text": "private note"},
    )

    dept_history = client.get("/api/worker-agents/chats/dept-engineering/history")
    direct_history = client.get("/api/worker-agents/chats/direct-user-worker-a/history")

    assert dept_send.status_code == 200
    assert direct_send.status_code == 200
    assert [msg["body_preview"] for msg in dept_history.json()["messages"]] == [
        "department update"
    ]
    assert [msg["body_preview"] for msg in direct_history.json()["messages"]] == [
        "private note"
    ]


def test_product_mention_creates_delivery_tracking(client):
    send = client.post(
        "/api/worker-agents/chats/dept-engineering/send",
        json={
            "sender_id": "user",
            "text": "@engineering please review",
            "message_type": "mention",
            "target_kind": "department",
            "target_id": "engineering",
        },
    )
    mentions = client.get("/api/worker-agents/mentions")

    assert send.status_code == 200
    assert send.json()["audit"]["delivery_records"][0]["resolved_recipient"] == {
        "kind": "worker",
        "participant_id": "worker-a",
    }
    assert mentions.status_code == 200
    assert mentions.json()[0]["mentioned_target"]["matched_kind"] == "department"


def test_product_broadcast_creates_delivery_tracking(client):
    send = client.post(
        "/api/worker-agents/chats/dept-engineering/send",
        json={
            "sender_id": "user",
            "text": "platform decision summary",
            "message_type": "broadcast",
            "target_kind": "team",
            "target_id": "platform",
            "importance": "important",
        },
    )
    broadcasts = client.get("/api/worker-agents/broadcasts")

    assert send.status_code == 200
    assert send.json()["audit"]["delivery_records"][0]["recipient"] == {
        "kind": "worker",
        "participant_id": "worker-b",
    }
    assert broadcasts.status_code == 200
    assert broadcasts.json()[0]["target"]["target_kind"] == "team"
    assert broadcasts.json()[0]["importance"] == "important"


def test_product_broadcast_rejects_explicit_worker_outside_thread(client):
    response = client.post(
        "/api/worker-agents/chats/dept-engineering/send",
        json={
            "sender_id": "user",
            "text": "private routing should fail",
            "message_type": "broadcast",
            "target_kind": "explicit_workers",
            "target_ids": ["writer"],
        },
    )

    assert response.status_code == 400
    assert "thread participant" in response.json()["detail"]


def test_gap_closure_outputs_no_sensitive_fields(client):
    rendered = json.dumps(
        {
            "overview": client.get("/api/worker-agents/overview").json(),
            "chats": client.get("/api/worker-agents/chats").json(),
            "direct": client.post("/api/worker-agents/workers/worker-a/direct-chat").json(),
        }
    )

    assert "secret_token" not in rendered
    assert "hidden" not in rendered
    assert "raw_transcript" not in rendered

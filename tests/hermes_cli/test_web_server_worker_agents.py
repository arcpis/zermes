import json

import pytest

from hermes_cli.worker_agents_product import write_management_state_for_tests
from worker_agents.organization import MAIN_AGENT_ID


def _state():
    return {
        "worker_records": {
            "worker-a": {
                "worker_id": "worker-a",
                "display_name": "Worker A",
                "role": "developer",
                "runtime_type": "internal",
                "status": "enabled",
                "metadata": {"secret_token": "hidden", "department_ids": ["engineering"]},
            },
            "worker-b": {
                "worker_id": "worker-b",
                "display_name": "Worker B",
                "role": "reviewer",
                "runtime_type": "external",
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
                    "child_ids": ["engineering"],
                },
                "engineering": {
                    "org_node_id": "engineering",
                    "name": "Engineering",
                    "node_type": "department",
                    "lifecycle": "active",
                    "parent_id": "root",
                    "member_worker_ids": ["worker-a"],
                },
            },
        },
        "threads": [
            {
                "thread_id": "thread-1",
                "thread_type": "organization_group",
                "participants": [
                    {"kind": "user", "participant_id": "user"},
                    {"kind": "main_agent", "participant_id": MAIN_AGENT_ID},
                    {"kind": "worker", "participant_id": "worker-a"},
                ],
                "main_agent_visible": True,
                "audit_summary": "safe summary",
            }
        ],
        "approvals": [
            {
                "source_kind": "organization_evolution",
                "proposal_id": "approval-1",
                "status": "pending",
                "requestor_id": "worker-a",
            }
        ],
        "assets": [
            {
                "proposal_id": "asset-1",
                "proposal_kind": "memory",
                "status": "pending",
                "target_department_id": "engineering",
                "summary": "raw transcript must redact",
            }
        ],
        "evolution": [
            {
                "proposal_id": "evo-1",
                "proposal_kind": "archive_node",
                "status": "approved",
            }
        ],
    }


@pytest.fixture()
def client(monkeypatch, tmp_path):
    try:
        from starlette.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi/starlette not installed")

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("ZERMES_HOME", str(tmp_path))
    write_management_state_for_tests(_state(), tmp_path)

    from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN

    test_client = TestClient(app)
    test_client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN
    return test_client


def test_worker_agents_api_requires_session_token(client):
    client.headers.clear()

    response = client.get("/api/worker-agents/overview")

    assert response.status_code == 401


def test_worker_agents_read_endpoints_filter_sensitive_fields(client):
    response = client.get("/api/worker-agents/overview")
    workers = client.get("/api/worker-agents/workers?runtime=internal")
    organization = client.get("/api/worker-agents/organization")
    chats = client.get("/api/worker-agents/chats")

    assert response.status_code == 200
    assert workers.status_code == 200
    assert organization.status_code == 200
    assert chats.status_code == 200
    assert workers.json()[0]["worker_id"] == "worker-a"
    rendered = json.dumps(
        {
            "overview": response.json(),
            "workers": workers.json(),
            "organization": organization.json(),
            "chats": chats.json(),
        }
    )
    assert "secret_token" not in rendered
    assert "hidden" not in rendered
    assert "raw transcript must redact" not in rendered


def test_worker_agents_chat_send_and_history_share_managed_store(client):
    send = client.post(
        "/api/worker-agents/chats/thread-1/send",
        json={"sender_id": "user", "text": "hello from dashboard"},
    )

    history = client.get("/api/worker-agents/chats/thread-1/history?limit=1")

    assert send.status_code == 200
    assert send.json()["audit_ref"].startswith("worker_agents/threads/thread-1/")
    assert history.status_code == 200
    assert history.json()["messages"][0]["body_preview"] == "hello from dashboard"


def test_worker_agents_evolution_apply_draft_updates_overview(client):
    response = client.post(
        "/api/worker-agents/evolution/apply-draft",
        json={
            "proposal_kind": "create_child_agent",
            "actor_id": "user",
            "target_node_id": "root",
            "requested_worker_id": "platform-implementation",
            "reason": "Platform implementation",
        },
    )
    overview = client.get("/api/worker-agents/overview")

    assert response.status_code == 200
    assert response.json()["updated_status"] == "created"
    assert any(
        worker["worker_id"] == "platform-implementation"
        for worker in overview.json()["workers"]
    )
    assert any(
        node["org_node_id"] == "platform-implementation"
        for node in overview.json()["organization_nodes"]
    )


def test_worker_agents_action_endpoints_return_audit_contract(client):
    approval = client.post(
        "/api/worker-agents/approvals/approval-1/action",
        json={"decision": "reject", "actor_id": "lead", "reason": "not needed"},
    )
    asset = client.post(
        "/api/worker-agents/assets/asset-1/action",
        json={"decision": "reject", "actor_id": "lead", "reason": "not needed"},
    )

    assert approval.status_code == 200
    assert asset.status_code == 200
    assert approval.json()["next_required_action"] == "review_audit_result"
    assert asset.json()["updated_status"] == "reject"

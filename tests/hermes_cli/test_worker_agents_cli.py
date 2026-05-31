import json
import sys
from pathlib import Path

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
                "responsibilities": ["Implement scoped changes"],
                "allow_delegation": True,
                "allowed_child_tools": ["read_file"],
                "max_child_task_tokens": 500,
                "runtime_type": "internal",
                "status": "enabled",
                "metadata": {
                    "department_ids": ["engineering"],
                    "api_key": "hidden",
                },
            },
            "worker-b": {
                "worker_id": "worker-b",
                "display_name": "Worker B",
                "role": "reviewer",
                "runtime_type": "external",
                "status": "archived",
            },
        },
        "health_summaries": {"worker-b": {"status": "unhealthy"}},
        "organization_tree": {
            "revision": "1",
            "nodes": {
                "root": {
                    "org_node_id": "root",
                    "name": "Root",
                    "node_type": "root",
                    "lifecycle": "active",
                    "child_ids": ["engineering"],
                    "leader": {"kind": "main_agent"},
                },
                "engineering": {
                    "org_node_id": "engineering",
                    "name": "Engineering",
                    "node_type": "department",
                    "lifecycle": "active",
                    "parent_id": "root",
                    "leader": {"kind": "worker", "worker_id": "worker-a"},
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
                "title": "Engineering",
                "audit_summary": "daily status",
            },
            {
                "thread_id": "frozen-thread",
                "thread_type": "organization_group",
                "status": "frozen",
                "participants": [
                    {"kind": "user", "participant_id": "user"},
                    {"kind": "main_agent", "participant_id": MAIN_AGENT_ID},
                    {"kind": "worker", "participant_id": "worker-a"},
                ],
                "main_agent_visible": True,
            },
        ],
        "approvals": [
            {
                "source_kind": "department_tool_policy",
                "proposal_id": "approval-1",
                "status": "pending",
                "requestor_id": "worker-a",
                "risks": [{"code": "permission_expansion", "severity": "blocker"}],
                "user_confirmation_required": True,
            }
        ],
        "assets": [
            {
                "proposal_id": "asset-1",
                "proposal_kind": "memory",
                "status": "pending",
                "target_department_id": "engineering",
                "summary": "safe summary",
            }
        ],
        "evolution": [
            {
                "proposal_id": "evo-1",
                "proposal_kind": "archive_node",
                "status": "approved",
            }
        ],
        "retention_candidates": [
            {"item_id": "cache-1", "item_kind": "runtime_cache", "estimated_size_bytes": 5}
        ],
    }


@pytest.fixture()
def cli_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("ZERMES_HOME", str(tmp_path))
    write_management_state_for_tests(_state(), tmp_path)
    return tmp_path


def _run_cli(monkeypatch, capsys, *args):
    from hermes_cli.main import main

    monkeypatch.setattr(sys, "argv", ["hermes", *args])
    try:
        main()
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise AssertionError(capsys.readouterr().err) from exc
    return capsys.readouterr()


def test_worker_agents_help_smoke(monkeypatch, capsys, cli_home):
    from hermes_cli.main import main

    monkeypatch.setattr(sys, "argv", ["hermes", "worker-agents", "--help"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    assert "overview" in capsys.readouterr().out


def test_workers_json_filters_and_redacts_sensitive_fields(monkeypatch, capsys, cli_home):
    out = _run_cli(
        monkeypatch,
        capsys,
        "worker-agents",
        "workers",
        "--runtime",
        "internal",
        "--json",
    ).out
    data = json.loads(out)

    assert [row["worker_id"] for row in data] == ["worker-a"]
    rendered = json.dumps(data)
    assert "api_key" not in rendered
    assert "hidden" not in rendered


def test_prompt_summary_json_exposes_identity_and_delegation(monkeypatch, capsys, cli_home):
    out = _run_cli(
        monkeypatch,
        capsys,
        "worker-agents",
        "prompt-summary",
        "worker-a",
        "--json",
    ).out
    data = json.loads(out)

    assert data["worker_id"] == "worker-a"
    assert data["default_reply_thread_id"] == "thread-1"
    assert data["department_chat_threads"][0]["thread_id"] == "thread-1"
    assert data["delegation"]["delegation_allowed"] is False
    assert "api_key" not in json.dumps(data)


def test_evolution_apply_draft_creates_management_worker_and_node(monkeypatch, capsys, cli_home):
    first = _run_cli(
        monkeypatch,
        capsys,
        "worker-agents",
        "evolution-apply-draft",
        "--proposal-kind",
        "create_child_agent",
        "--actor",
        "user",
        "--target-node",
        "root",
        "--requested-worker",
        "code-implementation",
        "--reason",
        "Code implementation department",
        "--json",
    ).out
    first_data = json.loads(first)
    assert first_data["updated_status"] == "created"

    _run_cli(
        monkeypatch,
        capsys,
        "worker-agents",
        "evolution-apply-draft",
        "--proposal-kind",
        "create_child_agent",
        "--actor",
        "user",
        "--target-node",
        "code-implementation",
        "--requested-worker",
        "frontend-implementation",
        "--reason",
        "Frontend implementation",
        "--json",
    )

    overview = json.loads(
        _run_cli(monkeypatch, capsys, "worker-agents", "overview", "--json").out
    )
    worker_ids = {worker["worker_id"] for worker in overview["workers"]}
    node_ids = {node["org_node_id"] for node in overview["organization_nodes"]}

    assert {"code-implementation", "frontend-implementation"} <= worker_ids
    assert {"root", "code-implementation", "frontend-implementation"} <= node_ids


def test_evolution_apply_draft_dry_run_does_not_write(monkeypatch, capsys, cli_home):
    _run_cli(
        monkeypatch,
        capsys,
        "worker-agents",
        "evolution-apply-draft",
        "--proposal-kind",
        "create_child_agent",
        "--actor",
        "user",
        "--target-node",
        "root",
        "--requested-worker",
        "dry-run-worker",
        "--dry-run",
        "--json",
    )

    overview = json.loads(
        _run_cli(monkeypatch, capsys, "worker-agents", "overview", "--json").out
    )

    assert "dry-run-worker" not in {worker["worker_id"] for worker in overview["workers"]}


def test_chat_history_paginates_controlled_message_envelopes(monkeypatch, capsys, cli_home):
    _run_cli(
        monkeypatch,
        capsys,
        "worker-agents",
        "send",
        "thread-1",
        "--sender",
        "user",
        "--text",
        "hello",
        "--json",
    )

    out = _run_cli(
        monkeypatch,
        capsys,
        "worker-agents",
        "chat-history",
        "thread-1",
        "--limit",
        "1",
        "--json",
    ).out
    data = json.loads(out)

    assert data["messages"][0]["body_preview"] == "hello"
    assert "raw_transcript" not in json.dumps(data)


def test_mention_command_records_delivery_tracking(monkeypatch, capsys, cli_home):
    out = _run_cli(
        monkeypatch,
        capsys,
        "worker-agents",
        "mention",
        "thread-1",
        "--sender",
        "user",
        "--text",
        "@worker-a please check",
        "--target-kind",
        "worker",
        "--target-id",
        "worker-a",
        "--json",
    ).out
    data = json.loads(out)
    mentions = json.loads(
        _run_cli(monkeypatch, capsys, "worker-agents", "mentions", "--json").out
    )

    assert data["updated_status"] == "created"
    assert data["audit"]["delivery_records"][0]["resolved_recipient"]["participant_id"] == "worker-a"
    assert mentions[0]["mentioned_target"]["requested_kind"] == "worker"


def test_broadcast_command_records_importance(monkeypatch, capsys, cli_home):
    out = _run_cli(
        monkeypatch,
        capsys,
        "worker-agents",
        "broadcast",
        "thread-1",
        "--sender",
        "user",
        "--text",
        "decision summary",
        "--target-kind",
        "thread",
        "--importance",
        "important",
        "--json",
    ).out
    data = json.loads(out)
    broadcasts = json.loads(
        _run_cli(monkeypatch, capsys, "worker-agents", "broadcasts", "--json").out
    )

    assert data["updated_status"] == "created"
    assert data["audit"]["delivery_records"][0]["importance"] == "important"
    assert broadcasts[0]["target"]["target_kind"] == "thread"


def test_direct_chat_command_creates_worker_thread(monkeypatch, capsys, cli_home):
    out = _run_cli(
        monkeypatch,
        capsys,
        "worker-agents",
        "direct-chat",
        "worker-a",
        "--json",
    ).out
    data = json.loads(out)

    assert data["updated_status"] == "created"
    assert data["thread"]["thread_id"] == "direct-user-worker-a"


def test_chat_send_rejects_read_only_thread(monkeypatch, capsys, cli_home):
    from hermes_cli.main import main

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "hermes",
            "worker-agents",
            "send",
            "frozen-thread",
            "--text",
            "blocked",
            "--json",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    error = json.loads(capsys.readouterr().err)
    assert error["error"]["next_required_action"] == "resolve_blocker_and_retry"


def test_high_risk_approval_requires_confirmation(monkeypatch, capsys, cli_home):
    from hermes_cli.main import main

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "hermes",
            "worker-agents",
            "approval",
            "approve",
            "approval-1",
            "--actor",
            "lead",
            "--reason",
            "ok",
            "--json",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    assert "explicit confirmation" in capsys.readouterr().err


def test_frontend_worker_agents_page_is_registered():
    app = Path("web/src/App.tsx").read_text(encoding="utf-8")
    page = Path("web/src/pages/WorkerAgentsPage.tsx").read_text(encoding="utf-8")

    assert '"/worker-agents": WorkerAgentsPage' in app
    assert "Worker Agents" in page
    assert "read-only" in page
    assert "Organization tree is available through the API" not in page
    assert "/api/worker-agents/organization" in page
    assert "/direct-chat" in page

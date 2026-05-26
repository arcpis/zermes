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

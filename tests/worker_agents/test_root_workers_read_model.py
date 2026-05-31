from __future__ import annotations

import json

from worker_agents.management.root_workers import (
    collect_enabled_root_worker_ids,
    load_worker_management_state,
)


def test_collect_enabled_root_worker_ids_preserves_order_and_filters_disabled():
    state = {
        "organization_tree": {
            "root_node_id": "root",
            "nodes": {
                "root": {
                    "node_type": "department",
                    "member_worker_ids": ["root-worker", "disabled-worker"],
                    "child_ids": ["dept-a", "dept-b"],
                },
                "dept-a": {
                    "node_type": "department",
                    "leader": {"kind": "worker", "worker_id": "dept-a-lead"},
                    "member_worker_ids": ["dept-a-member", "root-worker"],
                    "child_ids": ["dept-a-individual"],
                },
                "dept-a-individual": {
                    "node_type": "individual",
                    "individual_worker_id": "individual-worker",
                },
                "dept-b": {
                    "node_type": "department",
                    "leader": {"kind": "main_agent"},
                    "member_worker_ids": ["dept-b-member"],
                    "child_ids": [],
                },
            },
        },
        "worker_records": {
            "root-worker": {"status": "enabled"},
            "disabled-worker": {"status": "disabled"},
            "dept-a-lead": {"status": "enabled"},
            "dept-a-member": {"status": "enabled"},
            "individual-worker": {"status": "enabled"},
            "dept-b-member": {"status": "enabled"},
        },
    }

    assert collect_enabled_root_worker_ids(state) == [
        "root-worker",
        "dept-a-lead",
        "dept-a-member",
        "individual-worker",
        "dept-b-member",
    ]


def test_load_worker_management_state_uses_profile_home_and_sanitizes(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    state_path = tmp_path / "worker_agents" / "management" / "dashboard_state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "worker_records": {
                    "worker-a": {
                        "status": "enabled",
                        "api_key": "secret",
                        "description": "normal summary",
                    }
                },
                "token_note": "remove me",
            }
        ),
        encoding="utf-8",
    )

    state = load_worker_management_state()

    assert "token_note" not in state
    assert "api_key" not in state["worker_records"]["worker-a"]
    assert state["worker_records"]["worker-a"]["description"] == "normal summary"

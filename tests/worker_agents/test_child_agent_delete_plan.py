import pytest

from worker_agents.organization_evolution import (
    CHILD_AGENT_LIFECYCLE_SCHEMA_VERSION,
    ChildAgentDeleteBlockingCheck,
    ChildAgentDeletionMode,
    ChildAgentPrivateAssetDisposition,
    ChildAgentReplacementOwner,
    ChildAgentReplacementOwnerKind,
    OrganizationEvolutionError,
    child_agent_delete_plan_from_dict,
    child_agent_delete_plan_to_dict,
    validate_child_agent_delete_plan,
)


def _replacement_owner(**overrides):
    data = {
        "kind": "worker",
        "worker_id": "platform_lead",
        "org_node_id": None,
        "reason": "Platform lead takes ownership.",
    }
    data.update(overrides)
    return data


def _delete_plan(**overrides):
    data = {
        "plan_id": "delete_platform_researcher",
        "schema_version": CHILD_AGENT_LIFECYCLE_SCHEMA_VERSION,
        "target_node_id": "platform_researcher_node",
        "target_worker_id": "platform_researcher",
        "deletion_mode": "archive",
        "reason": "Role is no longer needed.",
        "replacement_owner": _replacement_owner(),
        "private_asset_disposition": "archive",
        "asset_disposition_refs": ["assets/archive-platform-researcher.json"],
        "chat_disposition_refs": ["chats/archive-platform-researcher.json"],
        "active_task_refs": [],
        "pending_approval_refs": [],
        "child_node_ids": [],
        "running_session_refs": [],
        "downstream_disposition_refs": [],
        "source_refs": ["proposals/delete-platform-researcher.md"],
    }
    data.update(overrides)
    return data


def test_delete_plan_without_blockers_can_enter_pending_approval():
    plan = child_agent_delete_plan_from_dict(_delete_plan())

    loaded = validate_child_agent_delete_plan(child_agent_delete_plan_to_dict(plan))

    assert loaded == plan
    assert loaded.deletion_mode is ChildAgentDeletionMode.ARCHIVE
    assert loaded.private_asset_disposition is ChildAgentPrivateAssetDisposition.ARCHIVE
    assert loaded.check_summary.blocking_checks == ()
    assert loaded.check_summary.can_enter_pending_approval is True
    assert loaded.check_summary.can_execute is True


def test_delete_plan_accepts_main_agent_replacement_owner():
    plan = child_agent_delete_plan_from_dict(
        _delete_plan(
            replacement_owner={
                "kind": "main_agent",
                "org_node_id": None,
                "worker_id": None,
                "reason": "Main agent holds responsibility until reassignment.",
            }
        )
    )

    assert plan.replacement_owner.kind is ChildAgentReplacementOwnerKind.MAIN_AGENT


def test_delete_plan_dataclass_accepts_no_replacement_reason():
    plan = child_agent_delete_plan_from_dict(
        _delete_plan(
            target_worker_id=None,
            deletion_mode="deprecate",
            replacement_owner={
                "kind": "no_replacement",
                "org_node_id": None,
                "worker_id": None,
                "reason": "The scoped responsibility is retired.",
            },
        )
    )

    assert plan.replacement_owner == ChildAgentReplacementOwner(
        kind=ChildAgentReplacementOwnerKind.NO_REPLACEMENT,
        reason="The scoped responsibility is retired.",
    )


@pytest.mark.parametrize(
    ("field", "value", "expected_blocker"),
    [
        (
            "active_task_refs",
            ["tasks/task-1/state.json"],
            ChildAgentDeleteBlockingCheck.ACTIVE_TASKS,
        ),
        (
            "pending_approval_refs",
            ["approvals/high-risk.json"],
            ChildAgentDeleteBlockingCheck.PENDING_APPROVALS,
        ),
        (
            "child_node_ids",
            ["downstream_team"],
            ChildAgentDeleteBlockingCheck.CHILD_NODES,
        ),
        (
            "running_session_refs",
            ["runtime/session-1.json"],
            ChildAgentDeleteBlockingCheck.RUNNING_SESSIONS,
        ),
    ],
)
def test_delete_plan_reports_execution_blockers(field, value, expected_blocker):
    overrides = {field: value}
    if field == "child_node_ids":
        overrides["downstream_disposition_refs"] = ["plans/move-downstream-team.json"]
    plan = child_agent_delete_plan_from_dict(_delete_plan(**overrides))

    summary = plan.check_summary

    assert expected_blocker in summary.blocking_checks
    assert summary.can_enter_pending_approval is False
    assert summary.can_execute is False


@pytest.mark.parametrize("field", ["asset_disposition_refs", "chat_disposition_refs"])
def test_delete_plan_rejects_missing_asset_or_chat_disposition_refs(field):
    with pytest.raises(OrganizationEvolutionError, match=field):
        child_agent_delete_plan_from_dict(_delete_plan(**{field: []}))


def test_delete_plan_rejects_direct_private_asset_drop():
    with pytest.raises(OrganizationEvolutionError, match="private asset disposition"):
        child_agent_delete_plan_from_dict(
            _delete_plan(private_asset_disposition="drop")
        )


def test_delete_plan_with_child_nodes_requires_downstream_disposition_ref():
    with pytest.raises(OrganizationEvolutionError, match="downstream_disposition_refs"):
        child_agent_delete_plan_from_dict(
            _delete_plan(child_node_ids=["downstream_team"])
        )


def test_delete_plan_requires_valid_replacement_owner_or_reason():
    with pytest.raises(OrganizationEvolutionError, match="replacement owner reason"):
        child_agent_delete_plan_from_dict(
            _delete_plan(
                replacement_owner={
                    "kind": "no_replacement",
                    "org_node_id": None,
                    "worker_id": None,
                    "reason": "",
                }
            )
        )


def test_delete_plan_rejects_sensitive_payload_fields():
    with pytest.raises(OrganizationEvolutionError, match="sensitive data"):
        validate_child_agent_delete_plan(_delete_plan(raw_transcript="not allowed"))

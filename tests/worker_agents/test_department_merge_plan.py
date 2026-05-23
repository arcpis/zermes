import pytest

from worker_agents.organization_evolution import (
    CHILD_AGENT_LIFECYCLE_SCHEMA_VERSION,
    DepartmentMergePlanStatus,
    OrganizationEvolutionError,
    department_merge_plan_from_dict,
    department_merge_plan_to_dict,
    department_merge_request_from_dict,
    validate_department_merge_plan,
)


def _initiator():
    return {
        "kind": "main_agent",
        "initiator_id": "zermes_main_agent",
        "display_name": "Zermes",
    }


def _department_summary(department_id, **overrides):
    data = {
        "department_id": department_id,
        "name": department_id.replace("_", " ").title(),
        "responsibility_summary": f"{department_id} responsibilities.",
        "leader_worker_id": f"{department_id}_lead",
        "member_worker_ids": [f"{department_id}_worker"],
        "child_node_ids": [],
    }
    data.update(overrides)
    return data


def _merge_request(**overrides):
    data = {
        "request_id": "merge_platform_into_engineering",
        "schema_version": CHILD_AGENT_LIFECYCLE_SCHEMA_VERSION,
        "initiator": _initiator(),
        "source_department_ids": ["platform"],
        "target_department_id": "engineering",
        "reason": "Consolidate platform delivery under engineering.",
        "source_summaries": [_department_summary("platform")],
        "target_summary": _department_summary("engineering"),
        "responsibility_change_summary": "Engineering absorbs platform delivery.",
        "member_migration_intent": "Move source department members to target.",
        "source_refs": ["proposals/merge-platform.md"],
    }
    data.update(overrides)
    return data


def _merge_plan(**overrides):
    data = {
        "plan_id": "merge_platform_plan",
        "schema_version": CHILD_AGENT_LIFECYCLE_SCHEMA_VERSION,
        "request": _merge_request(),
        "status": "draft",
        "task_transfer_plan_ref": "merge/task-transfer.json",
        "chat_freeze_plan_ref": "merge/chat-freeze.json",
        "memory_merge_report_ref": "merge/memory-report.json",
        "skill_disposition_plan_ref": "merge/skill-disposition.json",
        "tool_disposition_plan_ref": "merge/tool-disposition.json",
        "rollback_plan_ref": "merge/rollback.json",
        "proposal_ref": "proposals/merge-platform.json",
        "source_refs": ["merge/request.json"],
    }
    data.update(overrides)
    return data


def test_single_source_department_merge_request_is_valid():
    request = department_merge_request_from_dict(_merge_request())

    assert request.source_department_ids == ("platform",)
    assert request.target_department_id == "engineering"


def test_multi_source_department_merge_request_is_valid():
    request = department_merge_request_from_dict(
        _merge_request(
            request_id="merge_delivery_departments",
            source_department_ids=["platform", "frontend"],
            source_summaries=[
                _department_summary("platform"),
                _department_summary("frontend"),
            ],
        )
    )

    assert request.source_department_ids == ("platform", "frontend")


@pytest.mark.parametrize(
    "overrides",
    [
        {"source_department_ids": []},
        {"target_department_id": ""},
        {"reason": ""},
    ],
)
def test_merge_request_rejects_missing_required_fields(overrides):
    with pytest.raises(OrganizationEvolutionError):
        department_merge_request_from_dict(_merge_request(**overrides))


def test_merge_request_rejects_target_in_sources():
    with pytest.raises(OrganizationEvolutionError, match="target_department_id"):
        department_merge_request_from_dict(
            _merge_request(source_department_ids=["engineering"])
        )


def test_merge_request_requires_matching_source_summaries():
    with pytest.raises(OrganizationEvolutionError, match="source_summaries"):
        department_merge_request_from_dict(
            _merge_request(source_summaries=[_department_summary("other")])
        )


def test_department_merge_plan_round_trips_through_dict():
    plan = department_merge_plan_from_dict(_merge_plan(status="ready_for_approval"))

    loaded = validate_department_merge_plan(department_merge_plan_to_dict(plan))

    assert loaded == plan
    assert loaded.status is DepartmentMergePlanStatus.READY_FOR_APPROVAL


@pytest.mark.parametrize(
    "missing_ref",
    [
        "task_transfer_plan_ref",
        "chat_freeze_plan_ref",
        "memory_merge_report_ref",
        "skill_disposition_plan_ref",
        "tool_disposition_plan_ref",
        "rollback_plan_ref",
    ],
)
def test_department_merge_plan_requires_sub_plan_refs(missing_ref):
    data = _merge_plan()
    data.pop(missing_ref)

    with pytest.raises(OrganizationEvolutionError):
        department_merge_plan_from_dict(data)


def test_department_merge_plan_rejects_sensitive_payload_fields():
    with pytest.raises(OrganizationEvolutionError, match="sensitive data"):
        validate_department_merge_plan(_merge_plan(raw_stdout="not allowed"))

import pytest

from worker_agents.organization_evolution import (
    CHILD_AGENT_LIFECYCLE_SCHEMA_VERSION,
    DepartmentMergePreflightBlockingCode,
    DepartmentMergePreflightConflictCode,
    DepartmentMergePlanStatus,
    EvolutionProposalType,
    OrganizationEvolutionError,
    build_department_merge_preflight,
    department_merge_preflight_report_to_dict,
    dump_department_merge_preflight_report_json,
    department_merge_plan_from_dict,
    department_merge_plan_to_dict,
    department_merge_request_from_dict,
    load_department_merge_preflight_report_json,
    organization_evolution_proposal_from_dict,
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


def test_merge_request_rejects_duplicate_sources():
    with pytest.raises(OrganizationEvolutionError, match="duplicates"):
        department_merge_request_from_dict(
            _merge_request(source_department_ids=["platform", "platform"])
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


def test_department_merge_plan_can_be_referenced_by_evolution_proposal():
    plan = department_merge_plan_from_dict(
        _merge_plan(proposal_ref="proposals/merge-platform.json")
    )

    proposal = organization_evolution_proposal_from_dict(
        {
            "proposal_id": "merge_platform_proposal",
            "proposal_type": "merge_department",
            "schema_version": 1,
            "status": "draft",
            "initiator": _initiator(),
            "target_node_ids": [plan.request.target_department_id],
            "affected_worker_ids": [],
            "reason": plan.request.reason,
            "before_summary": "Platform is separate from engineering.",
            "after_summary": "Platform is merged into engineering.",
            "risk_flags": ["responsibility_change", "group_chat_closure"],
            "approval_policy": "unresolved",
            "asset_disposition_refs": [plan.skill_disposition_plan_ref],
            "chat_disposition_refs": [plan.chat_freeze_plan_ref],
            "rollback_summary_ref": plan.rollback_plan_ref,
            "source_refs": [plan.proposal_ref, "merge/plan.json"],
        }
    )

    assert proposal.proposal_type is EvolutionProposalType.MERGE_DEPARTMENT
    assert plan.proposal_ref in proposal.source_refs


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


def test_department_merge_preflight_is_ready_without_blockers():
    report = build_department_merge_preflight(
        _merge_plan(),
        department_lifecycle_states={
            "platform": "active",
            "engineering": "active",
        },
        asset_disposition_plan_refs={"platform": "merge/assets/platform.json"},
    )

    assert report.status is DepartmentMergePlanStatus.READY_FOR_APPROVAL
    assert report.blocking_items == ()


@pytest.mark.parametrize(
    ("summary_name", "summary", "expected_code"),
    [
        (
            "task_state_summary",
            {
                "active_high_risk_tasks": {
                    "platform": [
                        {
                            "task_id": "task_high_risk_release",
                            "source_refs": ["tasks/task_high_risk_release.json"],
                        }
                    ]
                }
            },
            DepartmentMergePreflightBlockingCode.ACTIVE_HIGH_RISK_TASK,
        ),
        (
            "approval_summary",
            {
                "pending_approvals": {
                    "platform": [
                        {
                            "approval_id": "approval_budget_change",
                            "source_refs": ["approvals/budget-change.json"],
                        }
                    ]
                }
            },
            DepartmentMergePreflightBlockingCode.PENDING_APPROVAL,
        ),
        (
            "runtime_session_summary",
            {
                "running_sessions": {
                    "platform": [
                        {
                            "session_id": "runtime_platform_1",
                            "source_refs": ["sessions/runtime-platform-1.json"],
                        }
                    ]
                }
            },
            DepartmentMergePreflightBlockingCode.RUNNING_RUNTIME_SESSION,
        ),
    ],
)
def test_department_merge_preflight_blocks_active_runtime_work(
    summary_name,
    summary,
    expected_code,
):
    kwargs = {
        "department_lifecycle_states": {
            "platform": "active",
            "engineering": "active",
        },
        "asset_disposition_plan_refs": {"platform": "merge/assets/platform.json"},
        summary_name: summary,
    }

    report = build_department_merge_preflight(_merge_plan(), **kwargs)

    assert report.status is DepartmentMergePlanStatus.BLOCKED
    assert [item.code for item in report.blocking_items] == [expected_code]


def test_department_merge_preflight_blocks_lifecycle_and_missing_assets():
    report = build_department_merge_preflight(
        _merge_plan(),
        department_lifecycle_states={
            "platform": "archived",
            "engineering": "active",
        },
        asset_disposition_plan_refs={},
    )

    assert report.status is DepartmentMergePlanStatus.BLOCKED
    assert [item.code for item in report.blocking_items] == [
        DepartmentMergePreflightBlockingCode.INVALID_LIFECYCLE_STATE,
        DepartmentMergePreflightBlockingCode.MISSING_ASSET_DISPOSITION_PLAN,
    ]


def test_department_merge_preflight_records_policy_conflicts_without_blocking():
    report = build_department_merge_preflight(
        _merge_plan(
            request=_merge_request(
                source_summaries=[
                    _department_summary(
                        "platform",
                        responsibility_summary="Own release platform reliability work.",
                        leader_worker_id="platform_lead",
                    )
                ],
                target_summary=_department_summary(
                    "engineering",
                    responsibility_summary="Own release platform reliability work.",
                    leader_worker_id="engineering_lead",
                ),
            )
        ),
        department_lifecycle_states={
            "platform": "active",
            "engineering": "active",
        },
        asset_disposition_plan_refs={"platform": "merge/assets/platform.json"},
        policy_summary={
            "budget_model_policies": {
                "platform": {"max_task_tokens": 1000, "default_model": "small"},
                "engineering": {"max_task_tokens": 2000, "default_model": "large"},
            },
            "tool_policies": {
                "platform": ["shell", "read_file"],
                "engineering": ["read_file"],
            },
            "department_playbooks": {
                "platform": "Ship via platform review.",
                "engineering": "Ship via engineering review.",
            },
        },
    )

    assert report.status is DepartmentMergePlanStatus.READY_FOR_APPROVAL
    assert [conflict.code for conflict in report.conflicts] == [
        DepartmentMergePreflightConflictCode.RESPONSIBILITY_OVERLAP,
        DepartmentMergePreflightConflictCode.OWNER_MISMATCH,
        DepartmentMergePreflightConflictCode.BUDGET_MODEL_POLICY_DIFFERENCE,
        DepartmentMergePreflightConflictCode.TOOL_POLICY_DIFFERENCE,
        DepartmentMergePreflightConflictCode.DEPARTMENT_PLAYBOOK_CONFLICT,
    ]
    assert len(report.manual_decisions) == len(report.conflicts)
    assert report.warnings


def test_department_merge_preflight_report_serialization_is_stable():
    report = build_department_merge_preflight(
        _merge_plan(
            request=_merge_request(
                target_summary=_department_summary(
                    "engineering",
                    leader_worker_id="platform_lead",
                )
            )
        ),
        department_lifecycle_states={
            "platform": "active",
            "engineering": "active",
        },
        asset_disposition_plan_refs={"platform": "merge/assets/platform.json"},
        task_state_summary={
            "tasks": {
                "platform": [
                    {
                        "task_id": "task_high_risk",
                        "status": "running",
                        "risk_level": "high",
                    }
                ]
            }
        },
    )

    raw_json = dump_department_merge_preflight_report_json(report)
    loaded = load_department_merge_preflight_report_json(raw_json)

    assert loaded == report
    assert department_merge_preflight_report_to_dict(loaded) == {
        "plan_id": "merge_platform_plan",
        "schema_version": CHILD_AGENT_LIFECYCLE_SCHEMA_VERSION,
        "status": "blocked",
        "blocking_items": [
            {
                "code": "active_high_risk_task",
                "department_id": "platform",
                "summary": "Active high-risk task 'task_high_risk' must be resolved.",
                "source_refs": [],
            }
        ],
        "warnings": [],
        "conflicts": [],
        "manual_decisions": [],
        "source_refs": ["merge/request.json"],
    }

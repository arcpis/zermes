from worker_agents.organization_evolution import (
    CHILD_AGENT_LIFECYCLE_SCHEMA_VERSION,
    ChildAgentChatPolicy,
    ChildAgentDeleteBlockingCheck,
    ChildAgentDeletionMode,
    ChildAgentPrivateAssetDisposition,
    ChildAgentRuntimeKind,
    DepartmentCollaborationSurface,
    DepartmentContractionMode,
    child_agent_create_plan_from_dict,
    child_agent_delete_plan_from_dict,
    plan_department_contraction,
)


def _permission_boundary(**overrides):
    data = {
        "requested_tools": ["read_file"],
        "parent_policy_allowed_tools": ["read_file", "search_docs"],
        "main_policy_allowed_tools": ["read_file", "search_docs", "open_issue"],
        "policy_ref": "policies/platform-child-tools.json",
    }
    data.update(overrides)
    return data


def _budget_policy(**overrides):
    data = {
        "max_task_tokens": 4000,
        "max_turn_tokens": 1000,
        "max_task_cost_usd": 1.25,
        "budget_ref": "budgets/platform-child.json",
    }
    data.update(overrides)
    return data


def _model_policy(**overrides):
    data = {
        "default_model": "fast-model",
        "allowed_models": ["fast-model"],
        "model_policy_ref": "models/platform-child.json",
    }
    data.update(overrides)
    return data


def _create_plan(**overrides):
    data = {
        "plan_id": "create_platform_researcher",
        "schema_version": CHILD_AGENT_LIFECYCLE_SCHEMA_VERSION,
        "child_node_id": "platform_researcher_node",
        "child_name": "Platform Researcher",
        "node_kind": "worker",
        "runtime_kind": "internal_worker",
        "parent_node_id": "platform",
        "responsibility_summary": "Research platform changes and summarize risks.",
        "capability_boundaries": ["read-only repository analysis"],
        "permission_boundary": _permission_boundary(),
        "budget_policy": _budget_policy(),
        "model_policy": _model_policy(),
        "chat_policy": "parent_group_chat",
        "leader_worker_id": "platform_lead",
        "child_worker_id": "platform_researcher",
        "initial_profile_ref": "profiles/platform-researcher-template.json",
        "initial_profile_template_summary": None,
        "external_adapter": None,
        "source_refs": ["proposals/create-platform-researcher.md"],
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
        "replacement_owner": {
            "kind": "worker",
            "worker_id": "platform_lead",
            "org_node_id": None,
            "reason": "Platform lead takes ownership.",
        },
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


def test_lifecycle_create_plans_cover_internal_external_and_team_nodes():
    internal_worker = child_agent_create_plan_from_dict(_create_plan())
    external_agent = child_agent_create_plan_from_dict(
        _create_plan(
            plan_id="create_external_researcher",
            child_node_id="external_researcher_node",
            child_name="External Researcher",
            runtime_kind="external_agent",
            external_adapter={
                "adapter_type": "remote_research_agent",
                "health_check_requirement": "healthy before registry activation",
                "credential_requirement_summary": "uses approved connector only",
            },
        )
    )
    team_node = child_agent_create_plan_from_dict(
        _create_plan(
            plan_id="create_platform_response_team",
            child_node_id="platform_response_team",
            child_name="Platform Response Team",
            node_kind="team",
            runtime_kind="organization_only",
            child_worker_id=None,
            initial_profile_ref=None,
            initial_profile_template_summary="Team node with no runtime identity.",
            chat_policy="department_group_candidate",
        )
    )

    assert internal_worker.runtime_kind is ChildAgentRuntimeKind.INTERNAL_WORKER
    assert external_agent.runtime_kind is ChildAgentRuntimeKind.EXTERNAL_AGENT
    assert external_agent.external_adapter is not None
    assert team_node.runtime_kind is ChildAgentRuntimeKind.ORGANIZATION_ONLY
    assert team_node.chat_policy is ChildAgentChatPolicy.DEPARTMENT_GROUP_CANDIDATE


def test_delete_plan_reports_all_lifecycle_blockers_before_execution():
    plan = child_agent_delete_plan_from_dict(
        _delete_plan(
            active_task_refs=["tasks/task-1/state.json"],
            pending_approval_refs=["approvals/high-risk.json"],
            child_node_ids=["downstream_team"],
            running_session_refs=["runtime/session-1.json"],
            downstream_disposition_refs=["plans/move-downstream-team.json"],
            asset_disposition_refs=[],
            chat_disposition_refs=[],
        )
    )

    assert plan.check_summary.blocking_checks == (
        ChildAgentDeleteBlockingCheck.ACTIVE_TASKS,
        ChildAgentDeleteBlockingCheck.PENDING_APPROVALS,
        ChildAgentDeleteBlockingCheck.CHILD_NODES,
        ChildAgentDeleteBlockingCheck.RUNNING_SESSIONS,
        ChildAgentDeleteBlockingCheck.ASSET_DISPOSITION_MISSING,
        ChildAgentDeleteBlockingCheck.CHAT_DISPOSITION_MISSING,
    )
    assert plan.check_summary.can_enter_pending_approval is False
    assert plan.check_summary.can_execute is False


def test_delete_plan_defaults_private_assets_to_archive():
    data = _delete_plan()
    data.pop("private_asset_disposition")

    plan = child_agent_delete_plan_from_dict(data)

    assert plan.deletion_mode is ChildAgentDeletionMode.ARCHIVE
    assert plan.private_asset_disposition is ChildAgentPrivateAssetDisposition.ARCHIVE


def test_department_contraction_covers_single_worker_and_empty_departments():
    single_worker = plan_department_contraction(
        plan_id="contract_platform_single_worker",
        department_node_id="platform",
        parent_node_id="engineering",
        remaining_worker_ids=("platform_lead",),
        remaining_child_node_ids=(),
        responsibilities_remain=True,
    )
    empty_department = plan_department_contraction(
        plan_id="contract_platform_empty",
        department_node_id="platform",
        parent_node_id="engineering",
        remaining_worker_ids=(),
        remaining_child_node_ids=(),
        responsibilities_remain=False,
        chat_disposition_ref="chats/archive-platform.json",
        asset_disposition_ref="assets/archive-platform.json",
    )

    assert (
        single_worker.contraction_mode
        is DepartmentContractionMode.KEEP_SINGLE_WORKER_DEPARTMENT
    )
    assert (
        single_worker.collaboration_surface
        is DepartmentCollaborationSurface.DIRECT_WORKER_CHAT
    )
    assert empty_department.contraction_mode is DepartmentContractionMode.ARCHIVE_NODE
    assert empty_department.collaboration_surface is DepartmentCollaborationSurface.NONE

import pytest

from worker_agents.organization_evolution import (
    CHILD_AGENT_LIFECYCLE_SCHEMA_VERSION,
    ChildAgentBudgetPolicy,
    ChildAgentChatPolicy,
    ChildAgentCreatePlan,
    ChildAgentExternalAdapterRequirement,
    ChildAgentModelPolicy,
    ChildAgentNodeKind,
    ChildAgentPermissionBoundary,
    ChildAgentRuntimeKind,
    OrganizationEvolutionError,
    child_agent_create_plan_from_dict,
    child_agent_create_plan_to_dict,
    validate_child_agent_create_plan,
)


def _permission_boundary(**overrides):
    data = {
        "requested_tools": ["read_file"],
        "parent_policy_allowed_tools": ["read_file", "search_docs"],
        "main_policy_allowed_tools": ["read_file", "search_docs", "open_issue"],
        "policy_ref": "policies/platform-tools.json",
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


def test_internal_worker_create_plan_is_valid_and_serializable():
    plan = child_agent_create_plan_from_dict(_create_plan())

    loaded = validate_child_agent_create_plan(child_agent_create_plan_to_dict(plan))

    assert loaded == plan
    assert loaded.node_kind is ChildAgentNodeKind.WORKER
    assert loaded.runtime_kind is ChildAgentRuntimeKind.INTERNAL_WORKER
    assert loaded.chat_policy is ChildAgentChatPolicy.PARENT_GROUP_CHAT


def test_create_plan_dataclass_accepts_template_summary_only():
    plan = ChildAgentCreatePlan(
        plan_id="create_platform_team",
        child_node_id="platform_team",
        child_name="Platform Team",
        node_kind=ChildAgentNodeKind.TEAM,
        runtime_kind=ChildAgentRuntimeKind.ORGANIZATION_ONLY,
        parent_node_id="platform",
        responsibility_summary="Coordinate platform delivery work.",
        capability_boundaries=("coordination only",),
        permission_boundary=ChildAgentPermissionBoundary(**_permission_boundary()),
        budget_policy=ChildAgentBudgetPolicy(**_budget_policy()),
        model_policy=ChildAgentModelPolicy(**_model_policy()),
        chat_policy=ChildAgentChatPolicy.DEPARTMENT_GROUP_CANDIDATE,
        initial_profile_template_summary="Team node with no durable worker profile.",
    )

    data = child_agent_create_plan_to_dict(plan)

    assert data["node_kind"] == "team"
    assert data["child_worker_id"] is None


def test_external_agent_create_plan_requires_adapter_requirement():
    with pytest.raises(OrganizationEvolutionError, match="external_adapter"):
        child_agent_create_plan_from_dict(
            _create_plan(
                runtime_kind="external_agent",
                initial_profile_ref="profiles/external-search.json",
            )
        )


def test_external_agent_create_plan_accepts_adapter_requirement():
    plan = child_agent_create_plan_from_dict(
        _create_plan(
            runtime_kind="external_agent",
            external_adapter={
                "adapter_type": "remote_research_agent",
                "health_check_requirement": "healthy before registration",
                "credential_requirement_summary": "uses existing approved connector",
            },
        )
    )

    assert isinstance(plan.external_adapter, ChildAgentExternalAdapterRequirement)
    assert plan.external_adapter.adapter_type == "remote_research_agent"


@pytest.mark.parametrize(
    "field",
    [
        "parent_node_id",
        "responsibility_summary",
        "capability_boundaries",
        "permission_boundary",
        "budget_policy",
    ],
)
def test_create_plan_rejects_missing_required_planning_fields(field):
    data = _create_plan()
    data.pop(field)

    with pytest.raises(OrganizationEvolutionError):
        child_agent_create_plan_from_dict(data)


def test_create_plan_rejects_permission_expansion_beyond_parent_policy():
    data = _create_plan(
        permission_boundary=_permission_boundary(
            requested_tools=["read_file", "write_file"],
            parent_policy_allowed_tools=["read_file"],
        )
    )

    with pytest.raises(OrganizationEvolutionError, match="parent_policy"):
        child_agent_create_plan_from_dict(data)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("plan_id", "delegation-1"),
        ("child_node_id", "temporary-platform-child"),
        ("child_worker_id", "temporary_worker"),
        ("initial_profile_ref", "tasks/task-1/temporary-subagents/delegation-1/request.json"),
    ],
)
def test_create_plan_rejects_temporary_subagent_delegation_identifiers(field, value):
    with pytest.raises(OrganizationEvolutionError, match="temporary subagent"):
        child_agent_create_plan_from_dict(_create_plan(**{field: value}))


def test_create_plan_rejects_sensitive_payload_fields():
    with pytest.raises(OrganizationEvolutionError, match="sensitive data"):
        validate_child_agent_create_plan(_create_plan(secret="not allowed"))

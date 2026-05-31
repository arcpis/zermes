import pytest

from worker_agents.profile import (
    WorkerAgentProfile,
    WorkerBudgetPolicy,
    WorkerDelegationPolicy,
    WorkerExecutionLimits,
    WorkerModelSettings,
    WorkerToolPolicy,
    WorkerWorkspacePolicy,
)
from worker_agents.runtime_contract import RuntimeType
from worker_agents.temporary_subagent_policy import (
    TemporarySubagentPolicyError,
    evaluate_temporary_subagent_policy,
    temporary_subagent_policy_decision_to_dict,
)
from worker_agents.temporary_subagents import (
    TemporarySubagentProfileOverlay,
    TemporarySubagentRequest,
    TemporarySubagentResultReturnPolicy,
)


def _profile(**overrides):
    data = {
        "worker_id": "researcher",
        "display_name": "Researcher",
        "description": "Research focused questions.",
        "role": "research",
        "tools": WorkerToolPolicy(allowed_tools=("read_file", "search_notes")),
        "workspace": WorkerWorkspacePolicy(
            read_roots=("workspace/project",),
            write_roots=("workspace/project/tmp",),
        ),
        "model": WorkerModelSettings(
            default_model="fast-model",
            allowed_models=("fast-model", "accurate-model"),
        ),
        "budgets": WorkerBudgetPolicy(
            max_task_tokens=1000,
            max_turn_tokens=200,
            max_task_cost_usd=2.0,
        ),
        "limits": WorkerExecutionLimits(
            max_concurrent_tasks=2,
            timeout_seconds=60,
        ),
        "delegation": WorkerDelegationPolicy(
            allow_temporary_child_agents=True,
            allowed_child_models=("fast-model",),
            allowed_child_tools=("read_file",),
            max_child_task_tokens=300,
        ),
    }
    data.update(overrides)
    return WorkerAgentProfile(**data)


def _request(**overrides):
    data = {
        "delegation_id": "delegation-1",
        "parent_worker_id": "researcher",
        "task_id": "task-1",
        "purpose": "Explore one narrow question.",
        "requested_runtime_type": RuntimeType.TEMPORARY_SUBAGENT,
        "profile_overlay": TemporarySubagentProfileOverlay(
            role_name="Focused Explorer",
            task_instructions="Use the supplied context only.",
            output_contract="Return findings.",
        ),
        "result_return_policy": TemporarySubagentResultReturnPolicy.PARENT_WORKER_ONLY,
        "requested_model": "fast-model",
        "requested_tools": ("read_file",),
        "workspace_read_roots": ("workspace/project/docs",),
        "workspace_write_roots": ("workspace/project/tmp/child",),
        "max_task_tokens": 250,
        "max_task_cost_usd": 1.0,
        "timeout_seconds": 30,
    }
    data.update(overrides)
    return TemporarySubagentRequest(**data)


def test_policy_allows_request_with_effective_snapshot():
    decision = evaluate_temporary_subagent_policy(_profile(), _request())

    assert decision.allowed is True
    assert decision.effective_policy is not None
    assert decision.effective_policy.allowed_tools == ("read_file",)
    assert decision.effective_policy.model_name == "fast-model"
    assert decision.effective_policy.max_task_tokens == 250

    data = temporary_subagent_policy_decision_to_dict(decision)
    assert data["effective_policy"]["workspace_read_roots"] == [
        "workspace/project/docs"
    ]


def test_policy_denies_when_delegation_is_disabled():
    profile = _profile(
        delegation=WorkerDelegationPolicy(allow_temporary_child_agents=False)
    )

    decision = evaluate_temporary_subagent_policy(profile, _request())

    assert decision.allowed is False
    assert decision.reason_code == "delegation_disabled"


def test_policy_denies_parent_mismatch():
    decision = evaluate_temporary_subagent_policy(
        _profile(worker_id="writer"),
        _request(),
    )

    assert decision.allowed is False
    assert decision.reason_code == "parent_mismatch"


def test_policy_denies_tool_model_budget_and_timeout_expansion():
    assert (
        evaluate_temporary_subagent_policy(
            _profile(),
            _request(requested_tools=("search_notes",)),
        ).reason_code
        == "child_tool_not_allowed"
    )
    assert (
        evaluate_temporary_subagent_policy(
            _profile(),
            _request(requested_model="accurate-model"),
        ).reason_code
        == "child_model_not_allowed"
    )
    assert (
        evaluate_temporary_subagent_policy(
            _profile(),
            _request(max_task_tokens=500),
        ).reason_code
        == "child_token_budget_exceeded"
    )
    assert (
        evaluate_temporary_subagent_policy(
            _profile(),
            _request(timeout_seconds=120),
        ).reason_code
        == "timeout_exceeded"
    )


def test_policy_denies_workspace_escape_and_concurrency_limit():
    assert (
        evaluate_temporary_subagent_policy(
            _profile(),
            _request(workspace_read_roots=("workspace/other",)),
        ).reason_code
        == "read_workspace_out_of_bounds"
    )
    assert (
        evaluate_temporary_subagent_policy(
            _profile(),
            _request(workspace_write_roots=("workspace/project/docs",)),
        ).reason_code
        == "write_workspace_out_of_bounds"
    )
    assert (
        evaluate_temporary_subagent_policy(
            _profile(),
            _request(),
            active_child_count=2,
        ).reason_code
        == "concurrency_limit"
    )


def test_policy_rejects_unbounded_or_escaping_workspace_paths():
    with pytest.raises(TemporarySubagentPolicyError, match="bounded"):
        evaluate_temporary_subagent_policy(
            _profile(workspace=WorkerWorkspacePolicy(read_roots=("*",))),
            _request(),
        )

    with pytest.raises(TemporarySubagentPolicyError, match="escape"):
        evaluate_temporary_subagent_policy(
            _profile(),
            _request(workspace_read_roots=("../outside",)),
        )

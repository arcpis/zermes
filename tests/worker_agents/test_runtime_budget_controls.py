import pytest

from worker_agents.runtime_contract import RuntimeExecutionBudget
from worker_agents.runtime_resources import (
    RuntimeBudgetPolicy,
    RuntimeBudgetSource,
    RuntimeBudgetViolationKind,
    RuntimeResourceError,
    RuntimeResourceUsage,
    resolve_runtime_budget,
    runtime_budget_policy_from_execution_budget,
    runtime_budget_snapshot_to_dict,
    runtime_resource_usage_to_audit_summary,
    runtime_budget_violation_to_dict,
    validate_runtime_usage,
)


def _defaults():
    return RuntimeBudgetPolicy(
        source=RuntimeBudgetSource.DEFAULT_LIMITS,
        source_ref="defaults",
        max_input_tokens=4000,
        max_output_tokens=1000,
        max_total_tokens=5000,
        max_cost_units=2.0,
        max_wall_time_seconds=120,
        max_output_bytes=20000,
        max_transcript_bytes=80000,
        max_retry_attempts=1,
        max_concurrent_children=2,
    )


def test_budget_resolver_uses_strictest_limits():
    worker_policy = RuntimeBudgetPolicy(
        source=RuntimeBudgetSource.WORKER_PROFILE,
        source_ref="worker:frontend",
        max_input_tokens=3000,
        max_output_tokens=900,
        max_total_tokens=3900,
        max_cost_units=1.5,
        max_wall_time_seconds=90,
        max_output_bytes=15000,
        max_transcript_bytes=60000,
        max_retry_attempts=1,
        max_concurrent_children=1,
    )
    task_policy = RuntimeBudgetPolicy(
        source=RuntimeBudgetSource.TASK_REQUEST,
        source_ref="task:task-1",
        max_output_tokens=500,
        max_wall_time_seconds=30,
    )

    budget = resolve_runtime_budget((worker_policy, task_policy), defaults=_defaults())

    assert budget.max_input_tokens == 3000
    assert budget.max_output_tokens == 500
    assert budget.max_wall_time_seconds == 30
    assert budget.max_concurrent_children == 1
    assert runtime_budget_snapshot_to_dict(budget)["source_refs"] == [
        "defaults",
        "worker:frontend",
        "task:task-1",
    ]


def test_budget_resolver_rejects_missing_effective_limit():
    defaults = RuntimeBudgetPolicy(
        source=RuntimeBudgetSource.DEFAULT_LIMITS,
        source_ref="defaults",
        max_input_tokens=4000,
    )

    with pytest.raises(RuntimeResourceError, match="max_output_tokens"):
        resolve_runtime_budget((), defaults=defaults)


def test_runtime_request_budget_converts_to_policy():
    request_budget = RuntimeExecutionBudget(
        budget_source="worker-profile:researcher",
        max_input_tokens=1000,
        max_output_tokens=300,
        max_cost_usd=0.4,
        timeout_seconds=45,
        max_output_bytes=8000,
        max_transcript_bytes=16000,
    )

    policy = runtime_budget_policy_from_execution_budget(request_budget)

    assert policy.source == RuntimeBudgetSource.WORKER_PROFILE
    assert policy.max_total_tokens == 1300
    assert policy.max_cost_units == 0.4


def test_runtime_usage_reports_budget_violations_without_content():
    budget = resolve_runtime_budget((), defaults=_defaults())
    usage = RuntimeResourceUsage(
        input_tokens=4200,
        output_tokens=900,
        cost_units=2.1,
        wall_time_seconds=30,
        output_bytes=100,
        transcript_bytes=100,
    )

    violations = validate_runtime_usage(usage, budget)

    assert [violation.kind for violation in violations] == [
        RuntimeBudgetViolationKind.INPUT_TOKENS,
        RuntimeBudgetViolationKind.TOTAL_TOKENS,
        RuntimeBudgetViolationKind.COST,
    ]
    assert runtime_budget_violation_to_dict(violations[0])["source_refs"] == [
        "defaults"
    ]


def test_usage_audit_summary_is_counter_only():
    usage = RuntimeResourceUsage(input_tokens=10, output_tokens=5, transcript_bytes=50)

    summary = runtime_resource_usage_to_audit_summary(usage)

    assert summary["total_tokens"] == 15
    assert "prompt" not in summary
    assert "transcript" not in set(summary) - {"transcript_bytes"}

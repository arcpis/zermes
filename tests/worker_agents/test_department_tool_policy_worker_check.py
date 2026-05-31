from worker_agents.department_tool_policies import (
    DepartmentToolPolicyRecord,
    DepartmentToolPolicyResolutionInput,
    DepartmentToolRuleEffect,
    WorkerToolPolicyBlockReason,
    WorkerToolPolicyCheckInput,
    cross_check_department_tool_policy_with_worker,
    resolve_department_tool_policies,
    worker_effective_tool_policy_to_dict,
)
from worker_agents.tool_permission_snapshot import WorkerToolPermissionSnapshot


def _worker_snapshot(**overrides):
    values = {
        "worker_id": "frontend",
        "profile_hash": "sha256:profile",
        "allowed_tools": ("read_file", "write_file"),
        "approval_required_tools": ("network",),
        "read_roots": ("repo",),
        "write_roots": ("repo/src",),
        "max_task_tokens": 2000,
        "max_turn_tokens": 500,
        "max_task_cost_usd": 1.0,
    }
    values.update(overrides)
    return WorkerToolPermissionSnapshot(**values)


def _resolved_policy(*policies):
    return resolve_department_tool_policies(
        DepartmentToolPolicyResolutionInput(
            target_department_id="platform",
            policies=tuple(policies),
        )
    )


def _policy(**overrides):
    values = {
        "department_id": "platform",
        "policy_id": "read-policy",
        "tool_refs": ("read_file",),
        "effect": DepartmentToolRuleEffect.ALLOW,
    }
    values.update(overrides)
    return DepartmentToolPolicyRecord(**values)


def test_worker_check_keeps_only_tools_allowed_by_profile():
    resolved = _resolved_policy(
        _policy(tool_refs=("read_file", "shell")),
    )
    effective = cross_check_department_tool_policy_with_worker(
        WorkerToolPolicyCheckInput(
            resolved_policy=resolved,
            worker_snapshot=_worker_snapshot(),
        )
    )

    assert effective.allowed_tools == ("read_file",)
    assert effective.blocked_items[0].item_ref == "shell"
    assert effective.blocked_items[0].reason == (
        WorkerToolPolicyBlockReason.PROFILE_DISALLOWS_TOOL
    )


def test_worker_check_preserves_department_deny_even_when_profile_allows_tool():
    resolved = _resolved_policy(
        _policy(
            policy_id="deny-write",
            tool_refs=("write_file",),
            effect=DepartmentToolRuleEffect.DENY,
        )
    )
    effective = cross_check_department_tool_policy_with_worker(
        WorkerToolPolicyCheckInput(
            resolved_policy=resolved,
            worker_snapshot=_worker_snapshot(),
        )
    )

    assert effective.denied_tools == ("write_file",)
    assert effective.allowed_tools == ()


def test_worker_check_routes_profile_approval_tools_to_approval_required():
    resolved = _resolved_policy(
        _policy(
            policy_id="network-policy",
            tool_refs=("network",),
            effect=DepartmentToolRuleEffect.ALLOW,
        )
    )
    effective = cross_check_department_tool_policy_with_worker(
        WorkerToolPolicyCheckInput(
            resolved_policy=resolved,
            worker_snapshot=_worker_snapshot(),
        )
    )

    assert effective.allowed_tools == ()
    assert effective.approval_required_tools == ("network",)


def test_worker_check_rejects_workspace_and_budget_outside_profile():
    resolved = _resolved_policy(
        _policy(
            policy_id="write-policy",
            tool_refs=("write_file",),
            workspace_read_roots=("repo", "private"),
            workspace_write_roots=("repo/src", "repo/secrets"),
            max_task_tokens=4000,
            max_turn_tokens=800,
            max_task_cost_usd=5.0,
        )
    )
    effective = cross_check_department_tool_policy_with_worker(
        WorkerToolPolicyCheckInput(
            resolved_policy=resolved,
            worker_snapshot=_worker_snapshot(),
        )
    )

    reasons = {item.reason for item in effective.blocked_items}
    assert WorkerToolPolicyBlockReason.WORKSPACE_OUT_OF_SCOPE in reasons
    assert WorkerToolPolicyBlockReason.BUDGET_EXCEEDS_PROFILE in reasons
    assert effective.workspace_read_roots == ("repo",)
    assert effective.workspace_write_roots == ("repo/src",)
    assert effective.max_task_tokens == 2000
    assert effective.max_turn_tokens == 500
    assert effective.max_task_cost_usd == 1.0


def test_external_runtime_is_summary_only_without_expanding_permissions():
    resolved = _resolved_policy(_policy())
    effective = cross_check_department_tool_policy_with_worker(
        WorkerToolPolicyCheckInput(
            resolved_policy=resolved,
            worker_snapshot=_worker_snapshot(),
            runtime_type="external_adapter",
        )
    )

    assert effective.external_runtime_summary_only is True
    assert WorkerToolPolicyBlockReason.EXTERNAL_RUNTIME_RESTRICTED in {
        item.reason for item in effective.blocked_items
    }
    payload = worker_effective_tool_policy_to_dict(effective)
    assert "env" not in payload
    assert "credential" not in payload
    assert payload["profile_snapshot_hash"] == "sha256:profile"

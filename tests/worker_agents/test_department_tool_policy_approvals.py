from worker_agents.department_tool_policies import (
    DepartmentToolPolicyRecord,
    DepartmentToolPolicyResolutionInput,
    DepartmentToolRuleEffect,
    HighRiskToolApprovalReason,
    ToolApprovalBuildInput,
    ToolApprovalDecision,
    ToolApprovalDecisionState,
    WorkerToolPolicyCheckInput,
    approved_tool_policy_refs_from_decisions,
    build_tool_approval_requests,
    cross_check_department_tool_policy_with_worker,
    resolve_department_tool_policies,
    tool_approval_decision_to_dict,
    tool_approval_request_to_dict,
)
from worker_agents.tool_permission_snapshot import WorkerToolPermissionSnapshot


def _worker_snapshot(**overrides):
    values = {
        "worker_id": "frontend",
        "profile_hash": "sha256:profile",
        "allowed_tools": ("read_file", "write_file", "network"),
        "approval_required_tools": ("shell",),
        "read_roots": ("repo",),
        "write_roots": ("repo/src",),
        "max_task_tokens": 2000,
        "max_turn_tokens": 500,
        "max_task_cost_usd": 1.0,
    }
    values.update(overrides)
    return WorkerToolPermissionSnapshot(**values)


def _effective(*policies, runtime_type="internal_worker"):
    resolved = resolve_department_tool_policies(
        DepartmentToolPolicyResolutionInput(
            target_department_id="platform",
            policies=tuple(policies),
        )
    )
    return cross_check_department_tool_policy_with_worker(
        WorkerToolPolicyCheckInput(
            resolved_policy=resolved,
            worker_snapshot=_worker_snapshot(),
            runtime_type=runtime_type,
        )
    )


def _policy(**overrides):
    values = {
        "department_id": "platform",
        "policy_id": "write-policy",
        "tool_refs": ("write_file",),
        "effect": DepartmentToolRuleEffect.REQUIRES_APPROVAL,
    }
    values.update(overrides)
    return DepartmentToolPolicyRecord(**values)


def test_write_tool_generates_approval_request_without_credentials():
    effective = _effective(_policy())
    requests = build_tool_approval_requests(
        ToolApprovalBuildInput(
            effective_policy=effective,
            task_id="task-1",
            created_at="2026-05-22T00:00:00Z",
            expires_at="2026-05-23T00:00:00Z",
        )
    )

    assert len(requests) == 1
    assert requests[0].risk_reasons == (HighRiskToolApprovalReason.WRITE_ACCESS,)
    payload = tool_approval_request_to_dict(requests[0])
    assert payload["tool_refs"] == ["write_file"]
    assert "credential" not in payload
    assert "token" not in payload
    assert "env" not in payload


def test_network_and_shell_tools_generate_distinct_risk_reasons():
    effective = _effective(
        _policy(
            policy_id="network-policy",
            tool_refs=("network",),
            effect=DepartmentToolRuleEffect.REQUIRES_APPROVAL,
        ),
        _policy(
            policy_id="shell-policy",
            tool_refs=("shell",),
            effect=DepartmentToolRuleEffect.REQUIRES_APPROVAL,
        ),
    )
    requests = build_tool_approval_requests(
        ToolApprovalBuildInput(effective_policy=effective, task_id="task-1")
    )
    reasons_by_tool = {
        request.tool_refs[0]: set(request.risk_reasons) for request in requests
    }

    assert HighRiskToolApprovalReason.NETWORK_ACCESS in reasons_by_tool["network"]
    assert HighRiskToolApprovalReason.EXTERNAL_EXECUTION in reasons_by_tool["shell"]


def test_budget_and_policy_relaxation_generate_approval_requests():
    effective = _effective(
        _policy(
            policy_id="budget-policy",
            tool_refs=("read_file",),
            effect=DepartmentToolRuleEffect.ALLOW,
            max_task_tokens=4000,
        )
    )
    requests = build_tool_approval_requests(
        ToolApprovalBuildInput(
            effective_policy=effective,
            task_id="task-1",
            blocked_relaxation_refs=("platform/relaxed-write",),
        )
    )
    reason_sets = [set(request.risk_reasons) for request in requests]

    assert {HighRiskToolApprovalReason.BUDGET_INCREASE,
            HighRiskToolApprovalReason.MODEL_OR_RUNTIME_COST} in reason_sets
    assert {HighRiskToolApprovalReason.POLICY_RELAXATION} in reason_sets


def test_external_runtime_generates_summary_only_approval_request():
    effective = _effective(_policy(effect=DepartmentToolRuleEffect.ALLOW), runtime_type="external_adapter")
    requests = build_tool_approval_requests(
        ToolApprovalBuildInput(effective_policy=effective, task_id="task-1")
    )

    assert requests[-1].risk_reasons == (
        HighRiskToolApprovalReason.EXTERNAL_RUNTIME_ACCESS,
    )


def test_only_matching_approved_decisions_return_refs():
    effective = _effective(_policy())
    requests = build_tool_approval_requests(
        ToolApprovalBuildInput(effective_policy=effective, task_id="task-1")
    )
    approved = ToolApprovalDecision(
        request_id=requests[0].request_id,
        decision=ToolApprovalDecisionState.APPROVED,
        reviewer_id="user",
        profile_snapshot_hash="sha256:profile",
        decided_at="2026-05-22T01:00:00Z",
    )
    rejected = ToolApprovalDecision(
        request_id=requests[0].request_id,
        decision=ToolApprovalDecisionState.REJECTED,
        reviewer_id="user",
        profile_snapshot_hash="sha256:profile",
        decided_at="2026-05-22T01:00:00Z",
    )
    stale_hash = ToolApprovalDecision(
        request_id=requests[0].request_id,
        decision=ToolApprovalDecisionState.APPROVED,
        reviewer_id="user",
        profile_snapshot_hash="sha256:old",
        decided_at="2026-05-22T01:00:00Z",
    )

    assert approved_tool_policy_refs_from_decisions(requests, (approved,)) == (
        "write_file",
    )
    assert approved_tool_policy_refs_from_decisions(requests, (rejected,)) == ()
    assert approved_tool_policy_refs_from_decisions(requests, (stale_hash,)) == ()
    assert tool_approval_decision_to_dict(approved)["decision"] == "approved"

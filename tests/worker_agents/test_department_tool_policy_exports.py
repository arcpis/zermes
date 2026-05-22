from worker_agents import (
    DEPARTMENT_TOOL_POLICY_SCHEMA_VERSION,
    DepartmentToolPolicyRecord,
    DepartmentToolPolicyResolutionInput,
    DepartmentToolPolicyState,
    DepartmentToolRiskLevel,
    DepartmentToolRuleEffect,
    HighRiskToolApprovalReason,
    ToolApprovalBuildInput,
    ToolApprovalDecisionState,
    WorkerToolPolicyBlockReason,
    build_tool_approval_requests,
    cross_check_department_tool_policy_with_worker,
    department_tool_policy_to_dict,
    resolve_department_tool_policies,
    worker_effective_tool_policy_to_dict,
)


def test_department_tool_policy_exports_are_available_from_package():
    assert DEPARTMENT_TOOL_POLICY_SCHEMA_VERSION == 1
    assert DepartmentToolPolicyState.ACTIVE.value == "active"
    assert DepartmentToolRiskLevel.HIGH.value == "high"
    assert DepartmentToolRuleEffect.REQUIRES_APPROVAL.value == "requires_approval"
    assert HighRiskToolApprovalReason.WRITE_ACCESS.value == "write_access"
    assert WorkerToolPolicyBlockReason.PROFILE_DISALLOWS_TOOL.value == (
        "profile_disallows_tool"
    )
    assert ToolApprovalDecisionState.APPROVED.value == "approved"
    assert DepartmentToolPolicyRecord.__name__ == "DepartmentToolPolicyRecord"
    assert DepartmentToolPolicyResolutionInput.__name__ == (
        "DepartmentToolPolicyResolutionInput"
    )
    assert ToolApprovalBuildInput.__name__ == "ToolApprovalBuildInput"
    assert department_tool_policy_to_dict.__name__ == "department_tool_policy_to_dict"
    assert resolve_department_tool_policies.__name__ == (
        "resolve_department_tool_policies"
    )
    assert cross_check_department_tool_policy_with_worker.__name__ == (
        "cross_check_department_tool_policy_with_worker"
    )
    assert build_tool_approval_requests.__name__ == "build_tool_approval_requests"
    assert worker_effective_tool_policy_to_dict.__name__ == (
        "worker_effective_tool_policy_to_dict"
    )

from worker_agents.department_tool_policies import (
    DepartmentToolPolicyConflictReason,
    DepartmentToolPolicyRecord,
    DepartmentToolPolicyResolutionInput,
    DepartmentToolPolicyVisibility,
    DepartmentToolRiskLevel,
    DepartmentToolRuleEffect,
    resolve_department_tool_policies,
    resolved_department_tool_policy_to_dict,
)


def _policy(**overrides):
    values = {
        "department_id": "platform",
        "policy_id": "read-policy",
        "tool_refs": ("read_file",),
        "effect": DepartmentToolRuleEffect.ALLOW,
        "risk_level": DepartmentToolRiskLevel.LOW,
    }
    values.update(overrides)
    return DepartmentToolPolicyRecord(**values)


def test_resolve_inherits_only_public_department_tool_policies():
    inherited_private = _policy(
        department_id="parent",
        policy_id="private-read",
        tool_refs=("read_file",),
        visibility=DepartmentToolPolicyVisibility.DEPARTMENT_ONLY,
    )
    inherited_public = _policy(
        department_id="parent",
        policy_id="public-search",
        tool_refs=("search",),
        visibility=DepartmentToolPolicyVisibility.INHERITABLE_POLICY,
    )

    resolved = resolve_department_tool_policies(
        DepartmentToolPolicyResolutionInput(
            target_department_id="child",
            inherited_department_ids=("parent",),
            policies=(inherited_private, inherited_public),
        )
    )

    assert resolved.snapshot.allowed_tools == ("search",)
    assert resolved.snapshot.policy_refs == ("parent/public-search",)


def test_local_deny_overrides_inherited_allow():
    parent = _policy(
        department_id="parent",
        policy_id="parent-shell",
        tool_refs=("shell",),
        visibility=DepartmentToolPolicyVisibility.INHERITABLE_POLICY,
    )
    child = _policy(
        department_id="child",
        policy_id="child-deny-shell",
        tool_refs=("shell",),
        effect=DepartmentToolRuleEffect.DENY,
        risk_level=DepartmentToolRiskLevel.RESTRICTED,
    )

    resolved = resolve_department_tool_policies(
        DepartmentToolPolicyResolutionInput(
            target_department_id="child",
            inherited_department_ids=("parent",),
            policies=(parent, child),
        )
    )

    assert resolved.snapshot.denied_tools == ("shell",)
    assert resolved.conflicts == ()


def test_parent_deny_blocks_child_relaxation_without_approval():
    parent = _policy(
        department_id="parent",
        policy_id="parent-deny-shell",
        tool_refs=("shell",),
        effect=DepartmentToolRuleEffect.DENY,
        visibility=DepartmentToolPolicyVisibility.INHERITABLE_POLICY,
    )
    child = _policy(
        department_id="child",
        policy_id="child-allow-shell",
        tool_refs=("shell",),
        effect=DepartmentToolRuleEffect.ALLOW,
    )

    resolved = resolve_department_tool_policies(
        DepartmentToolPolicyResolutionInput(
            target_department_id="child",
            inherited_department_ids=("parent",),
            policies=(parent, child),
        )
    )

    assert resolved.snapshot.denied_tools == ("shell",)
    assert resolved.blocked_relaxation_refs == ("child/child-allow-shell",)
    assert DepartmentToolPolicyConflictReason.PARENT_DENIES_TOOL in {
        conflict.reason for conflict in resolved.conflicts
    }


def test_approved_child_relaxation_can_replace_inherited_approval_requirement():
    parent = _policy(
        department_id="parent",
        policy_id="parent-write",
        tool_refs=("write_file",),
        effect=DepartmentToolRuleEffect.REQUIRES_APPROVAL,
        risk_level=DepartmentToolRiskLevel.HIGH,
        visibility=DepartmentToolPolicyVisibility.INHERITABLE_POLICY,
    )
    child = _policy(
        department_id="child",
        policy_id="child-write",
        tool_refs=("write_file",),
        effect=DepartmentToolRuleEffect.ALLOW,
        risk_level=DepartmentToolRiskLevel.MEDIUM,
    )

    resolved = resolve_department_tool_policies(
        DepartmentToolPolicyResolutionInput(
            target_department_id="child",
            inherited_department_ids=("parent",),
            policies=(parent, child),
            approved_relaxation_refs=("child/child-write",),
        )
    )

    assert resolved.snapshot.allowed_tools == ("write_file",)
    assert resolved.conflicts == ()


def test_workspace_and_budget_expansion_need_approval():
    parent = _policy(
        department_id="parent",
        policy_id="parent-write",
        tool_refs=("write_file",),
        effect=DepartmentToolRuleEffect.ALLOW,
        workspace_write_roots=("repo/src",),
        max_task_tokens=1000,
        visibility=DepartmentToolPolicyVisibility.INHERITABLE_POLICY,
    )
    child = _policy(
        department_id="child",
        policy_id="child-write",
        tool_refs=("write_file",),
        effect=DepartmentToolRuleEffect.ALLOW,
        workspace_write_roots=("repo/src", "repo/secrets"),
        max_task_tokens=2000,
    )

    resolved = resolve_department_tool_policies(
        DepartmentToolPolicyResolutionInput(
            target_department_id="child",
            inherited_department_ids=("parent",),
            policies=(parent, child),
        )
    )

    reasons = {conflict.reason for conflict in resolved.conflicts}
    assert DepartmentToolPolicyConflictReason.WORKSPACE_SCOPE_EXPANDED in reasons
    assert DepartmentToolPolicyConflictReason.BUDGET_INCREASED in reasons
    assert resolved.snapshot.workspace_write_roots == ("repo/src",)
    assert resolved.snapshot.max_task_tokens == 1000


def test_task_constraint_can_tighten_local_policy():
    local = _policy(
        department_id="platform",
        policy_id="allow-network",
        tool_refs=("network",),
        effect=DepartmentToolRuleEffect.ALLOW,
    )
    task_constraint = _policy(
        department_id="platform",
        policy_id="task-network-approval",
        tool_refs=("network",),
        effect=DepartmentToolRuleEffect.REQUIRES_USER_CONFIRMATION,
        risk_level=DepartmentToolRiskLevel.HIGH,
    )

    resolved = resolve_department_tool_policies(
        DepartmentToolPolicyResolutionInput(
            target_department_id="platform",
            policies=(local,),
            task_constraints=(task_constraint,),
        )
    )

    assert resolved.snapshot.user_confirmation_required_tools == ("network",)
    assert resolved.snapshot.allowed_tools == ()


def test_resolved_policy_serializes_conflicts():
    parent = _policy(
        department_id="parent",
        policy_id="deny-shell",
        tool_refs=("shell",),
        effect=DepartmentToolRuleEffect.DENY,
        visibility=DepartmentToolPolicyVisibility.INHERITABLE_POLICY,
    )
    child = _policy(
        department_id="child",
        policy_id="allow-shell",
        tool_refs=("shell",),
        effect=DepartmentToolRuleEffect.ALLOW,
    )
    resolved = resolve_department_tool_policies(
        DepartmentToolPolicyResolutionInput(
            target_department_id="child",
            inherited_department_ids=("parent",),
            policies=(parent, child),
        )
    )

    payload = resolved_department_tool_policy_to_dict(resolved)

    assert payload["snapshot"]["denied_tools"] == ["shell"]
    assert payload["conflicts"][0]["reason"] == "parent_denies_tool"

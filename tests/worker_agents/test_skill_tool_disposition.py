from worker_agents.department_skills import DepartmentSkillBindingRecord
from worker_agents.department_tool_policies import (
    DepartmentToolPolicyRecord,
    DepartmentToolPolicySnapshot,
    DepartmentToolRiskLevel,
    DepartmentToolRuleEffect,
)
from worker_agents.organization_asset_disposition import (
    GovernanceDispositionPolicy,
    PermissionDispositionDecision,
    PermissionDispositionFindingCode,
    SkillDispositionDecision,
    SkillExperienceDispositionDecision,
    SkillExperienceDispositionInput,
    ToolPolicyDispositionDecision,
    ToolPolicyDispositionItemKind,
    plan_skill_disposition,
    plan_tool_policy_disposition,
    review_disposition_permissions,
)
from worker_agents.private_assets import PrivateAssetSensitivity
from worker_agents.private_skill_experience import PrivateSkillExperience
from worker_agents.tool_permission_snapshot import WorkerToolPermissionSnapshot


def test_skill_and_tool_disposition_keeps_blocked_items_out_of_active_candidates():
    skill_plan = plan_skill_disposition(
        source_department_id="source-dept",
        target_department_id="target-dept",
        source_bindings=(
            DepartmentSkillBindingRecord(
                department_id="source-dept",
                binding_id="missing-skill",
                skill_id="missing_skill",
                skill_source="profile_skill_registry",
                usage_guidance="Use only if available.",
            ),
            DepartmentSkillBindingRecord(
                department_id="source-dept",
                binding_id="browser-skill",
                skill_id="browser_skill",
                skill_source="profile_skill_registry",
                usage_guidance="Use only with browser access.",
                tool_assumptions=("browser",),
            ),
        ),
        available_skill_ids=("browser_skill",),
        available_tool_ids=("terminal",),
        experiences=(
            SkillExperienceDispositionInput(
                experience=PrivateSkillExperience(
                    worker_id="worker-1",
                    experience_id="exp-1",
                    skill_id="browser_skill",
                    summary="Personal workflow note.",
                    applicability="browser work",
                    shareable=True,
                    sensitivity=PrivateAssetSensitivity.LOW,
                ),
                redacted=False,
                personalization_removed=False,
            ),
        ),
    )
    tool_plan = plan_tool_policy_disposition(
        source_department_id="source-dept",
        target_department_id="target-dept",
        source_policies=(
            DepartmentToolPolicyRecord(
                department_id="source-dept",
                policy_id="deny-shell",
                tool_refs=("shell",),
                effect=DepartmentToolRuleEffect.DENY,
            ),
            DepartmentToolPolicyRecord(
                department_id="source-dept",
                policy_id="network-policy",
                tool_refs=("network",),
                effect=DepartmentToolRuleEffect.ALLOW,
                risk_level=DepartmentToolRiskLevel.HIGH,
            ),
        ),
        target_allowed_tool_ids=("network",),
    )

    assert [item.decision for item in skill_plan.binding_dispositions] == [
        SkillDispositionDecision.MISSING_DEPENDENCY,
        SkillDispositionDecision.REFERENCES_UNAVAILABLE_TOOL,
    ]
    assert skill_plan.active_binding_candidate_refs == ()
    assert skill_plan.experience_dispositions[0].decision == (
        SkillExperienceDispositionDecision.REQUIRES_USER_REVIEW
    )
    assert tool_plan.policy_dispositions[0].decision == (
        ToolPolicyDispositionDecision.CONSERVATIVE_CANDIDATE
    )
    assert tool_plan.policy_dispositions[1].item_kind == (
        ToolPolicyDispositionItemKind.HIGH_RISK_TOOL
    )
    assert tool_plan.target_active_write_candidate_refs == (
        "departments/source-dept/policies/tools/deny-shell",
    )


def test_permission_review_summarizes_high_risk_and_profile_conflicts():
    tool_plan = plan_tool_policy_disposition(
        source_department_id="source-dept",
        target_department_id="target-dept",
        source_policies=(
            DepartmentToolPolicyRecord(
                department_id="source-dept",
                policy_id="network-policy",
                tool_refs=("network",),
                effect=DepartmentToolRuleEffect.ALLOW,
                risk_level=DepartmentToolRiskLevel.HIGH,
            ),
            DepartmentToolPolicyRecord(
                department_id="source-dept",
                policy_id="workspace-policy",
                tool_refs=("read_file",),
                effect=DepartmentToolRuleEffect.ALLOW,
                workspace_write_roots=("repo/secrets",),
            ),
        ),
        target_allowed_tool_ids=("network", "read_file"),
    )

    review = review_disposition_permissions(
        tool_policy_plan=tool_plan,
        target_department_policy=DepartmentToolPolicySnapshot(
            department_id="target-dept",
            allowed_tools=("network", "read_file"),
            workspace_write_roots=("repo",),
        ),
        worker_permission_snapshot=WorkerToolPermissionSnapshot(
            worker_id="worker-1",
            profile_hash="sha256:profile",
            allowed_tools=("read_file",),
            write_roots=("repo/src",),
            max_task_tokens=1000,
            max_turn_tokens=250,
            max_task_cost_usd=1.0,
        ),
        governance_policy=GovernanceDispositionPolicy(high_risk_tools=("network",)),
    )

    decisions = {item.item_ref: item for item in review.items}
    network_item = decisions["departments/source-dept/policies/tools/network-policy"]
    workspace_item = decisions["departments/source-dept/policies/tools/workspace-policy"]

    assert network_item.decision == PermissionDispositionDecision.BLOCKED
    assert PermissionDispositionFindingCode.PROFILE_DENIES_TOOL.value in (
        network_item.finding_codes
    )
    assert (
        PermissionDispositionFindingCode.HIGH_RISK_APPROVAL_MISSING.value
        in network_item.finding_codes
    )
    assert workspace_item.decision == PermissionDispositionDecision.REQUIRES_APPROVAL
    assert "workspace_permission_user_approval" in (
        workspace_item.approval_requirements
    )
    assert review.approval_summary == "1 disposition item(s) require approval"
    assert review.blocking_summary == "1 disposition item(s) are blocked"

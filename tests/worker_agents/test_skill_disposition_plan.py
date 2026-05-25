import pytest

from worker_agents.department_skills import (
    DepartmentSkillBindingRecord,
    DepartmentSkillBindingState,
)
from worker_agents.department_tool_policies import (
    DepartmentToolPolicySnapshot,
    DepartmentToolPolicyRecord,
    DepartmentToolRiskLevel,
    DepartmentToolRuleEffect,
)
from worker_agents.organization_asset_disposition import (
    GovernanceDispositionPolicy,
    OrganizationAssetDispositionError,
    PermissionDispositionDecision,
    PermissionDispositionFindingCode,
    SkillDispositionDecision,
    SkillExperienceDispositionDecision,
    SkillExperienceDispositionInput,
    ToolPolicyDispositionDecision,
    ToolPolicyDispositionItemKind,
    plan_skill_disposition,
    plan_tool_policy_disposition,
    permission_disposition_review_from_dict,
    permission_disposition_review_to_dict,
    review_disposition_permissions,
    skill_disposition_plan_from_dict,
    skill_disposition_plan_to_dict,
    tool_policy_disposition_plan_from_dict,
    tool_policy_disposition_plan_to_dict,
)
from worker_agents.private_assets import PrivateAssetSensitivity
from worker_agents.private_skill_experience import PrivateSkillExperience
from worker_agents.tool_permission_snapshot import WorkerToolPermissionSnapshot


def _binding(
    *,
    department_id: str = "source-dept",
    binding_id: str = "release-review",
    skill_id: str = "release_review",
    state: DepartmentSkillBindingState = DepartmentSkillBindingState.RECOMMENDED,
    tool_assumptions: tuple[str, ...] = (),
) -> DepartmentSkillBindingRecord:
    return DepartmentSkillBindingRecord(
        department_id=department_id,
        binding_id=binding_id,
        skill_id=skill_id,
        skill_source="profile_skill_registry",
        usage_guidance="Use for release review tasks.",
        state=state,
        tool_assumptions=tool_assumptions,
        source_refs=("tasks/task-1/summary.json",),
    )


def _experience(
    *,
    shareable: bool = True,
    sensitivity: PrivateAssetSensitivity = PrivateAssetSensitivity.LOW,
) -> PrivateSkillExperience:
    return PrivateSkillExperience(
        worker_id="worker-1",
        experience_id="exp-1",
        skill_id="release_review",
        summary="Review release handoffs against the checklist.",
        applicability="release review",
        source_refs=("workers/worker-1/experiences/exp-1.json",),
        shareable=shareable,
        sensitivity=sensitivity,
    )


def _tool_policy(**overrides) -> DepartmentToolPolicyRecord:
    values = {
        "department_id": "source-dept",
        "policy_id": "read-policy",
        "tool_refs": ("read_file",),
        "effect": DepartmentToolRuleEffect.ALLOW,
        "source_refs": ("tasks/task-1/tool-policy.json",),
    }
    values.update(overrides)
    return DepartmentToolPolicyRecord(**values)


def _target_policy(**overrides) -> DepartmentToolPolicySnapshot:
    values = {
        "department_id": "target-dept",
        "allowed_tools": ("read_file",),
        "policy_refs": ("departments/target-dept/policies/tools/read-policy",),
    }
    values.update(overrides)
    return DepartmentToolPolicySnapshot(**values)


def _worker_snapshot(**overrides) -> WorkerToolPermissionSnapshot:
    values = {
        "worker_id": "worker-1",
        "profile_hash": "sha256:profile",
        "allowed_tools": ("read_file",),
        "approval_required_tools": (),
        "read_roots": ("repo",),
        "write_roots": ("repo/src",),
        "max_task_tokens": 1000,
        "max_turn_tokens": 250,
        "max_task_cost_usd": 1.0,
    }
    values.update(overrides)
    return WorkerToolPermissionSnapshot(**values)


def test_skill_disposition_marks_existing_target_binding():
    plan = plan_skill_disposition(
        source_department_id="source-dept",
        target_department_id="target-dept",
        source_bindings=(_binding(),),
        target_bindings=(
            _binding(department_id="target-dept", binding_id="existing"),
        ),
        available_skill_ids=("release_review",),
        available_tool_ids=(),
    )

    disposition = plan.binding_dispositions[0]
    assert disposition.decision == SkillDispositionDecision.ALREADY_EXISTS
    assert disposition.active_write_candidate is False
    assert plan.active_binding_candidate_refs == ()


def test_skill_disposition_blocks_missing_skill_dependency():
    plan = plan_skill_disposition(
        source_department_id="source-dept",
        target_department_id="target-dept",
        source_bindings=(_binding(),),
        target_bindings=(),
        available_skill_ids=(),
        available_tool_ids=(),
    )

    disposition = plan.binding_dispositions[0]
    assert disposition.decision == SkillDispositionDecision.MISSING_DEPENDENCY
    assert disposition.active_write_candidate is False


def test_skill_disposition_blocks_unavailable_tool_references():
    plan = plan_skill_disposition(
        source_department_id="source-dept",
        target_department_id="target-dept",
        source_bindings=(_binding(tool_assumptions=("terminal", "browser")),),
        target_bindings=(),
        available_skill_ids=("release_review",),
        available_tool_ids=("terminal",),
    )

    disposition = plan.binding_dispositions[0]
    assert disposition.decision == SkillDispositionDecision.REFERENCES_UNAVAILABLE_TOOL
    assert disposition.unavailable_tool_refs == ("browser",)
    assert disposition.active_write_candidate is False


def test_skill_disposition_only_outputs_review_candidates():
    plan = plan_skill_disposition(
        source_department_id="source-dept",
        target_department_id="target-dept",
        source_bindings=(_binding(),),
        target_bindings=(),
        available_skill_ids=("release_review",),
        available_tool_ids=(),
    )

    disposition = plan.binding_dispositions[0]
    assert disposition.decision == SkillDispositionDecision.CANDIDATE_FOR_ADOPTION
    assert disposition.active_write_candidate is True
    assert plan.active_binding_candidate_refs == (
        "departments/source-dept/skills/release-review",
    )


def test_skill_experience_requires_redaction_before_proposal():
    plan = plan_skill_disposition(
        source_department_id="source-dept",
        target_department_id="target-dept",
        experiences=(
            SkillExperienceDispositionInput(
                experience=_experience(),
                redacted=False,
                personalization_removed=True,
            ),
        ),
    )

    disposition = plan.experience_dispositions[0]
    assert disposition.decision == SkillExperienceDispositionDecision.REQUIRES_USER_REVIEW
    assert disposition.redaction_required is True
    assert disposition.proposal_input_candidate is False


def test_sanitized_skill_experience_can_only_become_proposal_input():
    plan = plan_skill_disposition(
        source_department_id="source-dept",
        target_department_id="target-dept",
        experiences=(
            SkillExperienceDispositionInput(
                experience=_experience(),
                redacted=True,
                personalization_removed=True,
            ),
        ),
    )

    disposition = plan.experience_dispositions[0]
    assert disposition.decision == SkillExperienceDispositionDecision.REDACT_AND_PROPOSE
    assert disposition.redaction_required is False
    assert disposition.personalization_removal_required is False
    assert disposition.proposal_input_candidate is True


def test_skill_disposition_contract_round_trips():
    plan = plan_skill_disposition(
        source_department_id="source-dept",
        target_department_id="target-dept",
        source_bindings=(_binding(),),
        target_bindings=(),
        available_skill_ids=("release_review",),
        experiences=(
            SkillExperienceDispositionInput(
                experience=_experience(),
                redacted=True,
                personalization_removed=True,
            ),
        ),
    )

    payload = skill_disposition_plan_to_dict(plan)

    assert skill_disposition_plan_from_dict(payload) == plan
    assert list(payload) == [
        "source_department_id",
        "target_department_id",
        "schema_version",
        "reviewer",
        "decision_status",
        "binding_dispositions",
        "experience_dispositions",
        "active_binding_candidate_refs",
    ]


def test_blocked_dispositions_cannot_be_active_write_candidates():
    with pytest.raises(OrganizationAssetDispositionError):
        plan = plan_skill_disposition(
            source_department_id="source-dept",
            target_department_id="target-dept",
            source_bindings=(_binding(),),
            target_bindings=(),
            available_skill_ids=(),
        )
        payload = skill_disposition_plan_to_dict(plan)
        payload["binding_dispositions"][0]["active_write_candidate"] = True
        skill_disposition_plan_from_dict(payload)


def test_tool_policy_deny_rule_is_conservative_candidate():
    plan = plan_tool_policy_disposition(
        source_department_id="source-dept",
        target_department_id="target-dept",
        source_policies=(
            _tool_policy(
                policy_id="deny-shell",
                tool_refs=("shell",),
                effect=DepartmentToolRuleEffect.DENY,
            ),
        ),
    )

    disposition = plan.policy_dispositions[0]
    assert disposition.item_kind == ToolPolicyDispositionItemKind.DENY_RULE
    assert disposition.decision == ToolPolicyDispositionDecision.CONSERVATIVE_CANDIDATE
    assert disposition.active_write_candidate is True
    assert plan.target_active_write_candidate_refs == (
        "departments/source-dept/policies/tools/deny-shell",
    )


def test_tool_policy_high_risk_tool_requires_user_approval():
    plan = plan_tool_policy_disposition(
        source_department_id="source-dept",
        target_department_id="target-dept",
        source_policies=(
            _tool_policy(
                policy_id="network-policy",
                tool_refs=("network",),
                risk_level=DepartmentToolRiskLevel.HIGH,
            ),
        ),
        target_allowed_tool_ids=("network",),
    )

    disposition = plan.policy_dispositions[0]
    assert disposition.item_kind == ToolPolicyDispositionItemKind.HIGH_RISK_TOOL
    assert disposition.decision == ToolPolicyDispositionDecision.USER_APPROVAL_REQUIRED
    assert disposition.user_approval_required is True
    assert disposition.active_write_candidate is False


def test_tool_policy_workspace_permission_requires_user_approval():
    plan = plan_tool_policy_disposition(
        source_department_id="source-dept",
        target_department_id="target-dept",
        source_policies=(
            _tool_policy(
                policy_id="workspace-policy",
                workspace_write_roots=("repo/src",),
            ),
        ),
        target_allowed_tool_ids=("read_file",),
    )

    disposition = plan.policy_dispositions[0]
    assert disposition.item_kind == ToolPolicyDispositionItemKind.WORKSPACE_PERMISSION
    assert disposition.decision == ToolPolicyDispositionDecision.USER_APPROVAL_REQUIRED
    assert disposition.user_approval_required is True


def test_tool_policy_external_adapter_requires_adapter_review():
    plan = plan_tool_policy_disposition(
        source_department_id="source-dept",
        target_department_id="target-dept",
        source_policies=(
            _tool_policy(
                policy_id="adapter-policy",
                tool_refs=("adapter_calendar",),
            ),
        ),
        target_allowed_tool_ids=("adapter_calendar",),
        external_adapter_tool_refs=("adapter_calendar",),
    )

    disposition = plan.policy_dispositions[0]
    assert disposition.item_kind == (
        ToolPolicyDispositionItemKind.EXTERNAL_ADAPTER_CAPABILITY
    )
    assert disposition.decision == ToolPolicyDispositionDecision.ADAPTER_REVIEW_REQUIRED
    assert disposition.adapter_review_required is True
    assert disposition.active_write_candidate is False


def test_tool_policy_disposition_contract_round_trips():
    plan = plan_tool_policy_disposition(
        source_department_id="source-dept",
        target_department_id="target-dept",
        source_policies=(
            _tool_policy(
                policy_id="approval-policy",
                effect=DepartmentToolRuleEffect.REQUIRES_APPROVAL,
            ),
        ),
        target_policies=(_tool_policy(department_id="target-dept"),),
    )

    payload = tool_policy_disposition_plan_to_dict(plan)

    assert tool_policy_disposition_plan_from_dict(payload) == plan
    assert list(payload) == [
        "source_department_id",
        "target_department_id",
        "schema_version",
        "reviewer",
        "decision_status",
        "policy_dispositions",
        "target_active_write_candidate_refs",
    ]


def test_permission_review_profile_deny_blocks_department_allow():
    tool_plan = plan_tool_policy_disposition(
        source_department_id="source-dept",
        target_department_id="target-dept",
        source_policies=(_tool_policy(tool_refs=("shell",)),),
        target_allowed_tool_ids=("shell",),
    )

    review = review_disposition_permissions(
        tool_policy_plan=tool_plan,
        target_department_policy=_target_policy(allowed_tools=("shell",)),
        worker_permission_snapshot=_worker_snapshot(allowed_tools=("read_file",)),
    )

    item = review.items[0]
    assert item.decision == PermissionDispositionDecision.BLOCKED
    assert PermissionDispositionFindingCode.PROFILE_DENIES_TOOL.value in (
        item.finding_codes
    )


def test_permission_review_blocks_high_risk_tool_without_approval():
    tool_plan = plan_tool_policy_disposition(
        source_department_id="source-dept",
        target_department_id="target-dept",
        source_policies=(
            _tool_policy(
                tool_refs=("network",),
                risk_level=DepartmentToolRiskLevel.HIGH,
            ),
        ),
        target_allowed_tool_ids=("network",),
    )

    review = review_disposition_permissions(
        tool_policy_plan=tool_plan,
        target_department_policy=_target_policy(allowed_tools=("network",)),
        worker_permission_snapshot=_worker_snapshot(allowed_tools=("network",)),
        governance_policy=GovernanceDispositionPolicy(high_risk_tools=("network",)),
    )

    item = review.items[0]
    assert item.decision == PermissionDispositionDecision.BLOCKED
    assert (
        PermissionDispositionFindingCode.HIGH_RISK_APPROVAL_MISSING.value
        in item.finding_codes
    )


def test_permission_review_budget_increase_requires_user_confirmation():
    tool_plan = plan_tool_policy_disposition(
        source_department_id="source-dept",
        target_department_id="target-dept",
        source_policies=(
            _tool_policy(
                policy_id="budget-policy",
                max_task_tokens=4000,
            ),
        ),
        target_allowed_tool_ids=("read_file",),
    )

    review = review_disposition_permissions(
        tool_policy_plan=tool_plan,
        target_department_policy=_target_policy(),
        worker_permission_snapshot=_worker_snapshot(max_task_tokens=5000),
    )

    item = review.items[0]
    assert item.decision == PermissionDispositionDecision.REQUIRES_APPROVAL
    assert "budget_model_user_approval" in item.approval_requirements
    assert (
        PermissionDispositionFindingCode.BUDGET_OR_MODEL_EXPANSION.value
        in item.finding_codes
    )


def test_permission_review_parent_deny_blocks_child_migration():
    tool_plan = plan_tool_policy_disposition(
        source_department_id="source-dept",
        target_department_id="target-dept",
        source_policies=(_tool_policy(tool_refs=("write_file",)),),
        target_allowed_tool_ids=("write_file",),
    )

    review = review_disposition_permissions(
        tool_policy_plan=tool_plan,
        target_department_policy=_target_policy(allowed_tools=("write_file",)),
        worker_permission_snapshot=_worker_snapshot(allowed_tools=("write_file",)),
        parent_policy=_target_policy(
            department_id="parent-dept",
            allowed_tools=(),
            denied_tools=("write_file",),
        ),
    )

    item = review.items[0]
    assert item.decision == PermissionDispositionDecision.BLOCKED
    assert (
        PermissionDispositionFindingCode.PARENT_POLICY_DENIES_TOOL.value
        in item.finding_codes
    )


def test_permission_review_contract_round_trips():
    skill_plan = plan_skill_disposition(
        source_department_id="source-dept",
        target_department_id="target-dept",
        source_bindings=(_binding(),),
        available_skill_ids=("release_review",),
    )
    review = review_disposition_permissions(
        skill_plan=skill_plan,
        target_department_policy=_target_policy(),
        worker_permission_snapshot=_worker_snapshot(),
    )

    payload = permission_disposition_review_to_dict(review)

    assert permission_disposition_review_from_dict(payload) == review
    assert list(payload) == [
        "target_department_id",
        "worker_id",
        "profile_snapshot_hash",
        "schema_version",
        "items",
        "approval_summary",
        "blocking_summary",
    ]

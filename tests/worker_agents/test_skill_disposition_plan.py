import pytest

from worker_agents.department_skills import (
    DepartmentSkillBindingRecord,
    DepartmentSkillBindingState,
)
from worker_agents.organization_asset_disposition import (
    OrganizationAssetDispositionError,
    SkillDispositionDecision,
    SkillExperienceDispositionDecision,
    SkillExperienceDispositionInput,
    plan_skill_disposition,
    skill_disposition_plan_from_dict,
    skill_disposition_plan_to_dict,
)
from worker_agents.private_assets import PrivateAssetSensitivity
from worker_agents.private_skill_experience import PrivateSkillExperience


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


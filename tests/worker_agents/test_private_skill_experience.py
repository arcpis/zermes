import pytest

from worker_agents.private_assets import PrivateAssetError, PrivateAssetSensitivity
from worker_agents.private_skill_experience import (
    PrivateSkillExperience,
    SkillExperienceKind,
    skill_experience_proposal_to_dict,
    skill_experience_to_dict,
    skill_experience_to_proposal_input,
    validate_skill_experience_payload,
)


def test_private_skill_experience_defaults_to_personal_note():
    experience = PrivateSkillExperience(
        worker_id="frontend",
        experience_id="skill-exp-1",
        skill_id="pytest",
        summary="Focused pytest files are enough for routing contract changes.",
        applicability="Small worker-agent changes.",
    )

    assert experience.kind == SkillExperienceKind.PERSONAL_NOTE
    assert experience.shareable is False

    with pytest.raises(PrivateAssetError, match="not eligible"):
        skill_experience_to_proposal_input(
            experience,
            proposal_input_id="skill-proposal-1",
            target_scope="department:platform",
        )


def test_shareable_skill_experience_becomes_department_proposal_input():
    experience = PrivateSkillExperience(
        worker_id="frontend",
        experience_id="skill-exp-1",
        skill_id="pytest",
        summary="Use focused pytest files for routing contract changes.",
        applicability="Worker-agent result routing and asset boundary changes.",
        limitations=("Still run broader suites before release.",),
        risk_notes=("Does not validate UI flows.",),
        tool_assumptions=("pytest is available",),
        source_refs=("tasks/task-123/summary.json",),
        sensitivity=PrivateAssetSensitivity.LOW,
        shareable=True,
    )

    proposal = skill_experience_to_proposal_input(
        experience,
        proposal_input_id="skill-proposal-1",
        target_scope="department:platform",
    )

    assert proposal.source_worker_id == "frontend"
    assert proposal.skill_id == "pytest"
    assert proposal.tool_assumptions == ("pytest is available",)
    payload = skill_experience_proposal_to_dict(proposal)
    assert "skill_source" not in payload
    assert payload["review_requirement"] == "department_skill_review"


def test_high_sensitivity_skill_experience_cannot_be_shared():
    experience = PrivateSkillExperience(
        worker_id="frontend",
        experience_id="skill-exp-1",
        skill_id="pytest",
        summary="Sensitive customer fixture guidance.",
        applicability="Private project only.",
        sensitivity=PrivateAssetSensitivity.HIGH,
        shareable=True,
    )

    with pytest.raises(PrivateAssetError, match="high-sensitivity"):
        skill_experience_to_proposal_input(
            experience,
            proposal_input_id="skill-proposal-1",
            target_scope="department:platform",
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"skill_source": "large instruction text"},
        {"full_prompt": "system prompt"},
        {"nested": {"api_key": "secret"}},
    ],
)
def test_skill_experience_payload_rejects_raw_skill_or_secret_material(payload):
    with pytest.raises(PrivateAssetError):
        validate_skill_experience_payload(payload)


@pytest.mark.parametrize("value", ["../summary.json", "/tmp/summary.json", r"C:\tmp\x"])
def test_skill_experience_rejects_unsafe_source_refs(value):
    with pytest.raises(PrivateAssetError, match="source_refs"):
        PrivateSkillExperience(
            worker_id="frontend",
            experience_id="skill-exp-1",
            skill_id="pytest",
            summary="Summary.",
            applicability="Tests.",
            source_refs=(value,),
        )


def test_skill_experience_rejects_path_like_ids():
    with pytest.raises(PrivateAssetError):
        PrivateSkillExperience(
            worker_id="frontend",
            experience_id="nested/skill-exp-1",
            skill_id="pytest",
            summary="Summary.",
            applicability="Tests.",
        )

    with pytest.raises(PrivateAssetError):
        PrivateSkillExperience(
            worker_id="frontend",
            experience_id="skill-exp-1",
            skill_id="../pytest",
            summary="Summary.",
            applicability="Tests.",
        )


def test_skill_experience_dict_keeps_personal_state_separate_from_proposal():
    experience = PrivateSkillExperience(
        worker_id="frontend",
        experience_id="skill-exp-1",
        skill_id="pytest",
        summary="Summary.",
        applicability="Tests.",
        shareable=True,
    )

    payload = skill_experience_to_dict(experience)

    assert payload["shareable"] is True
    assert payload["kind"] == SkillExperienceKind.PERSONAL_NOTE.value

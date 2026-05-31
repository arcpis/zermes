import pytest

from worker_agents.department_skills import (
    DepartmentSkillBindingProposal,
    DepartmentSkillBindingRecord,
    DepartmentSkillBindingSensitivity,
    DepartmentSkillBindingState,
    DepartmentSkillBindingVisibility,
    DepartmentSkillError,
    DepartmentSkillProposalAction,
    DepartmentSkillProposalState,
    department_skill_binding_from_dict,
    department_skill_binding_to_dict,
    department_skill_dir,
    department_skill_proposal_from_dict,
    department_skill_proposal_to_dict,
    validate_department_skill_payload,
)


def test_department_skill_binding_serializes_stable_contract():
    binding = DepartmentSkillBindingRecord(
        department_id="platform",
        binding_id="release-review",
        skill_id="release_review",
        skill_source="profile_skill_registry",
        version_constraint=">=1",
        state=DepartmentSkillBindingState.DEFAULT,
        visibility=DepartmentSkillBindingVisibility.INHERITABLE_GUIDANCE,
        sensitivity=DepartmentSkillBindingSensitivity.INTERNAL,
        usage_guidance="Use for release handoff review tasks.",
        applicability=("release_review",),
        disabled_conditions=("task touches credentials",),
        limitations=("Does not grant deploy permissions.",),
        risk_notes=("Requires separate tool policy checks.",),
        tool_assumptions=("read_file",),
        owner="platform-lead",
        source_refs=("tasks/task_123/summary.json",),
        accepted_at="2026-05-21T00:00:00Z",
        audit_summary="Accepted by department lead.",
    )

    payload = department_skill_binding_to_dict(binding)
    loaded = department_skill_binding_from_dict(payload)

    assert loaded == binding
    assert list(payload) == [
        "department_id",
        "binding_id",
        "schema_version",
        "skill_id",
        "skill_source",
        "version_constraint",
        "state",
        "visibility",
        "sensitivity",
        "usage_guidance",
        "applicability",
        "disabled_conditions",
        "limitations",
        "risk_notes",
        "tool_assumptions",
        "owner",
        "source_refs",
        "revision",
        "active",
        "accepted_at",
        "created_at",
        "updated_at",
        "audit_summary",
        "replacement_skill_id",
    ]


def test_department_skill_proposal_defaults_to_pending():
    proposal = DepartmentSkillBindingProposal(
        proposal_id="proposal-1",
        department_id="platform",
        proposed_action=DepartmentSkillProposalAction.ADD_BINDING,
        skill_id="release_review",
        candidate_guidance="Use for release handoff review tasks.",
        source_actor="frontend",
    )

    assert proposal.state == DepartmentSkillProposalState.PENDING
    assert proposal.sensitivity == DepartmentSkillBindingSensitivity.INTERNAL
    payload = department_skill_proposal_to_dict(proposal)
    assert department_skill_proposal_from_dict(payload) == proposal


@pytest.mark.parametrize(
    "payload",
    [
        {"skill_source_code": "def run(): ..."},
        {"nested": {"raw_skill_instruction": "full prompt"}},
        {"items": [{"external_raw_output": "adapter log"}]},
        {"private_experience_text": "worker-only experience"},
    ],
)
def test_department_skill_payload_rejects_sensitive_fields(payload):
    with pytest.raises(DepartmentSkillError):
        validate_department_skill_payload(payload)


@pytest.mark.parametrize("value", ["../task.json", "/tmp/task.json", r"C:\tmp\task.json"])
def test_department_skill_rejects_unsafe_source_refs(value):
    with pytest.raises(DepartmentSkillError, match="source_refs"):
        DepartmentSkillBindingRecord(
            department_id="platform",
            binding_id="binding-1",
            skill_id="release_review",
            skill_source="profile_skill_registry",
            usage_guidance="Use summary only.",
            source_refs=(value,),
        )


def test_department_skill_rejects_path_like_ids():
    with pytest.raises(ValueError):
        DepartmentSkillBindingRecord(
            department_id="team/platform",
            binding_id="binding-1",
            skill_id="release_review",
            skill_source="profile_skill_registry",
            usage_guidance="Use summary only.",
        )

    with pytest.raises(DepartmentSkillError):
        DepartmentSkillBindingProposal(
            proposal_id="../proposal-1",
            department_id="platform",
            proposed_action=DepartmentSkillProposalAction.ADD_BINDING,
            skill_id="release_review",
            candidate_guidance="Use summary only.",
            source_actor="main_agent",
        )


def test_department_skill_path_stays_in_department_skill_area():
    path = department_skill_dir("/profile/worker_agents", "platform")

    assert path.parts[-4:] == ("organization", "departments", "platform", "skills")
    assert "workers" not in path.parts

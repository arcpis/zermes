import pytest

from worker_agents.department_skills import (
    DepartmentSkillBindingProposal,
    DepartmentSkillBindingState,
    DepartmentSkillBindingStore,
    DepartmentSkillBindingVisibility,
    DepartmentSkillError,
    DepartmentSkillProposalAction,
    DepartmentSkillProposalCreateStatus,
    DepartmentSkillProposalState,
    DepartmentSkillReviewAction,
    DepartmentSkillReviewDecision,
    DepartmentSkillReviewService,
    DepartmentSkillReviewerRole,
    proposal_from_skill_experience_input,
)
from worker_agents.private_skill_experience import SkillExperienceProposalInput


def _proposal(**overrides):
    values = {
        "proposal_id": "proposal-1",
        "department_id": "platform",
        "proposed_action": DepartmentSkillProposalAction.ADD_BINDING,
        "skill_id": "release_review",
        "candidate_guidance": "Use for release handoff review tasks.",
        "source_actor": "frontend",
        "source_hash": "sha256:abc",
        "created_at": "2026-05-21T00:00:00Z",
    }
    values.update(overrides)
    return DepartmentSkillBindingProposal(**values)


def test_store_creates_and_loads_pending_skill_proposal(tmp_path):
    store = DepartmentSkillBindingStore(root=tmp_path)
    proposal = _proposal()

    result = store.create_proposal(proposal)
    loaded = store.load_proposal("platform", "proposal-1")

    assert result.status == DepartmentSkillProposalCreateStatus.CREATED
    assert loaded == proposal
    assert store.proposal_path("platform", "proposal-1").parts[-3:] == (
        "skills",
        "proposals",
        "proposal-1.json",
    )


def test_store_returns_existing_pending_duplicate_by_skill_and_source_hash(tmp_path):
    store = DepartmentSkillBindingStore(root=tmp_path)
    first = _proposal()
    duplicate = _proposal(
        proposal_id="proposal-2",
        candidate_guidance="Use again.",
        source_hash="sha256:abc",
    )

    store.create_proposal(first)
    result = store.create_proposal(duplicate)

    assert result.status == DepartmentSkillProposalCreateStatus.EXISTING
    assert result.proposal == first
    assert store.list_proposals("platform") == [first]


def test_store_rejects_non_pending_creation(tmp_path):
    store = DepartmentSkillBindingStore(root=tmp_path)
    proposal = _proposal(state=DepartmentSkillProposalState.REJECTED)

    with pytest.raises(DepartmentSkillError, match="must be pending"):
        store.create_proposal(proposal)


def test_skill_experience_input_becomes_department_skill_proposal_without_raw_text():
    proposal_input = SkillExperienceProposalInput(
        proposal_input_id="input-1",
        source_worker_id="frontend",
        source_experience_id="exp-1",
        skill_id="release_review",
        target_scope="department:platform",
        summary="Use for release handoff review tasks.",
        applicability="release handoff",
        limitations=("Does not grant deploy permissions.",),
        risk_notes=("Requires tool policy checks.",),
        tool_assumptions=("read_file",),
        source_refs=("tasks/task_123/summary.json",),
    )

    proposal = proposal_from_skill_experience_input(
        proposal_input,
        proposal_id="proposal-1",
        department_id="platform",
    )

    assert proposal.skill_id == "release_review"
    assert proposal.candidate_guidance == proposal_input.summary
    assert proposal.source_actor == "frontend"
    assert proposal.source_hash == "frontend:exp-1"
    assert "private_experience_text" not in proposal.candidate_guidance


def test_approve_pending_skill_proposal_creates_active_binding(tmp_path):
    store = DepartmentSkillBindingStore(root=tmp_path)
    proposal = _proposal(
        candidate_state=DepartmentSkillBindingState.DEFAULT,
        visibility=DepartmentSkillBindingVisibility.INHERITABLE_GUIDANCE,
        tool_assumptions=("read_file",),
    )
    store.create_proposal(proposal)
    service = DepartmentSkillReviewService(store)

    binding = service.approve(
        "platform",
        "proposal-1",
        DepartmentSkillReviewAction(
            proposal_id="proposal-1",
            decision=DepartmentSkillReviewDecision.APPROVE,
            actor_id="lead-worker",
            actor_role=DepartmentSkillReviewerRole.DEPARTMENT_LEAD,
            reason="Useful department default.",
            reviewed_at="2026-05-21T01:00:00Z",
        ),
    )

    updated = store.load_proposal("platform", "proposal-1")
    assert binding.binding_id == proposal.proposal_id
    assert binding.state == DepartmentSkillBindingState.DEFAULT
    assert binding.tool_assumptions == ("read_file",)
    assert updated.state == DepartmentSkillProposalState.APPROVED
    assert store.binding_path("platform", "proposal-1").exists()


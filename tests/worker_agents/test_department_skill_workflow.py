from worker_agents.department_skills import (
    DepartmentSkillApplicabilityDecision,
    DepartmentSkillApplicabilityRequest,
    DepartmentSkillBindingState,
    DepartmentSkillBindingStore,
    DepartmentSkillGuardrailDecision,
    DepartmentSkillProposalAction,
    DepartmentSkillReviewAction,
    DepartmentSkillReviewDecision,
    DepartmentSkillReviewService,
    DepartmentSkillReviewerRole,
    guard_department_skill_usage,
    proposal_from_skill_experience_input,
    resolve_department_skill_bindings,
    validate_department_skill_applicability,
)
from worker_agents.private_skill_experience import SkillExperienceProposalInput


def test_skill_experience_can_be_reviewed_and_exposed_as_safe_candidate(tmp_path):
    store = DepartmentSkillBindingStore(root=tmp_path)
    proposal_input = SkillExperienceProposalInput(
        proposal_input_id="input-1",
        source_worker_id="frontend",
        source_experience_id="exp-1",
        skill_id="release_review",
        target_scope="department:platform",
        summary="Use for release handoff review tasks.",
        applicability="release_review",
        limitations=("Does not grant deploy permissions.",),
        risk_notes=("Requires separate tool policy checks.",),
        tool_assumptions=("read_file",),
        source_refs=("tasks/task_123/summary.json",),
    )
    proposal = proposal_from_skill_experience_input(
        proposal_input,
        proposal_id="proposal-1",
        department_id="platform",
        proposed_action=DepartmentSkillProposalAction.ADD_BINDING,
        candidate_state=DepartmentSkillBindingState.DEFAULT,
    )

    store.create_proposal(proposal)
    binding = DepartmentSkillReviewService(store).approve(
        "platform",
        "proposal-1",
        DepartmentSkillReviewAction(
            proposal_id="proposal-1",
            decision=DepartmentSkillReviewDecision.APPROVE,
            actor_id="lead-worker",
            actor_role=DepartmentSkillReviewerRole.DEPARTMENT_LEAD,
            reason="Useful release review default.",
            reviewed_at="2026-05-21T01:00:00Z",
        ),
    )
    resolved = resolve_department_skill_bindings(store, "platform")
    applicability = validate_department_skill_applicability(
        resolved[0],
        DepartmentSkillApplicabilityRequest(
            task_type="release_review",
            worker_id="frontend",
            worker_role="engineer",
            department_id="platform",
            runtime_type="internal_worker",
            allowed_skill_ids=("release_review",),
            permission_names=("read_file",),
        ),
    )
    guardrail = guard_department_skill_usage(
        binding,
        applicability,
        runtime_type="internal_worker",
    )

    assert applicability.decision == DepartmentSkillApplicabilityDecision.ALLOWED
    assert guardrail.decision == DepartmentSkillGuardrailDecision.ALLOWED_CANDIDATE
    assert guardrail.safe_candidate is not None
    assert guardrail.safe_candidate.guidance_summary == proposal_input.summary
    assert "private_experience_text" not in guardrail.safe_candidate.guidance_summary

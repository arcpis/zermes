from worker_agents import (
    DEPARTMENT_SKILL_SCHEMA_VERSION,
    DepartmentSkillApplicabilityDecision,
    DepartmentSkillApplicabilityRequest,
    DepartmentSkillBindingProposal,
    DepartmentSkillBindingRecord,
    DepartmentSkillBindingState,
    DepartmentSkillBindingStore,
    DepartmentSkillGuardrailDecision,
    DepartmentSkillGuardrailReason,
    DepartmentSkillProposalAction,
    DepartmentSkillReviewAction,
    DepartmentSkillReviewDecision,
    DepartmentSkillReviewService,
    DepartmentSkillReviewerRole,
    department_skill_binding_to_dict,
    guard_department_skill_usage,
    proposal_from_skill_experience_input,
    resolve_department_skill_bindings,
    validate_department_skill_applicability,
)


def test_department_skill_exports_are_available_from_package():
    assert DEPARTMENT_SKILL_SCHEMA_VERSION == 1
    assert DepartmentSkillBindingState.DEFAULT.value == "default"
    assert DepartmentSkillProposalAction.ADD_BINDING.value == "add_binding"
    assert DepartmentSkillApplicabilityDecision.BLOCKED.value == "blocked"
    assert DepartmentSkillGuardrailDecision.ALLOWED_CANDIDATE.value == (
        "allowed_candidate"
    )
    assert DepartmentSkillGuardrailReason.MISSING_PERMISSION.value == (
        "missing_permission"
    )
    assert DepartmentSkillBindingRecord.__name__ == "DepartmentSkillBindingRecord"
    assert DepartmentSkillBindingProposal.__name__ == "DepartmentSkillBindingProposal"
    assert DepartmentSkillBindingStore.__name__ == "DepartmentSkillBindingStore"
    assert DepartmentSkillReviewAction.__name__ == "DepartmentSkillReviewAction"
    assert DepartmentSkillReviewDecision.APPROVE.value == "approve"
    assert DepartmentSkillReviewerRole.MAIN_AGENT.value == "main_agent"
    assert DepartmentSkillReviewService.__name__ == "DepartmentSkillReviewService"
    assert DepartmentSkillApplicabilityRequest.__name__ == (
        "DepartmentSkillApplicabilityRequest"
    )
    assert department_skill_binding_to_dict.__name__ == (
        "department_skill_binding_to_dict"
    )
    assert proposal_from_skill_experience_input.__name__ == (
        "proposal_from_skill_experience_input"
    )
    assert resolve_department_skill_bindings.__name__ == (
        "resolve_department_skill_bindings"
    )
    assert validate_department_skill_applicability.__name__ == (
        "validate_department_skill_applicability"
    )
    assert guard_department_skill_usage.__name__ == "guard_department_skill_usage"

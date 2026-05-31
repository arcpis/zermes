from worker_agents.department_skills import (
    DepartmentSkillApplicabilityDecision,
    DepartmentSkillApplicabilityRequest,
    DepartmentSkillBindingRecord,
    DepartmentSkillBindingSensitivity,
    DepartmentSkillBindingState,
    DepartmentSkillResolvedBinding,
    validate_department_skill_applicability,
)


def _binding(**overrides):
    values = {
        "department_id": "platform",
        "binding_id": "release-review",
        "skill_id": "release_review",
        "skill_source": "profile_skill_registry",
        "usage_guidance": "Use for release handoff review tasks.",
        "state": DepartmentSkillBindingState.DEFAULT,
        "applicability": ("release_review",),
        "tool_assumptions": ("read_file",),
    }
    values.update(overrides)
    return DepartmentSkillBindingRecord(**values)


def _request(**overrides):
    values = {
        "task_type": "release_review",
        "worker_id": "frontend",
        "worker_role": "engineer",
        "department_id": "platform",
        "runtime_type": "internal_worker",
        "allowed_skill_ids": ("release_review",),
        "permission_names": ("read_file",),
    }
    values.update(overrides)
    return DepartmentSkillApplicabilityRequest(**values)


def test_default_skill_with_profile_and_permission_is_allowed():
    result = validate_department_skill_applicability(_binding(), _request())

    assert result.decision == DepartmentSkillApplicabilityDecision.ALLOWED
    assert result.reasons == ()
    assert result.safe_guidance_summary == "Use for release handoff review tasks."


def test_recommended_skill_is_candidate_only_when_allowed():
    result = validate_department_skill_applicability(
        _binding(state=DepartmentSkillBindingState.RECOMMENDED),
        _request(),
    )

    assert result.decision == DepartmentSkillApplicabilityDecision.CANDIDATE_ONLY


def test_default_skill_is_blocked_when_worker_profile_disallows_it():
    result = validate_department_skill_applicability(
        _binding(),
        _request(allowed_skill_ids=()),
    )

    assert result.decision == DepartmentSkillApplicabilityDecision.BLOCKED
    assert "profile_disallows_skill" in result.reasons
    assert result.safe_guidance_summary == ""


def test_missing_tool_permission_blocks_skill_guidance():
    result = validate_department_skill_applicability(
        _binding(tool_assumptions=("read_file", "shell")),
        _request(permission_names=("read_file",)),
    )

    assert result.decision == DepartmentSkillApplicabilityDecision.BLOCKED
    assert "missing_permission" in result.reasons


def test_wrong_department_role_and_task_type_return_stable_reasons():
    result = validate_department_skill_applicability(
        _binding(disabled_conditions=("designer",)),
        _request(
            department_id="design",
            worker_role="designer",
            task_type="visual_review",
        ),
    )

    assert result.decision == DepartmentSkillApplicabilityDecision.BLOCKED
    assert result.reasons == (
        "wrong_department",
        "unsupported_task_type",
        "wrong_worker_role",
    )


def test_inherited_binding_can_match_child_department():
    inherited = DepartmentSkillResolvedBinding(
        binding=_binding(department_id="parent"),
        inherited=True,
        source_department_id="parent",
    )

    result = validate_department_skill_applicability(
        inherited,
        _request(department_id="child"),
    )

    assert "wrong_department" not in result.reasons
    assert result.decision == DepartmentSkillApplicabilityDecision.ALLOWED


def test_restricted_binding_needs_review_without_blocking_permission():
    result = validate_department_skill_applicability(
        _binding(state=DepartmentSkillBindingState.RESTRICTED),
        _request(),
    )

    assert result.decision == DepartmentSkillApplicabilityDecision.NEEDS_REVIEW
    assert result.reasons == ("restricted_binding",)


def test_user_confirmation_required_binding_needs_review_until_confirmed():
    result = validate_department_skill_applicability(
        _binding(
            sensitivity=DepartmentSkillBindingSensitivity.USER_CONFIRMATION_REQUIRED,
        ),
        _request(
            sensitivity=DepartmentSkillBindingSensitivity.USER_CONFIRMATION_REQUIRED,
        ),
    )
    confirmed = validate_department_skill_applicability(
        _binding(
            sensitivity=DepartmentSkillBindingSensitivity.USER_CONFIRMATION_REQUIRED,
        ),
        _request(
            sensitivity=DepartmentSkillBindingSensitivity.USER_CONFIRMATION_REQUIRED,
            confirmation_refs=("approvals/user-confirmation-1.json",),
        ),
    )

    assert result.decision == DepartmentSkillApplicabilityDecision.NEEDS_REVIEW
    assert result.reasons == ("user_confirmation_required",)
    assert confirmed.decision == DepartmentSkillApplicabilityDecision.ALLOWED
    assert confirmed.required_review_refs == ("approvals/user-confirmation-1.json",)


def test_sensitive_task_blocks_when_request_allows_lower_sensitivity():
    result = validate_department_skill_applicability(
        _binding(sensitivity=DepartmentSkillBindingSensitivity.RESTRICTED),
        _request(sensitivity=DepartmentSkillBindingSensitivity.INTERNAL),
    )

    assert result.decision == DepartmentSkillApplicabilityDecision.BLOCKED
    assert "sensitive_task_blocked" in result.reasons

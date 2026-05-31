from worker_agents.department_skills import (
    DepartmentSkillApplicabilityRequest,
    DepartmentSkillBindingRecord,
    DepartmentSkillBindingSensitivity,
    DepartmentSkillBindingState,
    DepartmentSkillGuardrailDecision,
    department_skill_guardrail_result_to_dict,
    guard_department_skill_usage,
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
        "limitations": ("Does not grant deploy permissions.",),
        "risk_notes": ("Requires separate tool policy checks.",),
        "source_refs": ("tasks/task_123/summary.json",),
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


def _guard(binding, request=None, runtime_type="internal_worker"):
    request = request or _request()
    applicability = validate_department_skill_applicability(binding, request)
    return guard_department_skill_usage(
        binding,
        applicability,
        runtime_type=runtime_type,
    )


def test_allowed_applicability_becomes_safe_candidate_view():
    result = _guard(_binding())

    assert result.decision == DepartmentSkillGuardrailDecision.ALLOWED_CANDIDATE
    assert result.safe_candidate is not None
    assert result.safe_candidate.guidance_summary == (
        "Use for release handoff review tasks."
    )
    payload = department_skill_guardrail_result_to_dict(result)
    assert set(payload["safe_candidate"]) == {
        "skill_id",
        "binding_id",
        "title",
        "guidance_summary",
        "constraints",
        "audit_refs",
        "replacement_skill_id",
    }


def test_missing_permission_blocks_without_safe_candidate():
    result = _guard(_binding(), _request(permission_names=()))

    assert result.decision == DepartmentSkillGuardrailDecision.BLOCKED
    assert "missing_permission" in result.reasons
    assert result.safe_candidate is None


def test_restricted_binding_requires_owner_review():
    result = _guard(_binding(state=DepartmentSkillBindingState.RESTRICTED))

    assert result.decision == DepartmentSkillGuardrailDecision.NEEDS_OWNER_REVIEW
    assert result.review_requirement == "department_owner_review"
    assert result.safe_candidate is not None


def test_user_confirmation_required_binding_keeps_candidate_pending_confirmation():
    result = _guard(
        _binding(sensitivity=DepartmentSkillBindingSensitivity.USER_CONFIRMATION_REQUIRED),
        _request(
            sensitivity=DepartmentSkillBindingSensitivity.USER_CONFIRMATION_REQUIRED,
        ),
    )

    assert result.decision == DepartmentSkillGuardrailDecision.NEEDS_USER_CONFIRMATION
    assert result.review_requirement == "user_confirmation"
    assert result.safe_candidate is not None


def test_deprecated_binding_returns_replacement_warning_only():
    result = _guard(
        _binding(
            state=DepartmentSkillBindingState.DEPRECATED,
            replacement_skill_id="new_release_review",
        )
    )

    assert result.decision == DepartmentSkillGuardrailDecision.WARNING_ONLY
    assert "deprecated_binding" in result.reasons
    assert result.safe_candidate is not None
    assert result.safe_candidate.guidance_summary == (
        "Deprecated department skill binding withheld."
    )
    assert result.safe_candidate.replacement_skill_id == "new_release_review"


def test_external_runtime_gets_summary_only_reason():
    result = _guard(_binding(), runtime_type="external_adapter")

    assert result.decision == DepartmentSkillGuardrailDecision.ALLOWED_CANDIDATE
    assert "external_runtime_summary_only" in result.reasons
    assert result.safe_candidate is not None
    assert "skill_source_code" not in department_skill_guardrail_result_to_dict(result)

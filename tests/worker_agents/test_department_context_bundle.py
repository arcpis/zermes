import pytest

from worker_agents.department_context_bundle import (
    DepartmentAssetContextBundle,
    DepartmentContextBundleError,
    DepartmentContextExcludedAsset,
    DepartmentContextLimitSummary,
    DepartmentContextSelectionReason,
    DepartmentContextSensitivitySummary,
    DepartmentMemoryContextView,
    DepartmentSkillGuidanceContextView,
    DepartmentToolPolicyContextSnapshot,
    department_context_bundle_from_dict,
    department_context_bundle_to_dict,
    validate_context_bundle_payload,
)


def _bundle() -> DepartmentAssetContextBundle:
    memory = DepartmentMemoryContextView(
        department_id="engineering",
        memory_id="delivery-standard",
        kind="delivery_standard",
        summary="Prefer small reviewed changes for release tasks.",
        tags=("release",),
        source_refs=("departments/engineering/memory/delivery-standard.json",),
        freshness="2026-05-20",
        sensitivity="low",
    )
    skill = DepartmentSkillGuidanceContextView(
        department_id="engineering",
        binding_id="pytest-guidance",
        skill_id="pytest",
        display_title="Pytest",
        guidance_summary="Use focused tests before broader regression runs.",
        constraints=("summary_only",),
        guardrail_refs=("departments/engineering/skills/pytest/guardrails.json",),
        audit_refs=("audits/skill-guidance/pytest.json",),
        source_refs=("departments/engineering/skills/pytest.json",),
        sensitivity="low",
    )
    policy = DepartmentToolPolicyContextSnapshot(
        department_id="engineering",
        allowed_tool_summaries=("pytest read-only checks",),
        denied_tool_summaries=("production deploy tools",),
        approval_required_tool_summaries=("write commands require approval",),
        denial_reasons=("production deploy is outside task scope",),
        approval_status_refs=("approvals/write-tools/pending.json",),
        policy_refs=("departments/engineering/tool-policy.json",),
        audit_refs=("audits/tool-policy/engineering.json",),
    )
    return DepartmentAssetContextBundle(
        department_id="engineering",
        worker_id="release_worker",
        task_ref="tasks/release-check",
        selected_memories=(memory,),
        selected_skill_guidance=(skill,),
        selected_tool_policy_snapshot=policy,
        selection_reasons=(
            DepartmentContextSelectionReason(
                asset_kind="memory",
                asset_id="delivery-standard",
                reasons=("department_match", "task_type_match"),
                source_refs=memory.source_refs,
            ),
            DepartmentContextSelectionReason(
                asset_kind="skill_guidance",
                asset_id="pytest-guidance",
                reasons=("worker_role_match",),
                source_refs=skill.source_refs,
            ),
        ),
        excluded_assets=(
            DepartmentContextExcludedAsset(
                asset_kind="memory",
                asset_id="too-sensitive",
                reason="sensitivity_ceiling_exceeded",
                sensitivity="restricted",
                source_refs=("departments/engineering/memory/too-sensitive.json",),
            ),
        ),
        sensitivity_summary=DepartmentContextSensitivitySummary(
            highest_included_sensitivity="low",
            included_sensitivities=("low",),
            excluded_sensitive_count=1,
        ),
        limit_summary=DepartmentContextLimitSummary(
            memory_items=1,
            skill_items=1,
            total_items=3,
            max_memory_items=2,
            max_skill_items=2,
            max_total_items=4,
            max_total_summary_chars=500,
        ),
        audit_summary="Selected safe department context for release task.",
        created_at="2026-05-23T00:00:00Z",
    )


def test_context_bundle_round_trips_stable_payload():
    payload = department_context_bundle_to_dict(_bundle())

    loaded = department_context_bundle_from_dict(payload)

    assert department_context_bundle_to_dict(loaded) == payload


@pytest.mark.parametrize(
    "field_name",
    [
        "secret",
        "credential",
        "token",
        "cookie",
        "env",
        "raw_transcript",
        "full_transcript",
        "private_memory_text",
        "private_experience_text",
        "unaccepted_proposal_body",
        "raw_stdout",
        "raw_stderr",
        "external_raw_output",
        "tool_call_history",
    ],
)
def test_context_bundle_payload_rejects_sensitive_field_names(field_name):
    with pytest.raises(DepartmentContextBundleError):
        validate_context_bundle_payload({"safe": {field_name: "blocked"}})


def test_context_views_reject_unaccepted_or_path_like_references():
    with pytest.raises(DepartmentContextBundleError, match="accepted"):
        DepartmentMemoryContextView(
            department_id="engineering",
            memory_id="proposal",
            kind="risk",
            summary="A pending proposal summary.",
            source_refs=("departments/engineering/memory/proposal.json",),
            accepted_state="pending",
        )

    with pytest.raises(DepartmentContextBundleError, match="single path segment"):
        DepartmentSkillGuidanceContextView(
            department_id="engineering",
            binding_id="../pytest",
            skill_id="pytest",
            display_title="Pytest",
            guidance_summary="Use focused tests.",
            source_refs=("departments/engineering/skills/pytest.json",),
        )


def test_selected_assets_require_source_refs_and_selection_reasons():
    memory = DepartmentMemoryContextView(
        department_id="engineering",
        memory_id="delivery-standard",
        kind="delivery_standard",
        summary="Prefer small reviewed changes.",
        source_refs=("departments/engineering/memory/delivery-standard.json",),
    )

    with pytest.raises(DepartmentContextBundleError, match="selection_reasons"):
        DepartmentAssetContextBundle(
            department_id="engineering",
            worker_id="release_worker",
            task_ref="tasks/release-check",
            selected_memories=(memory,),
            created_at="2026-05-23T00:00:00Z",
        )

    with pytest.raises(DepartmentContextBundleError, match="source_refs"):
        DepartmentMemoryContextView(
            department_id="engineering",
            memory_id="no-source",
            kind="risk",
            summary="Missing source refs.",
        )

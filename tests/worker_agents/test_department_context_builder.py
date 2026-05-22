from worker_agents.department_context_builder import (
    DepartmentContextBuildInput,
    DepartmentContextInjectionLimits,
    build_department_context_bundle,
)
from worker_agents.department_context_bundle import (
    DepartmentToolPolicyContextSnapshot,
    department_context_bundle_to_dict,
)
from worker_agents.department_context_selection import (
    DepartmentContextCandidate,
    DepartmentContextSelectionInput,
    select_department_context_assets,
)


def _candidate(
    asset_id: str,
    *,
    asset_kind: str = "memory",
    summary: str = "Use focused release tests before broad checks.",
    department_id: str = "engineering",
    sensitivity: str = "low",
) -> DepartmentContextCandidate:
    return DepartmentContextCandidate(
        asset_kind=asset_kind,
        asset_id=asset_id,
        department_id=department_id,
        summary=summary,
        source_refs=(f"departments/{department_id}/assets/{asset_id}.json",),
        task_types=("release",),
        worker_roles=("developer",),
        freshness="fresh",
        sensitivity=sensitivity,
        title=asset_id.replace("-", " ").title(),
        constraints=("summary_only",),
        guardrail_refs=(f"departments/{department_id}/guardrails/{asset_id}.json",),
        audit_refs=(f"audits/{asset_id}.json",),
    )


def _selection(candidates):
    return select_department_context_assets(
        DepartmentContextSelectionInput(
            task_ref="tasks/release-check",
            task_type="release",
            target_department_id="engineering",
            department_ancestry=("platform",),
            worker_id="release_worker",
            worker_role="developer",
            asset_candidates=tuple(candidates),
            sensitivity_ceiling="restricted",
            max_memories=5,
            max_skill_guidance=5,
            max_total_items=5,
            max_summary_chars=1000,
        )
    )


def _build(selection_result, limits, *, tool_policy=None):
    return build_department_context_bundle(
        DepartmentContextBuildInput(
            task_ref="tasks/release-check",
            target_department_id="engineering",
            worker_id="release_worker",
            selection_result=selection_result,
            effective_tool_policy_snapshot=tool_policy,
            limits=limits,
            department_ancestry=("platform",),
            audit_trace_ref="traces/release-check/context.json",
            created_at="2026-05-23T00:00:00Z",
        )
    )


def test_builder_excludes_candidates_beyond_max_items():
    result = _selection(
        (
            _candidate("first"),
            _candidate("second"),
            _candidate("skill", asset_kind="skill_guidance"),
        )
    )

    bundle = _build(
        result,
        DepartmentContextInjectionLimits(max_memory_items=1, max_total_items=2),
    )

    assert [item.memory_id for item in bundle.selected_memories] == ["first"]
    assert {item.reason for item in bundle.excluded_assets} >= {"limit_reached"}


def test_builder_truncates_long_summaries_and_keeps_serialization_valid():
    result = _selection((_candidate("long", summary="x" * 80),))

    bundle = _build(
        result,
        DepartmentContextInjectionLimits(max_summary_chars_per_item=20),
    )

    assert bundle.selected_memories[0].summary.endswith("...")
    assert len(bundle.selected_memories[0].summary) <= 20
    assert "summary_truncated" in bundle.limit_summary.reasons
    assert department_context_bundle_to_dict(bundle)["selected_memories"][0]["summary"]


def test_builder_rejects_selected_candidate_above_sensitivity_ceiling():
    result = _selection((_candidate("restricted", sensitivity="restricted"),))

    bundle = _build(
        result,
        DepartmentContextInjectionLimits(sensitivity_ceiling="internal"),
    )

    assert bundle.selected_memories == ()
    assert bundle.audit_summary == "all_candidates_excluded"
    assert bundle.excluded_assets[0].reason == "sensitivity_ceiling_exceeded"


def test_builder_injects_pending_high_risk_tool_policy_as_summary_only():
    result = _selection((_candidate("release-memory"),))
    tool_policy = DepartmentToolPolicyContextSnapshot(
        department_id="engineering",
        allowed_tool_summaries=("read-only test execution",),
        approval_required_tool_summaries=("write shell commands pending approval",),
        denied_tool_summaries=("production deploy commands denied",),
        approval_status_refs=("approvals/write-shell/pending.json",),
        policy_refs=("departments/engineering/tool-policy.json",),
    )

    bundle = _build(result, DepartmentContextInjectionLimits(), tool_policy=tool_policy)
    payload = department_context_bundle_to_dict(bundle)

    assert payload["selected_tool_policy_snapshot"]["approval_required_tool_summaries"]
    assert "write shell commands pending approval" not in payload[
        "selected_tool_policy_snapshot"
    ]["allowed_tool_summaries"]


def test_empty_bundle_serializes_with_no_relevant_assets_audit():
    result = _selection(())

    bundle = _build(result, DepartmentContextInjectionLimits())

    assert bundle.selected_memories == ()
    assert bundle.selected_skill_guidance == ()
    assert bundle.audit_summary == "no_relevant_safe_assets"
    assert department_context_bundle_to_dict(bundle)["selected_memories"] == []


def test_builder_payload_whitelist_excludes_raw_sensitive_fields():
    result = _selection(
        (
            _candidate("memory"),
            _candidate("skill", asset_kind="skill_guidance"),
        )
    )

    payload = department_context_bundle_to_dict(
        _build(result, DepartmentContextInjectionLimits())
    )
    payload_text = str(payload)

    for blocked in (
        "secret",
        "credential",
        "token",
        "raw_stdout",
        "raw_stderr",
        "full_transcript",
        "private_memory_text",
    ):
        assert blocked not in payload_text

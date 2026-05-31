"""Build minimal department context bundles from selected safe candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .department_context_bundle import (
    DepartmentAssetContextBundle,
    DepartmentContextExcludedAsset,
    DepartmentContextLimitSummary,
    DepartmentContextSensitivitySummary,
    DepartmentMemoryContextView,
    DepartmentSkillGuidanceContextView,
    DepartmentToolPolicyContextSnapshot,
    department_context_bundle_to_dict,
    validate_context_bundle_payload,
)
from .department_context_selection import (
    DepartmentContextCandidate,
    DepartmentContextSelectionResult,
)
from .organization import validate_org_node_id
from .profile import validate_worker_id


class DepartmentContextBuilderError(ValueError):
    """Raised when a minimal context bundle cannot be built safely."""


_SENSITIVITY_RANK = {
    "none": -1,
    "low": 0,
    "internal": 1,
    "restricted": 2,
    "user_confirmation_required": 3,
}


@dataclass(frozen=True)
class DepartmentContextInjectionLimits:
    """Hard limits applied after relevance selection and before runtime injection."""

    max_memory_items: int = 3
    max_skill_items: int = 2
    max_total_items: int = 5
    max_summary_chars_per_item: int = 500
    max_total_summary_chars: int = 2000
    max_inheritance_depth: int = 1
    sensitivity_ceiling: str = "internal"
    allowed_asset_kinds: tuple[str, ...] = ("memory", "skill_guidance")

    def __post_init__(self) -> None:
        for field_name in (
            "max_memory_items",
            "max_skill_items",
            "max_total_items",
            "max_summary_chars_per_item",
            "max_total_summary_chars",
            "max_inheritance_depth",
        ):
            _non_negative_int(getattr(self, field_name), field_name)
        _require_known_sensitivity(self.sensitivity_ceiling)
        _coerce_string_tuple(self, "allowed_asset_kinds")


@dataclass(frozen=True)
class DepartmentContextBuildInput:
    """Inputs needed to turn selection results into a runtime-safe bundle."""

    task_ref: str
    target_department_id: str
    worker_id: str
    selection_result: DepartmentContextSelectionResult
    limits: DepartmentContextInjectionLimits
    created_at: str
    department_ancestry: tuple[str, ...] = ()
    effective_tool_policy_snapshot: DepartmentToolPolicyContextSnapshot | None = None
    audit_trace_ref: str = ""

    def __post_init__(self) -> None:
        _require_string(self.task_ref, "task_ref")
        validate_org_node_id(self.target_department_id)
        validate_worker_id(self.worker_id)
        if not isinstance(self.selection_result, DepartmentContextSelectionResult):
            raise DepartmentContextBuilderError(
                "selection_result must be a DepartmentContextSelectionResult"
            )
        if not isinstance(self.limits, DepartmentContextInjectionLimits):
            raise DepartmentContextBuilderError(
                "limits must be a DepartmentContextInjectionLimits"
            )
        _require_string(self.created_at, "created_at")
        object.__setattr__(
            self,
            "department_ancestry",
            tuple(validate_org_node_id(value) for value in self.department_ancestry),
        )
        if self.effective_tool_policy_snapshot is not None and not isinstance(
            self.effective_tool_policy_snapshot, DepartmentToolPolicyContextSnapshot
        ):
            raise DepartmentContextBuilderError(
                "effective_tool_policy_snapshot must be a DepartmentToolPolicyContextSnapshot"
            )
        _string_value(self.audit_trace_ref, "audit_trace_ref")


def build_department_context_bundle(
    build_input: DepartmentContextBuildInput,
) -> DepartmentAssetContextBundle:
    """Build a field-limited bundle and validate it before returning."""

    if not isinstance(build_input, DepartmentContextBuildInput):
        raise DepartmentContextBuilderError(
            "build_input must be a DepartmentContextBuildInput"
        )

    memories: list[DepartmentMemoryContextView] = []
    skills: list[DepartmentSkillGuidanceContextView] = []
    excluded: list[DepartmentContextExcludedAsset] = list(
        build_input.selection_result.excluded_candidates
    )
    total_summary_chars = 0
    limit_reasons: list[str] = list(build_input.selection_result.limit_summary.reasons)

    for candidate in build_input.selection_result.selected_candidates:
        if len(memories) + len(skills) >= build_input.limits.max_total_items:
            excluded.append(_excluded(candidate, "limit_reached"))
            _append_unique(limit_reasons, "limit_reached")
            continue
        reason = _builder_exclusion_reason(candidate, build_input)
        if reason is not None:
            excluded.append(_excluded(candidate, reason))
            if reason in {"limit_reached", "token_budget_pressure"}:
                _append_unique(limit_reasons, reason)
            continue

        clipped_summary = _clip(
            candidate.summary, build_input.limits.max_summary_chars_per_item
        )
        if clipped_summary != candidate.summary:
            _append_unique(limit_reasons, "summary_truncated")
        if total_summary_chars + len(clipped_summary) > build_input.limits.max_total_summary_chars:
            excluded.append(_excluded(candidate, "token_budget_pressure"))
            _append_unique(limit_reasons, "token_budget_pressure")
            continue

        if candidate.asset_kind == "memory":
            if len(memories) >= build_input.limits.max_memory_items:
                excluded.append(_excluded(candidate, "limit_reached"))
                _append_unique(limit_reasons, "limit_reached")
                continue
            memories.append(_memory_view(candidate, clipped_summary))
        elif candidate.asset_kind == "skill_guidance":
            if len(skills) >= build_input.limits.max_skill_items:
                excluded.append(_excluded(candidate, "limit_reached"))
                _append_unique(limit_reasons, "limit_reached")
                continue
            skills.append(_skill_view(candidate, clipped_summary))
        total_summary_chars += len(clipped_summary)

        if len(memories) + len(skills) >= build_input.limits.max_total_items:
            _append_unique(limit_reasons, "limit_reached")

    tool_policy = _tool_policy_snapshot(build_input.effective_tool_policy_snapshot)
    included_sensitivities = tuple(
        sorted(
            {item.sensitivity for item in memories}
            | {item.sensitivity for item in skills},
            key=_sensitivity_rank,
        )
    )
    highest = included_sensitivities[-1] if included_sensitivities else "none"
    audit_summary = _audit_summary(memories, skills, excluded, build_input)
    bundle = DepartmentAssetContextBundle(
        department_id=build_input.target_department_id,
        worker_id=build_input.worker_id,
        task_ref=build_input.task_ref,
        selected_memories=tuple(memories),
        selected_skill_guidance=tuple(skills),
        selected_tool_policy_snapshot=tool_policy,
        selection_reasons=build_input.selection_result.selection_reasons
        if memories or skills or tool_policy is not None
        else (),
        excluded_assets=tuple(sorted(excluded, key=_excluded_sort_key)),
        sensitivity_summary=DepartmentContextSensitivitySummary(
            highest_included_sensitivity=highest,
            included_sensitivities=included_sensitivities,
            excluded_sensitive_count=sum(
                1
                for item in excluded
                if _sensitivity_rank(item.sensitivity) > _sensitivity_rank("internal")
            ),
        ),
        limit_summary=DepartmentContextLimitSummary(
            memory_items=len(memories),
            skill_items=len(skills),
            total_items=len(memories) + len(skills) + (1 if tool_policy else 0),
            max_memory_items=build_input.limits.max_memory_items,
            max_skill_items=build_input.limits.max_skill_items,
            max_total_items=build_input.limits.max_total_items,
            max_total_summary_chars=build_input.limits.max_total_summary_chars,
            limit_reached=bool(limit_reasons),
            reasons=tuple(limit_reasons),
        ),
        audit_summary=audit_summary,
        created_at=build_input.created_at,
    )
    validate_context_bundle_payload(department_context_bundle_to_dict(bundle))
    return bundle


def _builder_exclusion_reason(
    candidate: DepartmentContextCandidate,
    build_input: DepartmentContextBuildInput,
) -> str | None:
    limits = build_input.limits
    if candidate.accepted_state != "accepted":
        return "unaccepted_proposal"
    if candidate.asset_kind not in limits.allowed_asset_kinds:
        return "asset_kind_not_allowed"
    if _sensitivity_rank(candidate.sensitivity) > _sensitivity_rank(
        limits.sensitivity_ceiling
    ):
        return "sensitivity_ceiling_exceeded"
    if not candidate.source_refs:
        return "missing_source_refs"
    if _inheritance_depth(candidate.department_id, build_input) > limits.max_inheritance_depth:
        return "inheritance_depth_exceeded"
    if len(candidate.summary) == 0:
        return "empty_summary"
    return None


def _memory_view(
    candidate: DepartmentContextCandidate, summary: str
) -> DepartmentMemoryContextView:
    return DepartmentMemoryContextView(
        department_id=candidate.department_id,
        memory_id=candidate.asset_id,
        kind="department_memory",
        summary=summary,
        tags=candidate.tags,
        source_refs=candidate.source_refs,
        freshness=candidate.freshness,
        sensitivity=candidate.sensitivity,
        accepted_state=candidate.accepted_state,
    )


def _skill_view(
    candidate: DepartmentContextCandidate, summary: str
) -> DepartmentSkillGuidanceContextView:
    return DepartmentSkillGuidanceContextView(
        department_id=candidate.department_id,
        binding_id=candidate.asset_id,
        skill_id=candidate.asset_id,
        display_title=candidate.title or candidate.asset_id,
        guidance_summary=summary,
        constraints=candidate.constraints,
        guardrail_refs=candidate.guardrail_refs,
        audit_refs=candidate.audit_refs,
        source_refs=candidate.source_refs,
        sensitivity=candidate.sensitivity,
        accepted_state=candidate.accepted_state,
    )


def _tool_policy_snapshot(
    snapshot: DepartmentToolPolicyContextSnapshot | None,
) -> DepartmentToolPolicyContextSnapshot | None:
    if snapshot is None:
        return None
    # Copy through the safe contract type to avoid carrying future mutable attrs.
    return DepartmentToolPolicyContextSnapshot(
        department_id=snapshot.department_id,
        allowed_tool_summaries=snapshot.allowed_tool_summaries,
        denied_tool_summaries=snapshot.denied_tool_summaries,
        approval_required_tool_summaries=snapshot.approval_required_tool_summaries,
        denial_reasons=snapshot.denial_reasons,
        approval_status_refs=snapshot.approval_status_refs,
        policy_refs=snapshot.policy_refs,
        audit_refs=snapshot.audit_refs,
    )


def _audit_summary(
    memories: list[DepartmentMemoryContextView],
    skills: list[DepartmentSkillGuidanceContextView],
    excluded: list[DepartmentContextExcludedAsset],
    build_input: DepartmentContextBuildInput,
) -> str:
    if not memories and not skills and build_input.effective_tool_policy_snapshot is None:
        return (
            "no_relevant_safe_assets"
            if not excluded
            else "all_candidates_excluded"
        )
    trace_suffix = f" trace={build_input.audit_trace_ref}" if build_input.audit_trace_ref else ""
    return (
        f"Built department context bundle with {len(memories)} memory summaries, "
        f"{len(skills)} skill guidance summaries, and {len(excluded)} exclusions."
        f"{trace_suffix}"
    )


def _inheritance_depth(
    department_id: str, build_input: DepartmentContextBuildInput
) -> int:
    if department_id == build_input.target_department_id:
        return 0
    try:
        return build_input.department_ancestry.index(department_id) + 1
    except ValueError:
        return build_input.limits.max_inheritance_depth + 1


def _clip(value: str, limit: int) -> str:
    if limit == 0:
        return ""
    if len(value) <= limit:
        return value
    if limit <= 1:
        return value[:limit]
    return value[: max(0, limit - 3)].rstrip() + "..."


def _excluded(
    candidate: DepartmentContextCandidate, reason: str
) -> DepartmentContextExcludedAsset:
    return DepartmentContextExcludedAsset(
        asset_kind=candidate.asset_kind,
        asset_id=candidate.asset_id,
        reason=reason,
        sensitivity=candidate.sensitivity,
        source_refs=candidate.source_refs,
    )


def _excluded_sort_key(asset: DepartmentContextExcludedAsset) -> tuple[str, str, str]:
    return (asset.asset_kind, asset.asset_id, asset.reason)


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _sensitivity_rank(value: str) -> int:
    _require_known_sensitivity(value)
    return _SENSITIVITY_RANK[value]


def _require_known_sensitivity(value: str) -> None:
    if value not in _SENSITIVITY_RANK:
        raise DepartmentContextBuilderError(f"Unknown sensitivity: {value!r}")


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise DepartmentContextBuilderError(f"{field_name} must be a non-empty string")
    return value


def _string_value(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise DepartmentContextBuilderError(f"{field_name} must be a string")
    return value


def _coerce_string_tuple(instance: object, field_name: str) -> None:
    values = getattr(instance, field_name)
    if not isinstance(values, tuple) or any(
        not isinstance(value, str) or not value for value in values
    ):
        raise DepartmentContextBuilderError(
            f"{field_name} must be a tuple of non-empty strings"
        )


def _non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DepartmentContextBuilderError(
            f"{field_name} must be a non-negative integer"
        )
    return value

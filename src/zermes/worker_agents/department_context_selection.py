"""Deterministic relevance selection for department context candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .department_context_bundle import (
    DepartmentContextExcludedAsset,
    DepartmentContextLimitSummary,
    DepartmentContextSelectionReason,
)
from .organization import validate_org_node_id
from .profile import validate_worker_id


class DepartmentContextSelectionError(ValueError):
    """Raised when context selection inputs are invalid."""


_SENSITIVITY_RANK = {
    "low": 0,
    "internal": 1,
    "restricted": 2,
    "user_confirmation_required": 3,
}

_ALLOWED_FRESHNESS = frozenset({"", "fresh", "current", "recent"})
_ASSET_KIND_LIMITS = {
    "memory": "max_memories",
    "skill_guidance": "max_skill_guidance",
}


@dataclass(frozen=True)
class DepartmentContextCandidate:
    """Safe summary candidate produced by department asset readers."""

    asset_kind: str
    asset_id: str
    department_id: str
    summary: str
    tags: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    freshness: str = ""
    sensitivity: str = "low"
    accepted_state: str = "accepted"
    audit_refs: tuple[str, ...] = ()
    task_types: tuple[str, ...] = ()
    worker_roles: tuple[str, ...] = ()
    thread_refs: tuple[str, ...] = ()
    org_refs: tuple[str, ...] = ()
    title: str = ""
    constraints: tuple[str, ...] = ()
    guardrail_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_string(self.asset_kind, "asset_kind")
        _validate_path_segment(self.asset_id, "asset_id")
        validate_org_node_id(self.department_id)
        _require_string(self.summary, "summary")
        for field_name in (
            "tags",
            "source_refs",
            "audit_refs",
            "task_types",
            "worker_roles",
            "thread_refs",
            "org_refs",
            "constraints",
            "guardrail_refs",
        ):
            _coerce_string_tuple(self, field_name)
        _string_value(self.freshness, "freshness")
        _require_string(self.sensitivity, "sensitivity")
        _require_string(self.accepted_state, "accepted_state")
        _string_value(self.title, "title")


@dataclass(frozen=True)
class DepartmentContextSelectionInput:
    """Task, worker, and limit inputs used to select relevant asset summaries."""

    task_ref: str
    task_type: str
    target_department_id: str
    department_ancestry: tuple[str, ...]
    worker_id: str
    worker_role: str
    asset_candidates: tuple[DepartmentContextCandidate, ...]
    thread_refs: tuple[str, ...] = ()
    org_refs: tuple[str, ...] = ()
    max_memories: int = 3
    max_skill_guidance: int = 2
    max_total_items: int = 5
    max_summary_chars: int = 2000
    sensitivity_ceiling: str = "internal"

    def __post_init__(self) -> None:
        _require_string(self.task_ref, "task_ref")
        _require_string(self.task_type, "task_type")
        validate_org_node_id(self.target_department_id)
        object.__setattr__(
            self,
            "department_ancestry",
            tuple(validate_org_node_id(value) for value in self.department_ancestry),
        )
        validate_worker_id(self.worker_id)
        _require_string(self.worker_role, "worker_role")
        if not isinstance(self.asset_candidates, tuple) or any(
            not isinstance(candidate, DepartmentContextCandidate)
            for candidate in self.asset_candidates
        ):
            raise DepartmentContextSelectionError(
                "asset_candidates must be a tuple of DepartmentContextCandidate"
            )
        _coerce_string_tuple(self, "thread_refs")
        _coerce_string_tuple(self, "org_refs")
        for field_name in (
            "max_memories",
            "max_skill_guidance",
            "max_total_items",
            "max_summary_chars",
        ):
            _non_negative_int(getattr(self, field_name), field_name)
        _require_known_sensitivity(self.sensitivity_ceiling)


@dataclass(frozen=True)
class DepartmentContextSelectionResult:
    """Selected candidates plus audit-safe explanations for excluded assets."""

    selected_candidates: tuple[DepartmentContextCandidate, ...]
    excluded_candidates: tuple[DepartmentContextExcludedAsset, ...]
    selection_reasons: tuple[DepartmentContextSelectionReason, ...]
    limit_summary: DepartmentContextLimitSummary
    audit_summary: str

    def __post_init__(self) -> None:
        if not isinstance(self.selected_candidates, tuple) or any(
            not isinstance(candidate, DepartmentContextCandidate)
            for candidate in self.selected_candidates
        ):
            raise DepartmentContextSelectionError(
                "selected_candidates must be DepartmentContextCandidate values"
            )
        if not isinstance(self.excluded_candidates, tuple) or any(
            not isinstance(candidate, DepartmentContextExcludedAsset)
            for candidate in self.excluded_candidates
        ):
            raise DepartmentContextSelectionError(
                "excluded_candidates must be DepartmentContextExcludedAsset values"
            )
        if not isinstance(self.selection_reasons, tuple) or any(
            not isinstance(reason, DepartmentContextSelectionReason)
            for reason in self.selection_reasons
        ):
            raise DepartmentContextSelectionError(
                "selection_reasons must be DepartmentContextSelectionReason values"
            )
        if not isinstance(self.limit_summary, DepartmentContextLimitSummary):
            raise DepartmentContextSelectionError(
                "limit_summary must be a DepartmentContextLimitSummary"
            )
        _require_string(self.audit_summary, "audit_summary")


def select_department_context_assets(
    request: DepartmentContextSelectionInput,
) -> DepartmentContextSelectionResult:
    """Select the strongest relevant safe candidates under the provided limits."""

    if not isinstance(request, DepartmentContextSelectionInput):
        raise DepartmentContextSelectionError(
            "request must be a DepartmentContextSelectionInput"
        )

    scored: list[tuple[int, DepartmentContextCandidate, tuple[str, ...]]] = []
    excluded: list[DepartmentContextExcludedAsset] = []
    for candidate in request.asset_candidates:
        exclusion_reason = _exclusion_reason(candidate, request)
        if exclusion_reason is not None:
            excluded.append(_excluded(candidate, exclusion_reason))
            continue
        reasons = _selection_reasons(candidate, request)
        scored.append((_score(candidate, request, reasons), candidate, reasons))

    scored.sort(key=lambda item: _selection_sort_key(item[0], item[1]))

    selected: list[DepartmentContextCandidate] = []
    selected_reasons: list[DepartmentContextSelectionReason] = []
    kind_counts = {"memory": 0, "skill_guidance": 0}
    summary_chars = 0
    limit_reasons: list[str] = []

    for score, candidate, reasons in scored:
        limit_reason = _limit_reason(candidate, request, kind_counts, summary_chars)
        if limit_reason is not None:
            excluded.append(_excluded(candidate, limit_reason))
            if limit_reason not in limit_reasons:
                limit_reasons.append(limit_reason)
            continue
        selected.append(candidate)
        selected_reasons.append(
            DepartmentContextSelectionReason(
                asset_kind=candidate.asset_kind,
                asset_id=candidate.asset_id,
                reasons=reasons,
                source_refs=candidate.source_refs,
            )
        )
        if candidate.asset_kind in kind_counts:
            kind_counts[candidate.asset_kind] += 1
        summary_chars += len(candidate.summary)

    limit_summary = DepartmentContextLimitSummary(
        memory_items=kind_counts["memory"],
        skill_items=kind_counts["skill_guidance"],
        total_items=len(selected),
        max_memory_items=request.max_memories,
        max_skill_items=request.max_skill_guidance,
        max_total_items=request.max_total_items,
        max_total_summary_chars=request.max_summary_chars,
        limit_reached=bool(limit_reasons),
        reasons=tuple(limit_reasons),
    )
    return DepartmentContextSelectionResult(
        selected_candidates=tuple(selected),
        excluded_candidates=tuple(sorted(excluded, key=_excluded_sort_key)),
        selection_reasons=tuple(selected_reasons),
        limit_summary=limit_summary,
        audit_summary=(
            f"Selected {len(selected)} department context assets; "
            f"excluded {len(excluded)}."
        ),
    )


def _exclusion_reason(
    candidate: DepartmentContextCandidate,
    request: DepartmentContextSelectionInput,
) -> str | None:
    if candidate.accepted_state != "accepted":
        return "unaccepted_proposal"
    if candidate.asset_kind not in {"memory", "skill_guidance"}:
        return "unsupported_asset_kind"
    if not candidate.source_refs:
        return "missing_source_refs"
    if _sensitivity_rank(candidate.sensitivity) > _sensitivity_rank(
        request.sensitivity_ceiling
    ):
        return "sensitivity_ceiling_exceeded"
    if candidate.freshness not in _ALLOWED_FRESHNESS:
        return "freshness_not_allowed"
    if not _department_allowed(candidate, request):
        return "department_not_in_scope"
    if not _has_relevance(candidate, request):
        return "not_relevant_to_task_or_worker"
    return None


def _limit_reason(
    candidate: DepartmentContextCandidate,
    request: DepartmentContextSelectionInput,
    kind_counts: dict[str, int],
    summary_chars: int,
) -> str | None:
    if len(kind_counts) and sum(kind_counts.values()) >= request.max_total_items:
        return "limit_reached"
    if summary_chars + len(candidate.summary) > request.max_summary_chars:
        return "token_budget_pressure"
    limit_field = _ASSET_KIND_LIMITS.get(candidate.asset_kind)
    if limit_field is not None and kind_counts[candidate.asset_kind] >= getattr(
        request, limit_field
    ):
        return "limit_reached"
    return None


def _department_allowed(
    candidate: DepartmentContextCandidate,
    request: DepartmentContextSelectionInput,
) -> bool:
    if candidate.department_id == request.target_department_id:
        return True
    if candidate.department_id in request.department_ancestry:
        return True
    department_ref = f"department:{candidate.department_id}"
    return department_ref in request.org_refs or department_ref in candidate.org_refs


def _has_relevance(
    candidate: DepartmentContextCandidate,
    request: DepartmentContextSelectionInput,
) -> bool:
    return bool(_selection_reasons(candidate, request))


def _selection_reasons(
    candidate: DepartmentContextCandidate,
    request: DepartmentContextSelectionInput,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if candidate.department_id == request.target_department_id:
        reasons.append("department_match")
    elif candidate.department_id in request.department_ancestry:
        reasons.append("department_ancestry_match")
    if request.task_type in candidate.task_types or request.task_type in candidate.tags:
        reasons.append("task_type_match")
    if request.worker_role in candidate.worker_roles or request.worker_role in candidate.tags:
        reasons.append("worker_role_match")
    if set(request.thread_refs).intersection(candidate.thread_refs).union(
        set(request.thread_refs).intersection(candidate.source_refs)
    ):
        reasons.append("thread_ref_match")
    if set(request.org_refs).intersection(candidate.org_refs).union(
        set(request.org_refs).intersection(candidate.source_refs)
    ):
        reasons.append("org_ref_match")
    if candidate.accepted_state == "accepted":
        reasons.append("accepted_asset")
    if _sensitivity_rank(candidate.sensitivity) <= _sensitivity_rank("low"):
        reasons.append("low_sensitivity")
    return tuple(dict.fromkeys(reasons))


def _score(
    candidate: DepartmentContextCandidate,
    request: DepartmentContextSelectionInput,
    reasons: tuple[str, ...],
) -> int:
    score = 0
    score += 80 if "thread_ref_match" in reasons else 0
    score += 70 if "org_ref_match" in reasons else 0
    score += 60 if "department_match" in reasons else 0
    score += 40 if "department_ancestry_match" in reasons else 0
    score += 30 if "task_type_match" in reasons else 0
    score += 20 if "worker_role_match" in reasons else 0
    score += 10 if "accepted_asset" in reasons else 0
    score += 5 if candidate.freshness in {"fresh", "current"} else 0
    return score


def _selection_sort_key(
    score: int, candidate: DepartmentContextCandidate
) -> tuple[Any, ...]:
    return (
        -score,
        _sensitivity_rank(candidate.sensitivity),
        len(candidate.summary),
        candidate.asset_kind,
        candidate.asset_id,
        candidate.department_id,
    )


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


def _sensitivity_rank(value: str) -> int:
    _require_known_sensitivity(value)
    return _SENSITIVITY_RANK[value]


def _require_known_sensitivity(value: str) -> None:
    if value not in _SENSITIVITY_RANK:
        raise DepartmentContextSelectionError(f"Unknown sensitivity: {value!r}")


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise DepartmentContextSelectionError(f"{field_name} must be a non-empty string")
    return value


def _string_value(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise DepartmentContextSelectionError(f"{field_name} must be a string")
    return value


def _coerce_string_tuple(instance: object, field_name: str) -> None:
    values = getattr(instance, field_name)
    if not isinstance(values, tuple) or any(
        not isinstance(value, str) or not value for value in values
    ):
        raise DepartmentContextSelectionError(
            f"{field_name} must be a tuple of non-empty strings"
        )


def _non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DepartmentContextSelectionError(
            f"{field_name} must be a non-negative integer"
        )
    return value


def _validate_path_segment(value: str, field_name: str) -> str:
    _require_string(value, field_name)
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise DepartmentContextSelectionError(
            f"{field_name} must be a single path segment"
        )
    return value

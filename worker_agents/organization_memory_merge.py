"""Safe memory candidate classification for organization merge planning."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Mapping

from .department_memory import (
    DepartmentMemoryProposal,
    DepartmentMemoryRecord,
    DepartmentMemorySensitivity,
)
from .organization import validate_org_node_id
from .private_assets import PrivateAssetProposalInput, PrivateAssetSensitivity


_SENSITIVE_FIELD_NAMES = frozenset(
    {
        "api_key",
        "complete_transcript",
        "cookie",
        "credential",
        "credentials",
        "env",
        "environment",
        "external_raw_log",
        "external_raw_output",
        "full_prompt",
        "full_transcript",
        "private_memory",
        "private_memory_text",
        "raw_log",
        "raw_output",
        "raw_stderr",
        "raw_stdout",
        "raw_transcript",
        "refresh_token",
        "secret",
        "stderr",
        "stdout",
        "token",
    }
)

_SENSITIVITY_RANK = {
    DepartmentMemorySensitivity.LOW: 0,
    DepartmentMemorySensitivity.INTERNAL: 1,
    DepartmentMemorySensitivity.RESTRICTED: 2,
    DepartmentMemorySensitivity.USER_CONFIRMATION_REQUIRED: 3,
}
_STALE_FRESHNESS = frozenset({"stale", "expired", "obsolete", "outdated"})
_HISTORICAL_FRESHNESS = frozenset({"historical", "history", "archived"})


class OrganizationMemoryMergeError(ValueError):
    """Raised when memory merge candidate data is unsafe or invalid."""


class MemoryMergeCandidateSourceKind(StrEnum):
    """Safe source types allowed into memory merge planning."""

    DEPARTMENT_MEMORY = "department_memory"
    DEPARTMENT_PROPOSAL = "department_proposal"
    PRIVATE_ASSET_PROPOSAL_INPUT = "private_asset_proposal_input"
    HISTORICAL_SUMMARY = "historical_summary"


class MemoryMergeClassification(StrEnum):
    """High-level classification before any dedupe or conflict decision runs."""

    VALID = "valid"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"
    STALE = "stale"
    SENSITIVE = "sensitive"
    HISTORICAL_REFERENCE = "historical_reference"


class MemoryMergeDisposition(StrEnum):
    """Initial disposition for downstream review, archive, or rejection flows."""

    ADOPT_CANDIDATE = "adopt_candidate"
    ARCHIVE = "archive"
    REQUIRES_REDACTION = "requires_redaction"
    REQUIRES_DECISION = "requires_decision"
    REJECT = "reject"


@dataclass(frozen=True)
class MemoryMergeCandidate:
    """Audit-safe memory summary considered during department merge planning.

    The candidate stores only summaries and source references. It deliberately
    excludes raw worker-private text, transcripts, stdout, stderr, and logs.
    """

    candidate_id: str
    source_kind: MemoryMergeCandidateSourceKind | str
    source_ref: str
    summary: str
    sensitivity: DepartmentMemorySensitivity | str
    freshness: str
    target_scope: str
    classification_reasons: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    explicit_markers: tuple[str, ...] = ()
    source_hash: str | None = None
    policy_type: str = ""
    task_type: str = ""
    tool_rule: str = ""
    delivery_standard: str = ""
    owner_decision: str = ""

    def __post_init__(self) -> None:
        _validate_identifier(self.candidate_id, "candidate_id")
        object.__setattr__(
            self, "source_kind", _source_kind(self.source_kind)
        )
        object.__setattr__(
            self, "source_ref", _validate_relative_ref(self.source_ref, "source_ref")
        )
        _require_string(self.summary, "summary")
        object.__setattr__(self, "sensitivity", _sensitivity(self.sensitivity))
        _string_value(self.freshness, "freshness")
        _validate_target_scope(self.target_scope)
        object.__setattr__(
            self,
            "classification_reasons",
            _string_tuple(self.classification_reasons, "classification_reasons"),
        )
        object.__setattr__(
            self,
            "source_refs",
            _relative_ref_tuple(self.source_refs, "source_refs"),
        )
        object.__setattr__(
            self,
            "explicit_markers",
            _string_tuple(self.explicit_markers, "explicit_markers"),
        )
        if self.source_hash is not None:
            _require_string(self.source_hash, "source_hash")
        for field_name in (
            "policy_type",
            "task_type",
            "tool_rule",
            "delivery_standard",
            "owner_decision",
        ):
            _string_value(getattr(self, field_name), field_name)


@dataclass(frozen=True)
class MemoryMergeClassificationResult:
    """Candidate classification plus the first safe disposition suggestion."""

    candidate_id: str
    source_kind: MemoryMergeCandidateSourceKind
    classification: MemoryMergeClassification
    disposition: MemoryMergeDisposition
    sensitivity: DepartmentMemorySensitivity
    reasons: tuple[str, ...]
    source_refs: tuple[str, ...]
    target_scope: str

    def __post_init__(self) -> None:
        _validate_identifier(self.candidate_id, "candidate_id")
        if not isinstance(self.source_kind, MemoryMergeCandidateSourceKind):
            raise OrganizationMemoryMergeError(
                "source_kind must be a MemoryMergeCandidateSourceKind"
            )
        object.__setattr__(
            self, "classification", _classification(self.classification)
        )
        object.__setattr__(self, "disposition", _disposition(self.disposition))
        object.__setattr__(self, "sensitivity", _sensitivity(self.sensitivity))
        object.__setattr__(self, "reasons", _string_tuple(self.reasons, "reasons"))
        object.__setattr__(
            self, "source_refs", _relative_ref_tuple(self.source_refs, "source_refs")
        )
        _validate_target_scope(self.target_scope)


@dataclass(frozen=True)
class MemoryDuplicateGroup:
    """Candidates that should not be adopted independently."""

    duplicate_key: str
    candidate_ids: tuple[str, ...]
    source_refs: tuple[str, ...]
    reason: str
    disposition: MemoryMergeDisposition | str = MemoryMergeDisposition.REJECT

    def __post_init__(self) -> None:
        _require_string(self.duplicate_key, "duplicate_key")
        object.__setattr__(
            self, "candidate_ids", _identifier_tuple(self.candidate_ids, "candidate_ids")
        )
        object.__setattr__(
            self, "source_refs", _relative_ref_tuple(self.source_refs, "source_refs")
        )
        _require_string(self.reason, "reason")
        object.__setattr__(self, "disposition", _disposition(self.disposition))


@dataclass(frozen=True)
class MemoryConflictItem:
    """Explicit conflict that needs a human reviewer before adoption."""

    conflict_field: str
    source_candidate_id: str
    target_candidate_id: str
    source_summary: str
    target_summary: str
    source_refs: tuple[str, ...]
    suggested_reviewer: str
    reason: str

    def __post_init__(self) -> None:
        _require_string(self.conflict_field, "conflict_field")
        _validate_identifier(self.source_candidate_id, "source_candidate_id")
        _validate_identifier(self.target_candidate_id, "target_candidate_id")
        _require_string(self.source_summary, "source_summary")
        _require_string(self.target_summary, "target_summary")
        object.__setattr__(
            self, "source_refs", _relative_ref_tuple(self.source_refs, "source_refs")
        )
        _require_string(self.suggested_reviewer, "suggested_reviewer")
        _require_string(self.reason, "reason")


@dataclass(frozen=True)
class MemoryDedupConflictReport:
    """Review report for merge candidates before any active memory write."""

    duplicate_groups: tuple[MemoryDuplicateGroup, ...]
    conflict_items: tuple[MemoryConflictItem, ...]
    rejected_candidate_ids: tuple[str, ...]
    archive_candidate_ids: tuple[str, ...]
    adoptable_candidate_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if any(
            not isinstance(group, MemoryDuplicateGroup)
            for group in self.duplicate_groups
        ):
            raise OrganizationMemoryMergeError(
                "duplicate_groups must contain MemoryDuplicateGroup items"
            )
        if any(not isinstance(item, MemoryConflictItem) for item in self.conflict_items):
            raise OrganizationMemoryMergeError(
                "conflict_items must contain MemoryConflictItem items"
            )
        for field_name in (
            "rejected_candidate_ids",
            "archive_candidate_ids",
            "adoptable_candidate_ids",
        ):
            object.__setattr__(
                self,
                field_name,
                _identifier_tuple(getattr(self, field_name), field_name),
            )


def validate_memory_merge_candidate_payload(payload: Mapping[str, Any]) -> None:
    """Reject unsafe candidate payloads before they enter merge planning."""

    _reject_sensitive_payload(_require_mapping(payload, "payload"), "payload")


def memory_merge_candidate_from_department_memory(
    memory: DepartmentMemoryRecord,
    *,
    target_scope: str,
    freshness: str = "current",
    explicit_markers: tuple[str, ...] = (),
) -> MemoryMergeCandidate:
    """Create a candidate from an accepted department memory summary."""

    return MemoryMergeCandidate(
        candidate_id=memory.memory_id,
        source_kind=MemoryMergeCandidateSourceKind.DEPARTMENT_MEMORY,
        source_ref=f"departments/{memory.department_id}/memory/{memory.memory_id}",
        summary=memory.summary,
        sensitivity=memory.sensitivity,
        freshness=freshness,
        target_scope=target_scope,
        source_refs=memory.source_refs,
        explicit_markers=explicit_markers,
    )


def memory_merge_candidate_from_department_proposal(
    proposal: DepartmentMemoryProposal,
    *,
    target_scope: str,
    freshness: str = "current",
    explicit_markers: tuple[str, ...] = (),
) -> MemoryMergeCandidate:
    """Create a candidate from a pending department memory proposal summary."""

    return MemoryMergeCandidate(
        candidate_id=proposal.proposal_id,
        source_kind=MemoryMergeCandidateSourceKind.DEPARTMENT_PROPOSAL,
        source_ref=f"departments/{proposal.department_id}/memory/proposals/{proposal.proposal_id}",
        summary=proposal.candidate_summary,
        sensitivity=proposal.sensitivity,
        freshness=freshness,
        target_scope=target_scope,
        classification_reasons=("pending_department_proposal",),
        source_refs=proposal.source_refs,
        explicit_markers=explicit_markers,
        source_hash=proposal.source_hash,
    )


def memory_merge_candidate_from_private_asset_proposal_input(
    proposal_input: PrivateAssetProposalInput,
    *,
    candidate_id: str,
    target_scope: str | None = None,
    freshness: str = "current",
    explicit_markers: tuple[str, ...] = (),
) -> MemoryMergeCandidate:
    """Create a candidate from a low-sensitive private asset proposal input.

    This helper only consumes the already-redacted proposal input. It does not
    load or inspect any worker-private asset body.
    """

    if proposal_input.sensitivity is not PrivateAssetSensitivity.LOW:
        raise OrganizationMemoryMergeError(
            "private asset proposal input must be low sensitivity"
        )
    return MemoryMergeCandidate(
        candidate_id=candidate_id,
        source_kind=MemoryMergeCandidateSourceKind.PRIVATE_ASSET_PROPOSAL_INPUT,
        source_ref=(
            f"workers/{proposal_input.source_worker_id}/private_assets/"
            f"proposals/{proposal_input.proposal_input_id}"
        ),
        summary=proposal_input.summary,
        sensitivity=DepartmentMemorySensitivity.LOW,
        freshness=freshness,
        target_scope=target_scope or proposal_input.target_scope,
        classification_reasons=("private_asset_summary_only",),
        source_refs=proposal_input.source_refs,
        explicit_markers=explicit_markers,
        source_hash=proposal_input.content_hash,
    )


def memory_merge_candidate_from_historical_summary(
    *,
    candidate_id: str,
    source_ref: str,
    summary: str,
    target_scope: str,
    sensitivity: DepartmentMemorySensitivity | str = DepartmentMemorySensitivity.LOW,
    source_refs: tuple[str, ...] = (),
    explicit_markers: tuple[str, ...] = (),
) -> MemoryMergeCandidate:
    """Create a candidate intended for archive or historical context only."""

    return MemoryMergeCandidate(
        candidate_id=candidate_id,
        source_kind=MemoryMergeCandidateSourceKind.HISTORICAL_SUMMARY,
        source_ref=source_ref,
        summary=summary,
        sensitivity=sensitivity,
        freshness="historical",
        target_scope=target_scope,
        classification_reasons=("historical_summary_source",),
        source_refs=source_refs,
        explicit_markers=explicit_markers,
    )


def classify_memory_merge_candidate(
    candidate: MemoryMergeCandidate,
) -> MemoryMergeClassificationResult:
    """Classify a candidate from explicit metadata without semantic merging."""

    if not isinstance(candidate, MemoryMergeCandidate):
        raise OrganizationMemoryMergeError(
            "candidate must be a MemoryMergeCandidate"
        )

    reasons = list(candidate.classification_reasons)
    markers = {marker.lower() for marker in candidate.explicit_markers}
    freshness = candidate.freshness.lower()

    if candidate.source_kind is MemoryMergeCandidateSourceKind.HISTORICAL_SUMMARY:
        classification = MemoryMergeClassification.HISTORICAL_REFERENCE
        disposition = MemoryMergeDisposition.ARCHIVE
        reasons.append("historical_summary_source")
    elif _requires_redaction(candidate.sensitivity):
        classification = MemoryMergeClassification.SENSITIVE
        disposition = MemoryMergeDisposition.REQUIRES_REDACTION
        reasons.extend(("sensitive_candidate", "user_confirmation_required"))
    elif "duplicate" in markers:
        classification = MemoryMergeClassification.DUPLICATE
        disposition = MemoryMergeDisposition.REQUIRES_DECISION
        reasons.append("explicit_duplicate_marker")
    elif "conflict" in markers:
        classification = MemoryMergeClassification.CONFLICT
        disposition = MemoryMergeDisposition.REQUIRES_DECISION
        reasons.append("explicit_conflict_marker")
    elif "reject" in markers:
        classification = MemoryMergeClassification.VALID
        disposition = MemoryMergeDisposition.REJECT
        reasons.append("explicit_reject_marker")
    elif freshness in _STALE_FRESHNESS or "stale" in markers:
        classification = MemoryMergeClassification.STALE
        disposition = MemoryMergeDisposition.ARCHIVE
        reasons.append("stale_freshness")
    elif freshness in _HISTORICAL_FRESHNESS or "historical" in markers:
        classification = MemoryMergeClassification.HISTORICAL_REFERENCE
        disposition = MemoryMergeDisposition.ARCHIVE
        reasons.append("historical_reference_marker")
    else:
        classification = MemoryMergeClassification.VALID
        disposition = MemoryMergeDisposition.ADOPT_CANDIDATE
        reasons.append("metadata_allows_adoption_candidate")

    return MemoryMergeClassificationResult(
        candidate_id=candidate.candidate_id,
        source_kind=candidate.source_kind,
        classification=classification,
        disposition=disposition,
        sensitivity=candidate.sensitivity,
        reasons=tuple(dict.fromkeys(reasons)),
        source_refs=(candidate.source_ref, *candidate.source_refs),
        target_scope=candidate.target_scope,
    )


def build_memory_dedup_conflict_report(
    candidates: tuple[MemoryMergeCandidate, ...],
    *,
    target_candidates: tuple[MemoryMergeCandidate, ...] = (),
    suggested_reviewer: str = "department_lead_or_main_agent",
) -> MemoryDedupConflictReport:
    """Build a deterministic pre-adoption report without mutating memory state."""

    _require_string(suggested_reviewer, "suggested_reviewer")
    _validate_candidate_tuple(candidates, "candidates")
    _validate_candidate_tuple(target_candidates, "target_candidates")

    duplicate_groups = _find_duplicate_groups(
        candidates, target_candidates=target_candidates
    )
    incoming_candidate_ids = {candidate.candidate_id for candidate in candidates}
    rejected_candidate_ids = {
        candidate_id
        for group in duplicate_groups
        for candidate_id in group.candidate_ids
        if candidate_id in incoming_candidate_ids
    }
    archive_candidate_ids = {
        candidate.candidate_id
        for candidate in candidates
        if classify_memory_merge_candidate(candidate).disposition
        is MemoryMergeDisposition.ARCHIVE
    }
    conflict_items = _find_conflict_items(
        candidates,
        target_candidates=target_candidates,
        suggested_reviewer=suggested_reviewer,
        ignored_candidate_ids=rejected_candidate_ids.union(archive_candidate_ids),
    )
    conflicted_candidate_ids = {
        item.source_candidate_id for item in conflict_items
    }.union({item.target_candidate_id for item in conflict_items})
    blocked_candidate_ids = rejected_candidate_ids.union(
        archive_candidate_ids, conflicted_candidate_ids
    )
    adoptable_candidate_ids = tuple(
        candidate.candidate_id
        for candidate in candidates
        if candidate.candidate_id not in blocked_candidate_ids
        and classify_memory_merge_candidate(candidate).disposition
        is MemoryMergeDisposition.ADOPT_CANDIDATE
    )

    return MemoryDedupConflictReport(
        duplicate_groups=duplicate_groups,
        conflict_items=conflict_items,
        rejected_candidate_ids=tuple(sorted(rejected_candidate_ids)),
        archive_candidate_ids=tuple(sorted(archive_candidate_ids)),
        adoptable_candidate_ids=adoptable_candidate_ids,
    )


def memory_merge_classification_result_to_dict(
    result: MemoryMergeClassificationResult,
) -> dict[str, Any]:
    """Return a deterministic JSON-ready classification result."""

    return {
        "candidate_id": result.candidate_id,
        "source_kind": result.source_kind.value,
        "classification": result.classification.value,
        "disposition": result.disposition.value,
        "sensitivity": result.sensitivity.value,
        "reasons": list(result.reasons),
        "source_refs": list(result.source_refs),
        "target_scope": result.target_scope,
    }


def memory_duplicate_group_to_dict(group: MemoryDuplicateGroup) -> dict[str, Any]:
    """Return a deterministic JSON-ready duplicate group."""

    return {
        "duplicate_key": group.duplicate_key,
        "candidate_ids": list(group.candidate_ids),
        "source_refs": list(group.source_refs),
        "reason": group.reason,
        "disposition": group.disposition.value,
    }


def memory_conflict_item_to_dict(item: MemoryConflictItem) -> dict[str, Any]:
    """Return a deterministic JSON-ready conflict item."""

    return {
        "conflict_field": item.conflict_field,
        "source_candidate_id": item.source_candidate_id,
        "target_candidate_id": item.target_candidate_id,
        "source_summary": item.source_summary,
        "target_summary": item.target_summary,
        "source_refs": list(item.source_refs),
        "suggested_reviewer": item.suggested_reviewer,
        "reason": item.reason,
    }


def memory_dedup_conflict_report_to_dict(
    report: MemoryDedupConflictReport,
) -> dict[str, Any]:
    """Return a deterministic JSON-ready deduplication and conflict report."""

    return {
        "duplicate_groups": [
            memory_duplicate_group_to_dict(group)
            for group in report.duplicate_groups
        ],
        "conflict_items": [
            memory_conflict_item_to_dict(item) for item in report.conflict_items
        ],
        "rejected_candidate_ids": list(report.rejected_candidate_ids),
        "archive_candidate_ids": list(report.archive_candidate_ids),
        "adoptable_candidate_ids": list(report.adoptable_candidate_ids),
    }


def _source_kind(
    value: MemoryMergeCandidateSourceKind | str,
) -> MemoryMergeCandidateSourceKind:
    try:
        return (
            value
            if isinstance(value, MemoryMergeCandidateSourceKind)
            else MemoryMergeCandidateSourceKind(value)
        )
    except ValueError as exc:
        raise OrganizationMemoryMergeError(
            f"Unknown memory merge candidate source kind: {value!r}"
        ) from exc


def _classification(
    value: MemoryMergeClassification | str,
) -> MemoryMergeClassification:
    try:
        return (
            value
            if isinstance(value, MemoryMergeClassification)
            else MemoryMergeClassification(value)
        )
    except ValueError as exc:
        raise OrganizationMemoryMergeError(
            f"Unknown memory merge classification: {value!r}"
        ) from exc


def _disposition(value: MemoryMergeDisposition | str) -> MemoryMergeDisposition:
    try:
        return (
            value
            if isinstance(value, MemoryMergeDisposition)
            else MemoryMergeDisposition(value)
        )
    except ValueError as exc:
        raise OrganizationMemoryMergeError(
            f"Unknown memory merge disposition: {value!r}"
        ) from exc


def _sensitivity(
    value: DepartmentMemorySensitivity | str,
) -> DepartmentMemorySensitivity:
    try:
        return (
            value
            if isinstance(value, DepartmentMemorySensitivity)
            else DepartmentMemorySensitivity(value)
        )
    except ValueError as exc:
        raise OrganizationMemoryMergeError(
            f"Unknown memory merge sensitivity: {value!r}"
        ) from exc


def _requires_redaction(sensitivity: DepartmentMemorySensitivity) -> bool:
    return _SENSITIVITY_RANK[sensitivity] >= _SENSITIVITY_RANK[
        DepartmentMemorySensitivity.RESTRICTED
    ]


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise OrganizationMemoryMergeError(f"{field_name} must be an object")
    return value


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise OrganizationMemoryMergeError(
            f"{field_name} must be a non-empty string"
        )
    return value


def _string_value(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise OrganizationMemoryMergeError(f"{field_name} must be a string")
    return value


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise OrganizationMemoryMergeError(
            f"{field_name} must be a tuple of non-empty strings"
        )
    return value


def _validate_identifier(value: str, field_name: str) -> str:
    _require_string(value, field_name)
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise OrganizationMemoryMergeError(
            f"{field_name} must be a single path segment"
        )
    return value


def _validate_relative_ref(value: str, field_name: str) -> str:
    _require_string(value, field_name)
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or ".." in posix.parts
        or ".." in windows.parts
    ):
        raise OrganizationMemoryMergeError(f"{field_name} must be a relative ref")
    return value


def _relative_ref_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    return tuple(
        _validate_relative_ref(item, field_name)
        for item in _string_tuple(value, field_name)
    )


def _identifier_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    return tuple(
        _validate_identifier(item, field_name)
        for item in _string_tuple(value, field_name)
    )


def _validate_target_scope(value: str) -> str:
    _require_string(value, "target_scope")
    prefix = "department:"
    if not value.startswith(prefix):
        raise OrganizationMemoryMergeError(
            "target_scope must start with 'department:'"
        )
    validate_org_node_id(value[len(prefix) :])
    return value


def _validate_candidate_tuple(value: Any, field_name: str) -> None:
    if not isinstance(value, tuple) or any(
        not isinstance(candidate, MemoryMergeCandidate) for candidate in value
    ):
        raise OrganizationMemoryMergeError(
            f"{field_name} must be a tuple of MemoryMergeCandidate items"
        )


def _find_duplicate_groups(
    candidates: tuple[MemoryMergeCandidate, ...],
    *,
    target_candidates: tuple[MemoryMergeCandidate, ...] = (),
) -> tuple[MemoryDuplicateGroup, ...]:
    all_candidates = (*target_candidates, *candidates)
    incoming_candidate_ids = {candidate.candidate_id for candidate in candidates}
    groups: list[MemoryDuplicateGroup] = []
    grouped_candidate_ids: set[str] = set()
    for reason, duplicate_key_for_candidate in (
        ("matching_source_hash", _source_hash_duplicate_key),
        ("matching_normalized_summary", _normalized_summary_duplicate_key),
        ("matching_stable_memory_id", _stable_memory_id_duplicate_key),
    ):
        grouped: dict[str, list[MemoryMergeCandidate]] = {}
        for candidate in all_candidates:
            if candidate.candidate_id in grouped_candidate_ids:
                continue
            duplicate_key = duplicate_key_for_candidate(candidate)
            if duplicate_key:
                grouped.setdefault(duplicate_key, []).append(candidate)

        for duplicate_key, members in sorted(grouped.items()):
            if len(members) < 2 or not any(
                member.candidate_id in incoming_candidate_ids for member in members
            ):
                continue
            groups.append(
                MemoryDuplicateGroup(
                    duplicate_key=duplicate_key,
                    candidate_ids=tuple(member.candidate_id for member in members),
                    source_refs=_candidate_source_refs(members),
                    reason=reason,
                )
            )
            grouped_candidate_ids.update(member.candidate_id for member in members)
    return tuple(groups)


def _source_hash_duplicate_key(candidate: MemoryMergeCandidate) -> str:
    if candidate.source_hash:
        return f"source_hash:{candidate.source_hash}"
    return ""


def _normalized_summary_duplicate_key(candidate: MemoryMergeCandidate) -> str:
    normalized_summary = " ".join(candidate.summary.casefold().split())
    if normalized_summary:
        digest = hashlib.sha256(normalized_summary.encode("utf-8")).hexdigest()
        return f"normalized_summary_sha256:{digest}"
    return ""


def _stable_memory_id_duplicate_key(candidate: MemoryMergeCandidate) -> str:
    return f"stable_memory_id:{candidate.candidate_id}"


def _candidate_source_refs(
    candidates: list[MemoryMergeCandidate] | tuple[MemoryMergeCandidate, ...],
) -> tuple[str, ...]:
    refs: list[str] = []
    for candidate in candidates:
        refs.extend((candidate.source_ref, *candidate.source_refs))
    return tuple(dict.fromkeys(refs))


def _find_conflict_items(
    candidates: tuple[MemoryMergeCandidate, ...],
    *,
    target_candidates: tuple[MemoryMergeCandidate, ...],
    suggested_reviewer: str,
    ignored_candidate_ids: set[str],
) -> tuple[MemoryConflictItem, ...]:
    items: list[MemoryConflictItem] = []
    for source in candidates:
        if source.candidate_id in ignored_candidate_ids:
            continue
        for target in (*target_candidates, *candidates):
            if (
                source.candidate_id == target.candidate_id
                or target.candidate_id in ignored_candidate_ids
            ):
                continue
            conflict_field, reason = _explicit_conflict(source, target)
            if conflict_field is None:
                continue
            items.append(
                MemoryConflictItem(
                    conflict_field=conflict_field,
                    source_candidate_id=source.candidate_id,
                    target_candidate_id=target.candidate_id,
                    source_summary=source.summary,
                    target_summary=target.summary,
                    source_refs=_candidate_source_refs((source, target)),
                    suggested_reviewer=suggested_reviewer,
                    reason=reason,
                )
            )
    return _dedupe_conflict_items(items)


def _explicit_conflict(
    source: MemoryMergeCandidate, target: MemoryMergeCandidate
) -> tuple[str | None, str]:
    if (
        source.policy_type
        and target.policy_type
        and source.policy_type != target.policy_type
    ):
        return None, ""
    if not source.task_type or not target.task_type:
        return None, ""
    if source.task_type != target.task_type:
        return None, ""

    tool_conflict = _opposite_tool_rule(source.tool_rule, target.tool_rule)
    if tool_conflict:
        return "tool_rule", "opposite_tool_rule_for_same_task_type"

    for field_name in ("delivery_standard", "owner_decision"):
        source_value = getattr(source, field_name)
        target_value = getattr(target, field_name)
        if source_value and target_value and source_value != target_value:
            return field_name, f"different_{field_name}_for_same_task_type"
    return None, ""


def _opposite_tool_rule(source_rule: str, target_rule: str) -> bool:
    source_action, source_subject = _tool_rule_parts(source_rule)
    target_action, target_subject = _tool_rule_parts(target_rule)
    return (
        source_action in {"allow", "deny"}
        and target_action in {"allow", "deny"}
        and source_action != target_action
        and source_subject == target_subject
    )


def _tool_rule_parts(rule: str) -> tuple[str, str]:
    normalized = " ".join(rule.casefold().replace(":", " ").split())
    if not normalized:
        return "", ""
    action, _, subject = normalized.partition(" ")
    action = {"allowed": "allow", "blocked": "deny", "forbid": "deny"}.get(
        action, action
    )
    return action, subject


def _dedupe_conflict_items(
    items: list[MemoryConflictItem],
) -> tuple[MemoryConflictItem, ...]:
    deduped: dict[tuple[str, str, str], MemoryConflictItem] = {}
    for item in items:
        pair = tuple(sorted((item.source_candidate_id, item.target_candidate_id)))
        key = (item.conflict_field, pair[0], pair[1])
        deduped.setdefault(key, item)
    return tuple(deduped[key] for key in sorted(deduped))


def _reject_sensitive_payload(value: Any, field_name: str) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_text = str(key)
            if key_text.lower() in _SENSITIVE_FIELD_NAMES:
                raise OrganizationMemoryMergeError(
                    f"{field_name} contains sensitive field: {key_text}"
                )
            _reject_sensitive_payload(nested, f"{field_name}.{key_text}")
        return
    if isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _reject_sensitive_payload(nested, f"{field_name}[{index}]")

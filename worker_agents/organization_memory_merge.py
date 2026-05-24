"""Safe memory candidate classification for organization merge planning."""

from __future__ import annotations

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


def _validate_target_scope(value: str) -> str:
    _require_string(value, "target_scope")
    prefix = "department:"
    if not value.startswith(prefix):
        raise OrganizationMemoryMergeError(
            "target_scope must start with 'department:'"
        )
    validate_org_node_id(value[len(prefix) :])
    return value


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

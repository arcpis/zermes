"""Private worker asset contracts and sharing boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Mapping

from .profile import validate_worker_id


PRIVATE_ASSET_SCHEMA_VERSION = 1

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
        "full_prompt",
        "full_transcript",
        "private_memory_text",
        "raw_output",
        "raw_stderr",
        "raw_stdout",
        "raw_transcript",
        "refresh_token",
        "secret",
        "skill_source",
        "source_code",
        "stderr",
        "stdout",
        "token",
    }
)


class PrivateAssetError(ValueError):
    """Raised when a private worker asset crosses a sharing boundary."""


class PrivateAssetKind(StrEnum):
    """Kinds of worker-private durable assets."""

    PRIVATE_MEMORY = "private_memory"
    PERSONAL_PREFERENCE = "personal_preference"
    TASK_LEARNING_CANDIDATE = "task_learning_candidate"


class PrivateAssetSensitivity(StrEnum):
    """Coarse sensitivity labels used before department review."""

    LOW = "low"
    REVIEW_REQUIRED = "review_required"
    HIGH = "high"


class PrivateAssetShareStatus(StrEnum):
    """Whether a private asset may become a low-sensitivity proposal input."""

    PRIVATE_ONLY = "private_only"
    PROPOSAL_ALLOWED = "proposal_allowed"
    PROPOSAL_BLOCKED = "proposal_blocked"


@dataclass(frozen=True)
class PrivateAssetProposalInput:
    """Low-sensitivity proposal input; never an accepted department asset."""

    proposal_input_id: str
    source_worker_id: str
    source_asset_id: str
    target_scope: str
    summary: str
    source_refs: tuple[str, ...] = ()
    content_hash: str | None = None
    sensitivity: PrivateAssetSensitivity | str = PrivateAssetSensitivity.LOW
    review_requirement: str = "main_agent_review"
    audit_summary: str = ""
    schema_version: int = PRIVATE_ASSET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        _validate_identifier(self.proposal_input_id, "proposal_input_id")
        validate_worker_id(self.source_worker_id)
        _validate_identifier(self.source_asset_id, "source_asset_id")
        _require_string(self.target_scope, "target_scope")
        _require_string(self.summary, "summary")
        _require_string(self.review_requirement, "review_requirement")
        object.__setattr__(
            self, "sensitivity", _asset_sensitivity(self.sensitivity)
        )
        object.__setattr__(
            self,
            "source_refs",
            tuple(_validate_relative_ref(ref, "source_refs") for ref in self.source_refs),
        )
        if self.content_hash is not None:
            _require_string(self.content_hash, "content_hash")
        if not isinstance(self.audit_summary, str):
            raise PrivateAssetError("audit_summary must be a string")


@dataclass(frozen=True)
class PrivateMemoryRecord:
    """Private memory owned by exactly one worker."""

    worker_id: str
    asset_id: str
    summary: str
    kind: PrivateAssetKind | str = PrivateAssetKind.PRIVATE_MEMORY
    source_refs: tuple[str, ...] = ()
    sensitivity: PrivateAssetSensitivity | str = PrivateAssetSensitivity.REVIEW_REQUIRED
    share_status: PrivateAssetShareStatus | str = PrivateAssetShareStatus.PRIVATE_ONLY
    created_at: str | None = None
    updated_at: str | None = None
    retention_hint: str | None = None
    audit_summary: str = ""
    schema_version: int = PRIVATE_ASSET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        validate_worker_id(self.worker_id)
        _validate_identifier(self.asset_id, "asset_id")
        _require_string(self.summary, "summary")
        object.__setattr__(self, "kind", _asset_kind(self.kind))
        object.__setattr__(
            self, "sensitivity", _asset_sensitivity(self.sensitivity)
        )
        object.__setattr__(self, "share_status", _share_status(self.share_status))
        object.__setattr__(
            self,
            "source_refs",
            tuple(_validate_relative_ref(ref, "source_refs") for ref in self.source_refs),
        )
        for value, field_name in (
            (self.created_at, "created_at"),
            (self.updated_at, "updated_at"),
            (self.retention_hint, "retention_hint"),
        ):
            if value is not None:
                _require_string(value, field_name)
        if not isinstance(self.audit_summary, str):
            raise PrivateAssetError("audit_summary must be a string")


def validate_private_asset_payload(payload: Mapping[str, Any]) -> None:
    """Reject explicit raw or secret-bearing fields before sharing assets."""

    _reject_sensitive_payload(payload, "payload")


def private_memory_to_proposal_input(
    memory: PrivateMemoryRecord,
    *,
    proposal_input_id: str,
    target_scope: str,
    content_hash: str | None = None,
    review_requirement: str = "main_agent_review",
) -> PrivateAssetProposalInput:
    """Convert an explicitly shareable memory into a low-sensitivity input."""

    if memory.share_status is not PrivateAssetShareStatus.PROPOSAL_ALLOWED:
        raise PrivateAssetError("private memory is not eligible for proposal input")
    if memory.sensitivity is PrivateAssetSensitivity.HIGH:
        raise PrivateAssetError("high-sensitivity private memory requires separate review")
    return PrivateAssetProposalInput(
        proposal_input_id=proposal_input_id,
        source_worker_id=memory.worker_id,
        source_asset_id=memory.asset_id,
        target_scope=target_scope,
        summary=memory.summary,
        source_refs=memory.source_refs,
        content_hash=content_hash,
        sensitivity=memory.sensitivity,
        review_requirement=review_requirement,
        audit_summary=memory.audit_summary,
    )


def private_memory_to_dict(memory: PrivateMemoryRecord) -> dict[str, Any]:
    """Return a deterministic JSON-ready private memory mapping."""

    return {
        "worker_id": memory.worker_id,
        "asset_id": memory.asset_id,
        "schema_version": memory.schema_version,
        "kind": memory.kind.value,
        "summary": memory.summary,
        "source_refs": list(memory.source_refs),
        "sensitivity": memory.sensitivity.value,
        "share_status": memory.share_status.value,
        "created_at": memory.created_at,
        "updated_at": memory.updated_at,
        "retention_hint": memory.retention_hint,
        "audit_summary": memory.audit_summary,
    }


def proposal_input_to_dict(proposal: PrivateAssetProposalInput) -> dict[str, Any]:
    """Return a deterministic JSON-ready proposal input mapping."""

    return {
        "proposal_input_id": proposal.proposal_input_id,
        "schema_version": proposal.schema_version,
        "source_worker_id": proposal.source_worker_id,
        "source_asset_id": proposal.source_asset_id,
        "target_scope": proposal.target_scope,
        "summary": proposal.summary,
        "source_refs": list(proposal.source_refs),
        "content_hash": proposal.content_hash,
        "sensitivity": proposal.sensitivity.value,
        "review_requirement": proposal.review_requirement,
        "audit_summary": proposal.audit_summary,
    }


def worker_private_assets_dir(worker_agents_home: str, worker_id: str) -> PurePosixPath:
    """Return the worker-private durable asset path shape without creating it."""

    validate_worker_id(worker_id)
    return PurePosixPath(worker_agents_home) / "workers" / worker_id / "private_assets"


def department_assets_dir(worker_agents_home: str, department_id: str) -> PurePosixPath:
    """Return the department asset path shape, separate from worker-private data."""

    _validate_identifier(department_id, "department_id")
    return (
        PurePosixPath(worker_agents_home)
        / "organization"
        / "departments"
        / department_id
    )


def _require_schema_version(schema_version: int) -> None:
    if schema_version != PRIVATE_ASSET_SCHEMA_VERSION:
        raise PrivateAssetError(
            f"Unsupported private asset schema_version: {schema_version!r}"
        )


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise PrivateAssetError(f"{field_name} must be a non-empty string")
    return value


def _validate_identifier(value: str, field_name: str) -> str:
    _require_string(value, field_name)
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise PrivateAssetError(f"{field_name} must be a single path segment")
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
        raise PrivateAssetError(f"{field_name} must stay within allowed storage")
    return value


def _asset_kind(value: PrivateAssetKind | str) -> PrivateAssetKind:
    try:
        return value if isinstance(value, PrivateAssetKind) else PrivateAssetKind(value)
    except ValueError as exc:
        raise PrivateAssetError(f"Unknown private asset kind: {value!r}") from exc


def _asset_sensitivity(
    value: PrivateAssetSensitivity | str,
) -> PrivateAssetSensitivity:
    try:
        return (
            value
            if isinstance(value, PrivateAssetSensitivity)
            else PrivateAssetSensitivity(value)
        )
    except ValueError as exc:
        raise PrivateAssetError(f"Unknown private asset sensitivity: {value!r}") from exc


def _share_status(value: PrivateAssetShareStatus | str) -> PrivateAssetShareStatus:
    try:
        return (
            value
            if isinstance(value, PrivateAssetShareStatus)
            else PrivateAssetShareStatus(value)
        )
    except ValueError as exc:
        raise PrivateAssetError(f"Unknown private asset share status: {value!r}") from exc


def _reject_sensitive_payload(payload: Mapping[str, Any], path: str) -> None:
    for key, value in payload.items():
        key_text = str(key).lower()
        if key_text in _SENSITIVE_FIELD_NAMES:
            raise PrivateAssetError(f"{path}.{key} cannot be shared from private assets")
        if isinstance(value, Mapping):
            _reject_sensitive_payload(value, f"{path}.{key}")
        elif isinstance(value, list | tuple):
            for index, item in enumerate(value):
                if isinstance(item, Mapping):
                    _reject_sensitive_payload(item, f"{path}.{key}[{index}]")

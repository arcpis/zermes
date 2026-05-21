"""Private skill experience records for managed workers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Mapping

from .private_assets import (
    PRIVATE_ASSET_SCHEMA_VERSION,
    PrivateAssetError,
    PrivateAssetSensitivity,
    validate_private_asset_payload,
)
from .profile import validate_worker_id


class SkillExperienceKind(StrEnum):
    """Lifecycle position of a worker-private skill experience."""

    PERSONAL_NOTE = "personal_note"
    TASK_LESSON = "task_lesson"
    DEPARTMENT_CANDIDATE = "department_candidate"
    ARCHIVED = "archived"


@dataclass(frozen=True)
class SkillExperienceProposalInput:
    """Low-sensitivity input for a future department skill proposal."""

    proposal_input_id: str
    source_worker_id: str
    source_experience_id: str
    skill_id: str
    target_scope: str
    summary: str
    applicability: str
    limitations: tuple[str, ...] = ()
    risk_notes: tuple[str, ...] = ()
    tool_assumptions: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    sensitivity: PrivateAssetSensitivity | str = PrivateAssetSensitivity.LOW
    review_requirement: str = "department_skill_review"
    schema_version: int = PRIVATE_ASSET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        _validate_segment(self.proposal_input_id, "proposal_input_id")
        validate_worker_id(self.source_worker_id)
        _validate_segment(self.source_experience_id, "source_experience_id")
        _validate_segment(self.skill_id, "skill_id")
        _require_string(self.target_scope, "target_scope")
        _require_string(self.summary, "summary")
        _require_string(self.applicability, "applicability")
        _require_string(self.review_requirement, "review_requirement")
        object.__setattr__(
            self, "sensitivity", _skill_sensitivity(self.sensitivity)
        )
        object.__setattr__(
            self,
            "limitations",
            tuple(_require_string(item, "limitations") for item in self.limitations),
        )
        object.__setattr__(
            self,
            "risk_notes",
            tuple(_require_string(item, "risk_notes") for item in self.risk_notes),
        )
        object.__setattr__(
            self,
            "tool_assumptions",
            tuple(
                _require_string(item, "tool_assumptions")
                for item in self.tool_assumptions
            ),
        )
        object.__setattr__(
            self,
            "source_refs",
            tuple(_validate_relative_ref(ref, "source_refs") for ref in self.source_refs),
        )


@dataclass(frozen=True)
class PrivateSkillExperience:
    """Skill usage experience owned by one worker until reviewed."""

    worker_id: str
    experience_id: str
    skill_id: str
    summary: str
    applicability: str
    kind: SkillExperienceKind | str = SkillExperienceKind.PERSONAL_NOTE
    limitations: tuple[str, ...] = ()
    risk_notes: tuple[str, ...] = ()
    tool_assumptions: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    sensitivity: PrivateAssetSensitivity | str = PrivateAssetSensitivity.REVIEW_REQUIRED
    shareable: bool = False
    review_requirement: str = "department_skill_review"
    schema_version: int = PRIVATE_ASSET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        validate_worker_id(self.worker_id)
        _validate_segment(self.experience_id, "experience_id")
        _validate_segment(self.skill_id, "skill_id")
        _require_string(self.summary, "summary")
        _require_string(self.applicability, "applicability")
        object.__setattr__(self, "kind", _experience_kind(self.kind))
        object.__setattr__(
            self, "sensitivity", _skill_sensitivity(self.sensitivity)
        )
        if not isinstance(self.shareable, bool):
            raise PrivateAssetError("shareable must be a boolean")
        _require_string(self.review_requirement, "review_requirement")
        object.__setattr__(
            self,
            "limitations",
            tuple(_require_string(item, "limitations") for item in self.limitations),
        )
        object.__setattr__(
            self,
            "risk_notes",
            tuple(_require_string(item, "risk_notes") for item in self.risk_notes),
        )
        object.__setattr__(
            self,
            "tool_assumptions",
            tuple(
                _require_string(item, "tool_assumptions")
                for item in self.tool_assumptions
            ),
        )
        object.__setattr__(
            self,
            "source_refs",
            tuple(_validate_relative_ref(ref, "source_refs") for ref in self.source_refs),
        )


def validate_skill_experience_payload(payload: Mapping[str, Any]) -> None:
    """Reject private skill experience payloads that contain raw skill material."""

    validate_private_asset_payload(payload)


def skill_experience_to_proposal_input(
    experience: PrivateSkillExperience,
    *,
    proposal_input_id: str,
    target_scope: str,
) -> SkillExperienceProposalInput:
    """Create a reviewable department-skill input from shareable experience."""

    if not experience.shareable:
        raise PrivateAssetError("skill experience is not eligible for proposal input")
    if experience.sensitivity is PrivateAssetSensitivity.HIGH:
        raise PrivateAssetError("high-sensitivity skill experience requires review first")
    return SkillExperienceProposalInput(
        proposal_input_id=proposal_input_id,
        source_worker_id=experience.worker_id,
        source_experience_id=experience.experience_id,
        skill_id=experience.skill_id,
        target_scope=target_scope,
        summary=experience.summary,
        applicability=experience.applicability,
        limitations=experience.limitations,
        risk_notes=experience.risk_notes,
        tool_assumptions=experience.tool_assumptions,
        source_refs=experience.source_refs,
        sensitivity=experience.sensitivity,
        review_requirement=experience.review_requirement,
    )


def skill_experience_to_dict(experience: PrivateSkillExperience) -> dict[str, Any]:
    """Return a deterministic JSON-ready private skill experience mapping."""

    return {
        "worker_id": experience.worker_id,
        "experience_id": experience.experience_id,
        "schema_version": experience.schema_version,
        "skill_id": experience.skill_id,
        "kind": experience.kind.value,
        "summary": experience.summary,
        "applicability": experience.applicability,
        "limitations": list(experience.limitations),
        "risk_notes": list(experience.risk_notes),
        "tool_assumptions": list(experience.tool_assumptions),
        "source_refs": list(experience.source_refs),
        "sensitivity": experience.sensitivity.value,
        "shareable": experience.shareable,
        "review_requirement": experience.review_requirement,
    }


def skill_experience_proposal_to_dict(
    proposal: SkillExperienceProposalInput,
) -> dict[str, Any]:
    """Return a deterministic JSON-ready skill experience proposal input."""

    return {
        "proposal_input_id": proposal.proposal_input_id,
        "schema_version": proposal.schema_version,
        "source_worker_id": proposal.source_worker_id,
        "source_experience_id": proposal.source_experience_id,
        "skill_id": proposal.skill_id,
        "target_scope": proposal.target_scope,
        "summary": proposal.summary,
        "applicability": proposal.applicability,
        "limitations": list(proposal.limitations),
        "risk_notes": list(proposal.risk_notes),
        "tool_assumptions": list(proposal.tool_assumptions),
        "source_refs": list(proposal.source_refs),
        "sensitivity": proposal.sensitivity.value,
        "review_requirement": proposal.review_requirement,
    }


def _require_schema_version(schema_version: int) -> None:
    if schema_version != PRIVATE_ASSET_SCHEMA_VERSION:
        raise PrivateAssetError(
            f"Unsupported skill experience schema_version: {schema_version!r}"
        )


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise PrivateAssetError(f"{field_name} must be a non-empty string")
    return value


def _validate_segment(value: str, field_name: str) -> str:
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


def _experience_kind(value: SkillExperienceKind | str) -> SkillExperienceKind:
    try:
        return (
            value if isinstance(value, SkillExperienceKind) else SkillExperienceKind(value)
        )
    except ValueError as exc:
        raise PrivateAssetError(f"Unknown skill experience kind: {value!r}") from exc


def _skill_sensitivity(
    value: PrivateAssetSensitivity | str,
) -> PrivateAssetSensitivity:
    try:
        return (
            value
            if isinstance(value, PrivateAssetSensitivity)
            else PrivateAssetSensitivity(value)
        )
    except ValueError as exc:
        raise PrivateAssetError(f"Unknown skill experience sensitivity: {value!r}") from exc

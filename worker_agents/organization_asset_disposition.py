"""Organization-change asset disposition plans for managed workers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Mapping

from .department_skills import (
    DepartmentSkillBindingRecord,
    DepartmentSkillBindingState,
)
from .organization import validate_org_node_id
from .private_assets import PrivateAssetSensitivity
from .private_skill_experience import PrivateSkillExperience


SKILL_DISPOSITION_SCHEMA_VERSION = 1


class OrganizationAssetDispositionError(ValueError):
    """Raised when an organization-change asset plan is unsafe or malformed."""


class SkillDispositionDecision(StrEnum):
    """Disposition outcomes for department skill assets during org changes."""

    ALREADY_EXISTS = "already_exists"
    CANDIDATE_FOR_ADOPTION = "candidate_for_adoption"
    REQUIRES_REVIEW = "requires_review"
    NOT_APPLICABLE = "not_applicable"
    MISSING_DEPENDENCY = "missing_dependency"
    REFERENCES_UNAVAILABLE_TOOL = "references_unavailable_tool"


class SkillExperienceDispositionDecision(StrEnum):
    """Disposition outcomes for private skill experience during org changes."""

    ARCHIVE = "archive"
    REDACT_AND_PROPOSE = "redact_and_propose"
    REJECT = "reject"
    REQUIRES_USER_REVIEW = "requires_user_review"


@dataclass(frozen=True)
class SkillBindingDisposition:
    """Reviewable decision for one source department skill binding."""

    source_department_id: str
    target_department_id: str
    skill_id: str
    source_binding_ref: str
    decision: SkillDispositionDecision | str
    reason: str
    source_refs: tuple[str, ...] = ()
    reviewer: str = "department_skill_review"
    decision_status: str = "planned"
    active_write_candidate: bool = False
    unavailable_tool_refs: tuple[str, ...] = ()
    schema_version: int = SKILL_DISPOSITION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        validate_org_node_id(self.source_department_id)
        validate_org_node_id(self.target_department_id)
        _validate_segment(self.skill_id, "skill_id")
        _validate_relative_ref(self.source_binding_ref, "source_binding_ref")
        object.__setattr__(self, "decision", _skill_decision(self.decision))
        _require_string(self.reason, "reason")
        _require_string(self.reviewer, "reviewer")
        _require_string(self.decision_status, "decision_status")
        if not isinstance(self.active_write_candidate, bool):
            raise OrganizationAssetDispositionError(
                "active_write_candidate must be a boolean"
            )
        object.__setattr__(
            self,
            "source_refs",
            tuple(_validate_relative_ref(ref, "source_refs") for ref in self.source_refs),
        )
        object.__setattr__(
            self,
            "unavailable_tool_refs",
            tuple(
                _require_string(ref, "unavailable_tool_refs")
                for ref in self.unavailable_tool_refs
            ),
        )
        if self.decision in {
            SkillDispositionDecision.MISSING_DEPENDENCY,
            SkillDispositionDecision.REFERENCES_UNAVAILABLE_TOOL,
        } and self.active_write_candidate:
            raise OrganizationAssetDispositionError(
                "blocked skill dispositions cannot be active write candidates"
            )


@dataclass(frozen=True)
class SkillExperienceDisposition:
    """Reviewable decision for private skill experience from moved workers."""

    source_worker_id: str
    source_experience_id: str
    target_department_id: str
    skill_id: str
    decision: SkillExperienceDispositionDecision | str
    reason: str
    redaction_required: bool
    personalization_removal_required: bool
    source_refs: tuple[str, ...] = ()
    reviewer: str = "department_skill_review"
    decision_status: str = "planned"
    proposal_input_candidate: bool = False
    schema_version: int = SKILL_DISPOSITION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        _validate_segment(self.source_worker_id, "source_worker_id")
        _validate_segment(self.source_experience_id, "source_experience_id")
        validate_org_node_id(self.target_department_id)
        _validate_segment(self.skill_id, "skill_id")
        object.__setattr__(self, "decision", _experience_decision(self.decision))
        _require_string(self.reason, "reason")
        _require_string(self.reviewer, "reviewer")
        _require_string(self.decision_status, "decision_status")
        for value, field_name in (
            (self.redaction_required, "redaction_required"),
            (
                self.personalization_removal_required,
                "personalization_removal_required",
            ),
            (self.proposal_input_candidate, "proposal_input_candidate"),
        ):
            if not isinstance(value, bool):
                raise OrganizationAssetDispositionError(f"{field_name} must be a boolean")
        object.__setattr__(
            self,
            "source_refs",
            tuple(_validate_relative_ref(ref, "source_refs") for ref in self.source_refs),
        )
        if self.proposal_input_candidate and (
            self.redaction_required or self.personalization_removal_required
        ):
            raise OrganizationAssetDispositionError(
                "skill experience must be redacted and depersonalized before proposal"
            )


@dataclass(frozen=True)
class SkillDispositionPlan:
    """Skill disposition plan produced before any active binding write occurs."""

    source_department_id: str
    target_department_id: str
    binding_dispositions: tuple[SkillBindingDisposition, ...] = ()
    experience_dispositions: tuple[SkillExperienceDisposition, ...] = ()
    reviewer: str = "department_skill_review"
    decision_status: str = "planned"
    active_binding_candidate_refs: tuple[str, ...] = ()
    schema_version: int = SKILL_DISPOSITION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        validate_org_node_id(self.source_department_id)
        validate_org_node_id(self.target_department_id)
        _require_string(self.reviewer, "reviewer")
        _require_string(self.decision_status, "decision_status")
        _coerce_typed_tuple(self, "binding_dispositions", SkillBindingDisposition)
        _coerce_typed_tuple(self, "experience_dispositions", SkillExperienceDisposition)
        object.__setattr__(
            self,
            "active_binding_candidate_refs",
            tuple(
                _validate_relative_ref(ref, "active_binding_candidate_refs")
                for ref in self.active_binding_candidate_refs
            ),
        )
        for disposition in self.binding_dispositions:
            if disposition.source_department_id != self.source_department_id:
                raise OrganizationAssetDispositionError(
                    "binding disposition source department does not match plan"
                )
            if disposition.target_department_id != self.target_department_id:
                raise OrganizationAssetDispositionError(
                    "binding disposition target department does not match plan"
                )
        for disposition in self.experience_dispositions:
            if disposition.target_department_id != self.target_department_id:
                raise OrganizationAssetDispositionError(
                    "experience disposition target department does not match plan"
                )


@dataclass(frozen=True)
class SkillExperienceDispositionInput:
    """Sanitization facts used to plan private skill experience disposition."""

    experience: PrivateSkillExperience
    redacted: bool = False
    personalization_removed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.experience, PrivateSkillExperience):
            raise OrganizationAssetDispositionError(
                "experience must be a PrivateSkillExperience"
            )
        if not isinstance(self.redacted, bool):
            raise OrganizationAssetDispositionError("redacted must be a boolean")
        if not isinstance(self.personalization_removed, bool):
            raise OrganizationAssetDispositionError(
                "personalization_removed must be a boolean"
            )


def plan_skill_disposition(
    *,
    source_department_id: str,
    target_department_id: str,
    source_bindings: tuple[DepartmentSkillBindingRecord, ...] = (),
    target_bindings: tuple[DepartmentSkillBindingRecord, ...] = (),
    available_skill_ids: tuple[str, ...] = (),
    available_tool_ids: tuple[str, ...] = (),
    experiences: tuple[SkillExperienceDispositionInput, ...] = (),
    reviewer: str = "department_skill_review",
) -> SkillDispositionPlan:
    """Build a conservative skill plan without mutating active department assets."""

    validate_org_node_id(source_department_id)
    validate_org_node_id(target_department_id)
    known_skill_ids = set(_string_tuple(available_skill_ids, "available_skill_ids"))
    known_tool_ids = set(_string_tuple(available_tool_ids, "available_tool_ids"))
    target_skill_ids = {binding.skill_id for binding in target_bindings}

    binding_dispositions = tuple(
        _plan_binding_disposition(
            binding,
            target_department_id=target_department_id,
            target_skill_ids=target_skill_ids,
            known_skill_ids=known_skill_ids,
            known_tool_ids=known_tool_ids,
            reviewer=reviewer,
        )
        for binding in source_bindings
    )
    experience_dispositions = tuple(
        _plan_experience_disposition(
            item,
            target_department_id=target_department_id,
            reviewer=reviewer,
        )
        for item in experiences
    )

    # These refs are proposal inputs only. Callers must still pass normal review
    # before any active department binding is written.
    active_binding_candidate_refs = tuple(
        disposition.source_binding_ref
        for disposition in binding_dispositions
        if disposition.active_write_candidate
    )
    return SkillDispositionPlan(
        source_department_id=source_department_id,
        target_department_id=target_department_id,
        binding_dispositions=binding_dispositions,
        experience_dispositions=experience_dispositions,
        reviewer=reviewer,
        active_binding_candidate_refs=active_binding_candidate_refs,
    )


def skill_disposition_plan_to_dict(plan: SkillDispositionPlan) -> dict[str, Any]:
    """Return a deterministic JSON-ready skill disposition plan."""

    return {
        "source_department_id": plan.source_department_id,
        "target_department_id": plan.target_department_id,
        "schema_version": plan.schema_version,
        "reviewer": plan.reviewer,
        "decision_status": plan.decision_status,
        "binding_dispositions": [
            skill_binding_disposition_to_dict(item)
            for item in plan.binding_dispositions
        ],
        "experience_dispositions": [
            skill_experience_disposition_to_dict(item)
            for item in plan.experience_dispositions
        ],
        "active_binding_candidate_refs": list(plan.active_binding_candidate_refs),
    }


def skill_binding_disposition_to_dict(
    disposition: SkillBindingDisposition,
) -> dict[str, Any]:
    """Return a deterministic JSON-ready binding disposition."""

    return {
        "source_department_id": disposition.source_department_id,
        "target_department_id": disposition.target_department_id,
        "schema_version": disposition.schema_version,
        "skill_id": disposition.skill_id,
        "source_binding_ref": disposition.source_binding_ref,
        "decision": disposition.decision.value,
        "reason": disposition.reason,
        "source_refs": list(disposition.source_refs),
        "reviewer": disposition.reviewer,
        "decision_status": disposition.decision_status,
        "active_write_candidate": disposition.active_write_candidate,
        "unavailable_tool_refs": list(disposition.unavailable_tool_refs),
    }


def skill_experience_disposition_to_dict(
    disposition: SkillExperienceDisposition,
) -> dict[str, Any]:
    """Return a deterministic JSON-ready experience disposition."""

    return {
        "source_worker_id": disposition.source_worker_id,
        "source_experience_id": disposition.source_experience_id,
        "target_department_id": disposition.target_department_id,
        "schema_version": disposition.schema_version,
        "skill_id": disposition.skill_id,
        "decision": disposition.decision.value,
        "reason": disposition.reason,
        "redaction_required": disposition.redaction_required,
        "personalization_removal_required": (
            disposition.personalization_removal_required
        ),
        "source_refs": list(disposition.source_refs),
        "reviewer": disposition.reviewer,
        "decision_status": disposition.decision_status,
        "proposal_input_candidate": disposition.proposal_input_candidate,
    }


def skill_disposition_plan_from_dict(data: Mapping[str, Any]) -> SkillDispositionPlan:
    """Load a skill disposition plan after boundary validation."""

    data = _require_mapping(data, "skill disposition plan")
    _reject_unknown_fields(data, _PLAN_FIELDS, "skill disposition plan")
    return SkillDispositionPlan(
        source_department_id=_require_string(
            data.get("source_department_id"), "source_department_id"
        ),
        target_department_id=_require_string(
            data.get("target_department_id"), "target_department_id"
        ),
        schema_version=data.get("schema_version", SKILL_DISPOSITION_SCHEMA_VERSION),
        reviewer=_string_value(data.get("reviewer", "department_skill_review"), "reviewer"),
        decision_status=_string_value(
            data.get("decision_status", "planned"), "decision_status"
        ),
        binding_dispositions=tuple(
            skill_binding_disposition_from_dict(item)
            for item in _mapping_tuple(
                data.get("binding_dispositions", ()), "binding_dispositions"
            )
        ),
        experience_dispositions=tuple(
            skill_experience_disposition_from_dict(item)
            for item in _mapping_tuple(
                data.get("experience_dispositions", ()), "experience_dispositions"
            )
        ),
        active_binding_candidate_refs=_string_tuple(
            data.get("active_binding_candidate_refs", ()),
            "active_binding_candidate_refs",
        ),
    )


def skill_binding_disposition_from_dict(
    data: Mapping[str, Any],
) -> SkillBindingDisposition:
    """Load a binding disposition after boundary validation."""

    data = _require_mapping(data, "skill binding disposition")
    _reject_unknown_fields(data, _BINDING_DISPOSITION_FIELDS, "skill binding disposition")
    return SkillBindingDisposition(
        source_department_id=_require_string(
            data.get("source_department_id"), "source_department_id"
        ),
        target_department_id=_require_string(
            data.get("target_department_id"), "target_department_id"
        ),
        schema_version=data.get("schema_version", SKILL_DISPOSITION_SCHEMA_VERSION),
        skill_id=_require_string(data.get("skill_id"), "skill_id"),
        source_binding_ref=_require_string(
            data.get("source_binding_ref"), "source_binding_ref"
        ),
        decision=data.get("decision", SkillDispositionDecision.REQUIRES_REVIEW),
        reason=_require_string(data.get("reason"), "reason"),
        source_refs=_string_tuple(data.get("source_refs", ()), "source_refs"),
        reviewer=_string_value(data.get("reviewer", "department_skill_review"), "reviewer"),
        decision_status=_string_value(
            data.get("decision_status", "planned"), "decision_status"
        ),
        active_write_candidate=data.get("active_write_candidate", False),
        unavailable_tool_refs=_string_tuple(
            data.get("unavailable_tool_refs", ()), "unavailable_tool_refs"
        ),
    )


def skill_experience_disposition_from_dict(
    data: Mapping[str, Any],
) -> SkillExperienceDisposition:
    """Load an experience disposition after boundary validation."""

    data = _require_mapping(data, "skill experience disposition")
    _reject_unknown_fields(
        data, _EXPERIENCE_DISPOSITION_FIELDS, "skill experience disposition"
    )
    return SkillExperienceDisposition(
        source_worker_id=_require_string(data.get("source_worker_id"), "source_worker_id"),
        source_experience_id=_require_string(
            data.get("source_experience_id"), "source_experience_id"
        ),
        target_department_id=_require_string(
            data.get("target_department_id"), "target_department_id"
        ),
        schema_version=data.get("schema_version", SKILL_DISPOSITION_SCHEMA_VERSION),
        skill_id=_require_string(data.get("skill_id"), "skill_id"),
        decision=data.get("decision", SkillExperienceDispositionDecision.REQUIRES_USER_REVIEW),
        reason=_require_string(data.get("reason"), "reason"),
        redaction_required=data.get("redaction_required", True),
        personalization_removal_required=data.get(
            "personalization_removal_required", True
        ),
        source_refs=_string_tuple(data.get("source_refs", ()), "source_refs"),
        reviewer=_string_value(data.get("reviewer", "department_skill_review"), "reviewer"),
        decision_status=_string_value(
            data.get("decision_status", "planned"), "decision_status"
        ),
        proposal_input_candidate=data.get("proposal_input_candidate", False),
    )


def _plan_binding_disposition(
    binding: DepartmentSkillBindingRecord,
    *,
    target_department_id: str,
    target_skill_ids: set[str],
    known_skill_ids: set[str],
    known_tool_ids: set[str],
    reviewer: str,
) -> SkillBindingDisposition:
    if binding.skill_id in target_skill_ids:
        decision = SkillDispositionDecision.ALREADY_EXISTS
        reason = "target department already has a reviewed binding for this skill"
        active_write_candidate = False
        unavailable_tool_refs: tuple[str, ...] = ()
    elif binding.skill_id not in known_skill_ids:
        decision = SkillDispositionDecision.MISSING_DEPENDENCY
        reason = "skill is not available in the target profile or registry snapshot"
        active_write_candidate = False
        unavailable_tool_refs = ()
    else:
        unavailable_tool_refs = tuple(
            tool_ref
            for tool_ref in binding.tool_assumptions
            if tool_ref not in known_tool_ids
        )
        if unavailable_tool_refs:
            decision = SkillDispositionDecision.REFERENCES_UNAVAILABLE_TOOL
            reason = "skill guidance references tools unavailable to the target"
            active_write_candidate = False
        elif binding.state in {
            DepartmentSkillBindingState.DEPRECATED,
            DepartmentSkillBindingState.DISABLED,
        }:
            decision = SkillDispositionDecision.NOT_APPLICABLE
            reason = "source binding is not active guidance for new department adoption"
            active_write_candidate = False
        elif binding.state is DepartmentSkillBindingState.RESTRICTED:
            decision = SkillDispositionDecision.REQUIRES_REVIEW
            reason = "restricted skill binding requires explicit department review"
            active_write_candidate = False
        else:
            decision = SkillDispositionDecision.CANDIDATE_FOR_ADOPTION
            reason = "eligible only as a reviewed adoption proposal"
            active_write_candidate = True

    return SkillBindingDisposition(
        source_department_id=binding.department_id,
        target_department_id=target_department_id,
        skill_id=binding.skill_id,
        source_binding_ref=f"departments/{binding.department_id}/skills/{binding.binding_id}",
        decision=decision,
        reason=reason,
        source_refs=binding.source_refs,
        reviewer=reviewer,
        active_write_candidate=active_write_candidate,
        unavailable_tool_refs=unavailable_tool_refs,
    )


def _plan_experience_disposition(
    item: SkillExperienceDispositionInput,
    *,
    target_department_id: str,
    reviewer: str,
) -> SkillExperienceDisposition:
    experience = item.experience
    redaction_required = not item.redacted
    personalization_removal_required = not item.personalization_removed

    if experience.sensitivity is PrivateAssetSensitivity.HIGH:
        decision = SkillExperienceDispositionDecision.REJECT
        reason = "high-sensitivity private experience cannot be proposed"
        proposal_input_candidate = False
    elif not experience.shareable:
        decision = SkillExperienceDispositionDecision.REQUIRES_USER_REVIEW
        reason = "private experience is not shareable without user review"
        proposal_input_candidate = False
    elif redaction_required or personalization_removal_required:
        decision = SkillExperienceDispositionDecision.REQUIRES_USER_REVIEW
        reason = "experience must be redacted and depersonalized before proposal"
        proposal_input_candidate = False
    else:
        decision = SkillExperienceDispositionDecision.REDACT_AND_PROPOSE
        reason = "experience is sanitized and can become a reviewed proposal input"
        proposal_input_candidate = True

    return SkillExperienceDisposition(
        source_worker_id=experience.worker_id,
        source_experience_id=experience.experience_id,
        target_department_id=target_department_id,
        skill_id=experience.skill_id,
        decision=decision,
        reason=reason,
        redaction_required=redaction_required,
        personalization_removal_required=personalization_removal_required,
        source_refs=experience.source_refs,
        reviewer=reviewer,
        proposal_input_candidate=proposal_input_candidate,
    )


def _require_schema_version(schema_version: int) -> None:
    if schema_version != SKILL_DISPOSITION_SCHEMA_VERSION:
        raise OrganizationAssetDispositionError(
            f"Unsupported skill disposition schema_version: {schema_version!r}"
        )


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise OrganizationAssetDispositionError(f"{field_name} must be a non-empty string")
    return value


def _string_value(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise OrganizationAssetDispositionError(f"{field_name} must be a string")
    return value


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise OrganizationAssetDispositionError(f"{field_name} must be a list of strings")
    return tuple(_require_string(item, field_name) for item in value)


def _mapping_tuple(value: Any, field_name: str) -> tuple[Mapping[str, Any], ...]:
    if isinstance(value, Mapping) or not isinstance(value, (list, tuple)):
        raise OrganizationAssetDispositionError(f"{field_name} must be a list of objects")
    return tuple(_require_mapping(item, field_name) for item in value)


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise OrganizationAssetDispositionError(f"{field_name} must be an object")
    return value


def _validate_segment(value: str, field_name: str) -> str:
    _require_string(value, field_name)
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise OrganizationAssetDispositionError(
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
        raise OrganizationAssetDispositionError(
            f"{field_name} must stay within allowed storage"
        )
    return value


def _coerce_typed_tuple(
    instance: object,
    field_name: str,
    expected_type: type,
) -> None:
    values = getattr(instance, field_name)
    if not isinstance(values, tuple) or any(
        not isinstance(value, expected_type) for value in values
    ):
        raise OrganizationAssetDispositionError(
            f"{field_name} must contain {expected_type.__name__} values"
        )


def _reject_unknown_fields(
    data: Mapping[str, Any], allowed_fields: set[str], field_name: str
) -> None:
    unknown_fields = sorted(set(data) - allowed_fields)
    if unknown_fields:
        joined = ", ".join(unknown_fields)
        raise OrganizationAssetDispositionError(
            f"{field_name} has unknown fields: {joined}"
        )


def _skill_decision(value: SkillDispositionDecision | str) -> SkillDispositionDecision:
    try:
        return (
            value
            if isinstance(value, SkillDispositionDecision)
            else SkillDispositionDecision(value)
        )
    except ValueError as exc:
        raise OrganizationAssetDispositionError(
            f"Unknown skill disposition decision: {value!r}"
        ) from exc


def _experience_decision(
    value: SkillExperienceDispositionDecision | str,
) -> SkillExperienceDispositionDecision:
    try:
        return (
            value
            if isinstance(value, SkillExperienceDispositionDecision)
            else SkillExperienceDispositionDecision(value)
        )
    except ValueError as exc:
        raise OrganizationAssetDispositionError(
            f"Unknown skill experience disposition decision: {value!r}"
        ) from exc


_PLAN_FIELDS = {
    "source_department_id",
    "target_department_id",
    "schema_version",
    "reviewer",
    "decision_status",
    "binding_dispositions",
    "experience_dispositions",
    "active_binding_candidate_refs",
}

_BINDING_DISPOSITION_FIELDS = {
    "source_department_id",
    "target_department_id",
    "schema_version",
    "skill_id",
    "source_binding_ref",
    "decision",
    "reason",
    "source_refs",
    "reviewer",
    "decision_status",
    "active_write_candidate",
    "unavailable_tool_refs",
}

_EXPERIENCE_DISPOSITION_FIELDS = {
    "source_worker_id",
    "source_experience_id",
    "target_department_id",
    "schema_version",
    "skill_id",
    "decision",
    "reason",
    "redaction_required",
    "personalization_removal_required",
    "source_refs",
    "reviewer",
    "decision_status",
    "proposal_input_candidate",
}

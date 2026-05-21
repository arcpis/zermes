"""Department skill binding contracts and policy-ready helpers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping

from .organization import validate_org_node_id


DEPARTMENT_SKILL_SCHEMA_VERSION = 1

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
        "private_experience_text",
        "raw_skill_instruction",
        "raw_output",
        "raw_stderr",
        "raw_stdout",
        "raw_transcript",
        "refresh_token",
        "secret",
        "skill_source_code",
        "stderr",
        "stdout",
        "token",
    }
)


class DepartmentSkillError(ValueError):
    """Raised when a department skill binding crosses a safe asset boundary."""


class DepartmentSkillBindingState(StrEnum):
    """Reviewable state of a department's relationship to one skill."""

    RECOMMENDED = "recommended"
    DEFAULT = "default"
    RESTRICTED = "restricted"
    DEPRECATED = "deprecated"
    DISABLED = "disabled"


class DepartmentSkillBindingVisibility(StrEnum):
    """How far low-sensitivity binding guidance may be reused."""

    PRIVATE_TO_DEPARTMENT = "private_to_department"
    INHERITABLE_GUIDANCE = "inheritable_guidance"
    ORGANIZATION_GUIDANCE = "organization_guidance"


class DepartmentSkillBindingSensitivity(StrEnum):
    """Sensitivity labels for department skill guidance."""

    LOW = "low"
    INTERNAL = "internal"
    RESTRICTED = "restricted"
    USER_CONFIRMATION_REQUIRED = "user_confirmation_required"


class DepartmentSkillProposalState(StrEnum):
    """Review lifecycle for department skill binding proposals."""

    PENDING = "pending"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


class DepartmentSkillProposalAction(StrEnum):
    """Requested action carried by a department skill proposal."""

    ADD_BINDING = "add_binding"
    UPDATE_GUIDANCE = "update_guidance"
    RESTRICT_BINDING = "restrict_binding"
    DEPRECATE_BINDING = "deprecate_binding"
    DISABLE_BINDING = "disable_binding"


@dataclass(frozen=True)
class DepartmentSkillBindingRecord:
    """Approved department skill guidance; pending proposals use another record."""

    department_id: str
    binding_id: str
    skill_id: str
    skill_source: str
    usage_guidance: str
    state: DepartmentSkillBindingState | str = DepartmentSkillBindingState.RECOMMENDED
    visibility: DepartmentSkillBindingVisibility | str = (
        DepartmentSkillBindingVisibility.PRIVATE_TO_DEPARTMENT
    )
    sensitivity: DepartmentSkillBindingSensitivity | str = (
        DepartmentSkillBindingSensitivity.LOW
    )
    version_constraint: str = ""
    applicability: tuple[str, ...] = ()
    disabled_conditions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    risk_notes: tuple[str, ...] = ()
    tool_assumptions: tuple[str, ...] = ()
    owner: str = ""
    source_refs: tuple[str, ...] = ()
    revision: int = 1
    active: bool = True
    accepted_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    audit_summary: str = ""
    replacement_skill_id: str | None = None
    schema_version: int = DEPARTMENT_SKILL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        validate_org_node_id(self.department_id)
        _validate_identifier(self.binding_id, "binding_id")
        _validate_identifier(self.skill_id, "skill_id")
        _require_string(self.skill_source, "skill_source")
        _require_string(self.usage_guidance, "usage_guidance")
        object.__setattr__(self, "state", _binding_state(self.state))
        object.__setattr__(self, "visibility", _binding_visibility(self.visibility))
        object.__setattr__(self, "sensitivity", _binding_sensitivity(self.sensitivity))
        _require_positive_int(self.revision, "revision")
        if not isinstance(self.active, bool):
            raise DepartmentSkillError("active must be a boolean")
        if self.replacement_skill_id is not None:
            _validate_identifier(self.replacement_skill_id, "replacement_skill_id")
        for value, field_name in (
            (self.version_constraint, "version_constraint"),
            (self.owner, "owner"),
            (self.audit_summary, "audit_summary"),
        ):
            if not isinstance(value, str):
                raise DepartmentSkillError(f"{field_name} must be a string")
        for value, field_name in (
            (self.accepted_at, "accepted_at"),
            (self.created_at, "created_at"),
            (self.updated_at, "updated_at"),
        ):
            if value is not None:
                _require_string(value, field_name)
        _coerce_string_tuple(self, "applicability")
        _coerce_string_tuple(self, "disabled_conditions")
        _coerce_string_tuple(self, "limitations")
        _coerce_string_tuple(self, "risk_notes")
        _coerce_string_tuple(self, "tool_assumptions")
        object.__setattr__(
            self,
            "source_refs",
            tuple(_validate_relative_ref(ref, "source_refs") for ref in self.source_refs),
        )


@dataclass(frozen=True)
class DepartmentSkillBindingProposal:
    """Reviewable candidate for a department skill binding change."""

    proposal_id: str
    department_id: str
    proposed_action: DepartmentSkillProposalAction | str
    skill_id: str
    candidate_guidance: str
    source_actor: str
    source_refs: tuple[str, ...] = ()
    rationale: str = ""
    source_hash: str | None = None
    skill_source: str = "profile_skill_registry"
    version_constraint: str = ""
    candidate_state: DepartmentSkillBindingState | str = (
        DepartmentSkillBindingState.RECOMMENDED
    )
    visibility: DepartmentSkillBindingVisibility | str = (
        DepartmentSkillBindingVisibility.PRIVATE_TO_DEPARTMENT
    )
    sensitivity: DepartmentSkillBindingSensitivity | str = (
        DepartmentSkillBindingSensitivity.INTERNAL
    )
    applicability: tuple[str, ...] = ()
    disabled_conditions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    risk_notes: tuple[str, ...] = ()
    tool_assumptions: tuple[str, ...] = ()
    owner: str = ""
    review_requirement: str = "department_skill_review"
    state: DepartmentSkillProposalState | str = DepartmentSkillProposalState.PENDING
    created_at: str | None = None
    updated_at: str | None = None
    audit_summary: str = ""
    replacement_skill_id: str | None = None
    schema_version: int = DEPARTMENT_SKILL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        _validate_identifier(self.proposal_id, "proposal_id")
        validate_org_node_id(self.department_id)
        object.__setattr__(
            self, "proposed_action", _proposal_action(self.proposed_action)
        )
        _validate_identifier(self.skill_id, "skill_id")
        _require_string(self.candidate_guidance, "candidate_guidance")
        _require_string(self.source_actor, "source_actor")
        _require_string(self.skill_source, "skill_source")
        object.__setattr__(self, "candidate_state", _binding_state(self.candidate_state))
        object.__setattr__(self, "visibility", _binding_visibility(self.visibility))
        object.__setattr__(self, "sensitivity", _binding_sensitivity(self.sensitivity))
        object.__setattr__(self, "state", _proposal_state(self.state))
        if self.replacement_skill_id is not None:
            _validate_identifier(self.replacement_skill_id, "replacement_skill_id")
        for value, field_name in (
            (self.rationale, "rationale"),
            (self.version_constraint, "version_constraint"),
            (self.owner, "owner"),
            (self.audit_summary, "audit_summary"),
        ):
            if not isinstance(value, str):
                raise DepartmentSkillError(f"{field_name} must be a string")
        for value, field_name in (
            (self.source_hash, "source_hash"),
            (self.created_at, "created_at"),
            (self.updated_at, "updated_at"),
        ):
            if value is not None:
                _require_string(value, field_name)
        _require_string(self.review_requirement, "review_requirement")
        _coerce_string_tuple(self, "applicability")
        _coerce_string_tuple(self, "disabled_conditions")
        _coerce_string_tuple(self, "limitations")
        _coerce_string_tuple(self, "risk_notes")
        _coerce_string_tuple(self, "tool_assumptions")
        object.__setattr__(
            self,
            "source_refs",
            tuple(_validate_relative_ref(ref, "source_refs") for ref in self.source_refs),
        )


def validate_department_skill_payload(payload: Mapping[str, Any]) -> None:
    """Reject raw skill material, private experience text, and secrets."""

    _reject_sensitive_payload(payload, "payload")


def department_skill_dir(worker_agents_home: str | Path, department_id: str) -> Path:
    """Return the durable department skill root without creating it."""

    validate_org_node_id(department_id)
    return (
        Path(worker_agents_home)
        / "organization"
        / "departments"
        / department_id
        / "skills"
    )


def department_skill_binding_to_dict(
    binding: DepartmentSkillBindingRecord,
) -> dict[str, Any]:
    """Return a deterministic JSON-ready active department skill binding."""

    return {
        "department_id": binding.department_id,
        "binding_id": binding.binding_id,
        "schema_version": binding.schema_version,
        "skill_id": binding.skill_id,
        "skill_source": binding.skill_source,
        "version_constraint": binding.version_constraint,
        "state": binding.state.value,
        "visibility": binding.visibility.value,
        "sensitivity": binding.sensitivity.value,
        "usage_guidance": binding.usage_guidance,
        "applicability": list(binding.applicability),
        "disabled_conditions": list(binding.disabled_conditions),
        "limitations": list(binding.limitations),
        "risk_notes": list(binding.risk_notes),
        "tool_assumptions": list(binding.tool_assumptions),
        "owner": binding.owner,
        "source_refs": list(binding.source_refs),
        "revision": binding.revision,
        "active": binding.active,
        "accepted_at": binding.accepted_at,
        "created_at": binding.created_at,
        "updated_at": binding.updated_at,
        "audit_summary": binding.audit_summary,
        "replacement_skill_id": binding.replacement_skill_id,
    }


def department_skill_binding_from_dict(
    data: Mapping[str, Any],
) -> DepartmentSkillBindingRecord:
    """Load an active department skill binding after boundary validation."""

    data = _require_mapping(data, "department skill binding")
    _reject_unknown_fields(data, _BINDING_FIELDS, "department skill binding")
    return DepartmentSkillBindingRecord(
        department_id=_require_string(data.get("department_id"), "department_id"),
        binding_id=_require_string(data.get("binding_id"), "binding_id"),
        schema_version=data.get("schema_version", DEPARTMENT_SKILL_SCHEMA_VERSION),
        skill_id=_require_string(data.get("skill_id"), "skill_id"),
        skill_source=_require_string(data.get("skill_source"), "skill_source"),
        version_constraint=_string_value(
            data.get("version_constraint", ""), "version_constraint"
        ),
        state=data.get("state", DepartmentSkillBindingState.RECOMMENDED),
        visibility=data.get(
            "visibility", DepartmentSkillBindingVisibility.PRIVATE_TO_DEPARTMENT
        ),
        sensitivity=data.get("sensitivity", DepartmentSkillBindingSensitivity.LOW),
        usage_guidance=_require_string(data.get("usage_guidance"), "usage_guidance"),
        applicability=_string_tuple(data.get("applicability", ()), "applicability"),
        disabled_conditions=_string_tuple(
            data.get("disabled_conditions", ()), "disabled_conditions"
        ),
        limitations=_string_tuple(data.get("limitations", ()), "limitations"),
        risk_notes=_string_tuple(data.get("risk_notes", ()), "risk_notes"),
        tool_assumptions=_string_tuple(
            data.get("tool_assumptions", ()), "tool_assumptions"
        ),
        owner=_string_value(data.get("owner", ""), "owner"),
        source_refs=_string_tuple(data.get("source_refs", ()), "source_refs"),
        revision=data.get("revision", 1),
        active=data.get("active", True),
        accepted_at=_optional_string(data.get("accepted_at"), "accepted_at"),
        created_at=_optional_string(data.get("created_at"), "created_at"),
        updated_at=_optional_string(data.get("updated_at"), "updated_at"),
        audit_summary=_string_value(data.get("audit_summary", ""), "audit_summary"),
        replacement_skill_id=_optional_string(
            data.get("replacement_skill_id"), "replacement_skill_id"
        ),
    )


def department_skill_proposal_to_dict(
    proposal: DepartmentSkillBindingProposal,
) -> dict[str, Any]:
    """Return a deterministic JSON-ready department skill proposal."""

    return {
        "proposal_id": proposal.proposal_id,
        "department_id": proposal.department_id,
        "schema_version": proposal.schema_version,
        "proposed_action": proposal.proposed_action.value,
        "skill_id": proposal.skill_id,
        "skill_source": proposal.skill_source,
        "version_constraint": proposal.version_constraint,
        "candidate_state": proposal.candidate_state.value,
        "candidate_guidance": proposal.candidate_guidance,
        "source_actor": proposal.source_actor,
        "source_refs": list(proposal.source_refs),
        "rationale": proposal.rationale,
        "source_hash": proposal.source_hash,
        "visibility": proposal.visibility.value,
        "sensitivity": proposal.sensitivity.value,
        "applicability": list(proposal.applicability),
        "disabled_conditions": list(proposal.disabled_conditions),
        "limitations": list(proposal.limitations),
        "risk_notes": list(proposal.risk_notes),
        "tool_assumptions": list(proposal.tool_assumptions),
        "owner": proposal.owner,
        "review_requirement": proposal.review_requirement,
        "state": proposal.state.value,
        "created_at": proposal.created_at,
        "updated_at": proposal.updated_at,
        "audit_summary": proposal.audit_summary,
        "replacement_skill_id": proposal.replacement_skill_id,
    }


def department_skill_proposal_from_dict(
    data: Mapping[str, Any],
) -> DepartmentSkillBindingProposal:
    """Load a department skill proposal after boundary validation."""

    data = _require_mapping(data, "department skill proposal")
    _reject_unknown_fields(data, _PROPOSAL_FIELDS, "department skill proposal")
    return DepartmentSkillBindingProposal(
        proposal_id=_require_string(data.get("proposal_id"), "proposal_id"),
        department_id=_require_string(data.get("department_id"), "department_id"),
        schema_version=data.get("schema_version", DEPARTMENT_SKILL_SCHEMA_VERSION),
        proposed_action=_require_string(data.get("proposed_action"), "proposed_action"),
        skill_id=_require_string(data.get("skill_id"), "skill_id"),
        skill_source=_require_string(data.get("skill_source"), "skill_source"),
        version_constraint=_string_value(
            data.get("version_constraint", ""), "version_constraint"
        ),
        candidate_state=data.get("candidate_state", DepartmentSkillBindingState.RECOMMENDED),
        candidate_guidance=_require_string(
            data.get("candidate_guidance"), "candidate_guidance"
        ),
        source_actor=_require_string(data.get("source_actor"), "source_actor"),
        source_refs=_string_tuple(data.get("source_refs", ()), "source_refs"),
        rationale=_string_value(data.get("rationale", ""), "rationale"),
        source_hash=_optional_string(data.get("source_hash"), "source_hash"),
        visibility=data.get(
            "visibility", DepartmentSkillBindingVisibility.PRIVATE_TO_DEPARTMENT
        ),
        sensitivity=data.get("sensitivity", DepartmentSkillBindingSensitivity.INTERNAL),
        applicability=_string_tuple(data.get("applicability", ()), "applicability"),
        disabled_conditions=_string_tuple(
            data.get("disabled_conditions", ()), "disabled_conditions"
        ),
        limitations=_string_tuple(data.get("limitations", ()), "limitations"),
        risk_notes=_string_tuple(data.get("risk_notes", ()), "risk_notes"),
        tool_assumptions=_string_tuple(
            data.get("tool_assumptions", ()), "tool_assumptions"
        ),
        owner=_string_value(data.get("owner", ""), "owner"),
        review_requirement=_require_string(
            data.get("review_requirement"), "review_requirement"
        ),
        state=data.get("state", DepartmentSkillProposalState.PENDING),
        created_at=_optional_string(data.get("created_at"), "created_at"),
        updated_at=_optional_string(data.get("updated_at"), "updated_at"),
        audit_summary=_string_value(data.get("audit_summary", ""), "audit_summary"),
        replacement_skill_id=_optional_string(
            data.get("replacement_skill_id"), "replacement_skill_id"
        ),
    )


_BINDING_FIELDS = {
    "department_id",
    "binding_id",
    "schema_version",
    "skill_id",
    "skill_source",
    "version_constraint",
    "state",
    "visibility",
    "sensitivity",
    "usage_guidance",
    "applicability",
    "disabled_conditions",
    "limitations",
    "risk_notes",
    "tool_assumptions",
    "owner",
    "source_refs",
    "revision",
    "active",
    "accepted_at",
    "created_at",
    "updated_at",
    "audit_summary",
    "replacement_skill_id",
}

_PROPOSAL_FIELDS = {
    "proposal_id",
    "department_id",
    "schema_version",
    "proposed_action",
    "skill_id",
    "skill_source",
    "version_constraint",
    "candidate_state",
    "candidate_guidance",
    "source_actor",
    "source_refs",
    "rationale",
    "source_hash",
    "visibility",
    "sensitivity",
    "applicability",
    "disabled_conditions",
    "limitations",
    "risk_notes",
    "tool_assumptions",
    "owner",
    "review_requirement",
    "state",
    "created_at",
    "updated_at",
    "audit_summary",
    "replacement_skill_id",
}


def _require_schema_version(schema_version: int) -> None:
    if schema_version != DEPARTMENT_SKILL_SCHEMA_VERSION:
        raise DepartmentSkillError(
            f"Unsupported department skill schema_version: {schema_version!r}"
        )


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise DepartmentSkillError(f"{field_name} must be a non-empty string")
    return value


def _string_value(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise DepartmentSkillError(f"{field_name} must be a string")
    return value


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, field_name)


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise DepartmentSkillError(f"{field_name} must be a list of strings")
    return tuple(_require_string(item, field_name) for item in value)


def _coerce_string_tuple(instance: object, field_name: str) -> None:
    object.__setattr__(
        instance,
        field_name,
        tuple(_require_string(item, field_name) for item in getattr(instance, field_name)),
    )


def _require_positive_int(value: Any, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DepartmentSkillError(f"{field_name} must be a positive integer")


def _validate_identifier(value: str, field_name: str) -> str:
    _require_string(value, field_name)
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise DepartmentSkillError(f"{field_name} must be a single path segment")
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
        raise DepartmentSkillError(f"{field_name} must stay within allowed storage")
    return value


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DepartmentSkillError(f"{field_name} must be an object")
    return value


def _reject_unknown_fields(
    data: Mapping[str, Any], allowed_fields: set[str], field_name: str
) -> None:
    unknown_fields = sorted(set(data) - allowed_fields)
    if unknown_fields:
        joined = ", ".join(unknown_fields)
        raise DepartmentSkillError(f"{field_name} has unknown fields: {joined}")


def _binding_state(value: DepartmentSkillBindingState | str) -> DepartmentSkillBindingState:
    try:
        return (
            value
            if isinstance(value, DepartmentSkillBindingState)
            else DepartmentSkillBindingState(value)
        )
    except ValueError as exc:
        raise DepartmentSkillError(f"Unknown department skill state: {value!r}") from exc


def _binding_visibility(
    value: DepartmentSkillBindingVisibility | str,
) -> DepartmentSkillBindingVisibility:
    try:
        return (
            value
            if isinstance(value, DepartmentSkillBindingVisibility)
            else DepartmentSkillBindingVisibility(value)
        )
    except ValueError as exc:
        raise DepartmentSkillError(
            f"Unknown department skill visibility: {value!r}"
        ) from exc


def _binding_sensitivity(
    value: DepartmentSkillBindingSensitivity | str,
) -> DepartmentSkillBindingSensitivity:
    try:
        return (
            value
            if isinstance(value, DepartmentSkillBindingSensitivity)
            else DepartmentSkillBindingSensitivity(value)
        )
    except ValueError as exc:
        raise DepartmentSkillError(
            f"Unknown department skill sensitivity: {value!r}"
        ) from exc


def _proposal_state(value: DepartmentSkillProposalState | str) -> DepartmentSkillProposalState:
    try:
        return (
            value
            if isinstance(value, DepartmentSkillProposalState)
            else DepartmentSkillProposalState(value)
        )
    except ValueError as exc:
        raise DepartmentSkillError(
            f"Unknown department skill proposal state: {value!r}"
        ) from exc


def _proposal_action(
    value: DepartmentSkillProposalAction | str,
) -> DepartmentSkillProposalAction:
    try:
        return (
            value
            if isinstance(value, DepartmentSkillProposalAction)
            else DepartmentSkillProposalAction(value)
        )
    except ValueError as exc:
        raise DepartmentSkillError(
            f"Unknown department skill proposal action: {value!r}"
        ) from exc


def _reject_sensitive_payload(value: Any, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in _SENSITIVE_FIELD_NAMES:
                raise DepartmentSkillError(f"{path}.{key_text} contains sensitive data")
            _reject_sensitive_payload(item, f"{path}.{key_text}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_sensitive_payload(item, f"{path}[{index}]")

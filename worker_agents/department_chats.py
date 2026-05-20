"""Department chat bindings for managed worker organization nodes."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from .message_router import (
    ChatParticipantKind,
    ChatParticipantRef,
    ChatThreadType,
    WorkerChatThread,
)
from .organization import MAIN_AGENT_ID, OrganizationError, validate_org_node_id
from .profile import WorkerProfileError, validate_worker_id
from .storage.safe_paths import validate_single_path_segment


DEPARTMENT_CHAT_BINDING_SCHEMA_VERSION = 1


class DepartmentChatError(ValueError):
    """Raised when a department chat binding or summary is invalid."""


class DepartmentChatBindingType(StrEnum):
    """Kinds of organization chat bindings."""

    DEPARTMENT_DEFAULT = "department_default"
    TEAM_DEFAULT = "team_default"
    PROJECT = "project"


class DepartmentChatBindingState(StrEnum):
    """Lifecycle state for a chat binding without managing thread history."""

    ACTIVE = "active"
    PENDING_UPDATE = "pending_update"
    CLOSED = "closed"
    ARCHIVED = "archived"


@dataclass(frozen=True)
class DepartmentChatBinding:
    """Low-sensitivity link between an organization node and a chat thread."""

    binding_id: str
    org_node_id: str
    thread_id: str
    binding_type: DepartmentChatBindingType
    state: DepartmentChatBindingState = DepartmentChatBindingState.ACTIVE
    owner_worker_id: str | None = None
    member_worker_ids: tuple[str, ...] = ()
    required_participants: tuple[ChatParticipantRef, ...] = ()
    parent_summary_targets: tuple[str, ...] = ()
    created_at: str | None = None
    updated_at: str | None = None
    revision: int = 0
    audit_summary: str = ""
    schema_version: int = DEPARTMENT_CHAT_BINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_binding_id(self.binding_id, "binding_id")
        _validate_org_id(self.org_node_id, "org_node_id")
        _validate_binding_id(self.thread_id, "thread_id")
        object.__setattr__(
            self, "binding_type", _binding_type(self.binding_type)
        )
        object.__setattr__(self, "state", _binding_state(self.state))
        if self.owner_worker_id is not None:
            _validate_worker(self.owner_worker_id, "owner_worker_id")
        members = _unique_workers(self.member_worker_ids, "member_worker_ids")
        object.__setattr__(self, "member_worker_ids", members)
        participants = tuple(self.required_participants)
        _validate_required_participants(participants)
        object.__setattr__(self, "required_participants", participants)
        targets = _unique_org_ids(
            self.parent_summary_targets, "parent_summary_targets"
        )
        object.__setattr__(self, "parent_summary_targets", targets)
        _optional_string(self.created_at, "created_at")
        _optional_string(self.updated_at, "updated_at")
        _non_negative_int(self.revision, "revision")
        _string_value(self.audit_summary, "audit_summary")
        if self.schema_version != DEPARTMENT_CHAT_BINDING_SCHEMA_VERSION:
            raise DepartmentChatError(
                f"Unsupported department chat schema_version: {self.schema_version!r}"
            )


@dataclass(frozen=True)
class DepartmentChatBindingSummary:
    """Low-sensitivity binding summary safe for UI, audit, and prompt context."""

    binding_id: str
    org_node_id: str
    thread_id: str
    binding_type: DepartmentChatBindingType
    state: DepartmentChatBindingState
    owner_worker_id: str | None
    member_count: int
    parent_summary_target_count: int
    audit_summary: str = ""


_BINDING_FIELDS = {
    "binding_id",
    "schema_version",
    "org_node_id",
    "thread_id",
    "binding_type",
    "state",
    "owner_worker_id",
    "member_worker_ids",
    "required_participants",
    "parent_summary_targets",
    "created_at",
    "updated_at",
    "revision",
    "audit_summary",
}
_PARTICIPANT_FIELDS = {"kind", "participant_id"}


def department_chat_binding_from_dict(
    data: Mapping[str, Any]
) -> DepartmentChatBinding:
    """Load a binding from a strict dictionary contract."""
    data = _require_mapping(data, "department_chat_binding")
    _reject_unknown_fields(data, _BINDING_FIELDS, "department_chat_binding")
    participants = _require_list(
        data.get("required_participants", ()), "required_participants"
    )
    return DepartmentChatBinding(
        binding_id=_require_string(data.get("binding_id"), "binding_id"),
        schema_version=data.get(
            "schema_version", DEPARTMENT_CHAT_BINDING_SCHEMA_VERSION
        ),
        org_node_id=_require_string(data.get("org_node_id"), "org_node_id"),
        thread_id=_require_string(data.get("thread_id"), "thread_id"),
        binding_type=_binding_type(data.get("binding_type")),
        state=_binding_state(data.get("state", DepartmentChatBindingState.ACTIVE)),
        owner_worker_id=_optional_string(
            data.get("owner_worker_id"), "owner_worker_id"
        ),
        member_worker_ids=_string_tuple(
            data.get("member_worker_ids", ()), "member_worker_ids"
        ),
        required_participants=tuple(
            chat_participant_from_dict(participant) for participant in participants
        ),
        parent_summary_targets=_string_tuple(
            data.get("parent_summary_targets", ()), "parent_summary_targets"
        ),
        created_at=_optional_string(data.get("created_at"), "created_at"),
        updated_at=_optional_string(data.get("updated_at"), "updated_at"),
        revision=_non_negative_int(data.get("revision", 0), "revision"),
        audit_summary=_require_string(data.get("audit_summary", ""), "audit_summary"),
    )


def department_chat_binding_to_dict(
    binding: DepartmentChatBinding,
) -> dict[str, Any]:
    """Dump a binding without transcript or private worker assets."""
    return {
        "binding_id": binding.binding_id,
        "schema_version": binding.schema_version,
        "org_node_id": binding.org_node_id,
        "thread_id": binding.thread_id,
        "binding_type": binding.binding_type.value,
        "state": binding.state.value,
        "owner_worker_id": binding.owner_worker_id,
        "member_worker_ids": list(binding.member_worker_ids),
        "required_participants": [
            chat_participant_to_dict(participant)
            for participant in binding.required_participants
        ],
        "parent_summary_targets": list(binding.parent_summary_targets),
        "created_at": binding.created_at,
        "updated_at": binding.updated_at,
        "revision": binding.revision,
        "audit_summary": binding.audit_summary,
    }


def dump_department_chat_binding_json(binding: DepartmentChatBinding) -> str:
    """Dump a binding as stable JSON text."""
    return json.dumps(
        department_chat_binding_to_dict(binding), ensure_ascii=False, indent=2
    )


def load_department_chat_binding_json(payload: str) -> DepartmentChatBinding:
    """Load a binding from JSON text."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise DepartmentChatError(
            f"Invalid department chat binding JSON: {exc.msg}"
        ) from exc
    return department_chat_binding_from_dict(data)


def summarize_department_chat_binding(
    binding: DepartmentChatBinding,
) -> DepartmentChatBindingSummary:
    """Return a low-sensitivity summary for a department chat binding."""
    return DepartmentChatBindingSummary(
        binding_id=binding.binding_id,
        org_node_id=binding.org_node_id,
        thread_id=binding.thread_id,
        binding_type=binding.binding_type,
        state=binding.state,
        owner_worker_id=binding.owner_worker_id,
        member_count=len(binding.member_worker_ids),
        parent_summary_target_count=len(binding.parent_summary_targets),
        audit_summary=binding.audit_summary,
    )


def department_chat_binding_summary_to_dict(
    summary: DepartmentChatBindingSummary,
) -> dict[str, Any]:
    return {
        "binding_id": summary.binding_id,
        "org_node_id": summary.org_node_id,
        "thread_id": summary.thread_id,
        "binding_type": summary.binding_type.value,
        "state": summary.state.value,
        "owner_worker_id": summary.owner_worker_id,
        "member_count": summary.member_count,
        "parent_summary_target_count": summary.parent_summary_target_count,
        "audit_summary": summary.audit_summary,
    }


def required_department_chat_participants(
    user_id: str,
) -> tuple[ChatParticipantRef, ChatParticipantRef]:
    """Return the required user and main-agent participants for group chats."""
    return (
        ChatParticipantRef(ChatParticipantKind.USER, user_id),
        ChatParticipantRef(ChatParticipantKind.MAIN_AGENT, MAIN_AGENT_ID),
    )


def thread_has_required_department_participants(thread: WorkerChatThread) -> bool:
    """Return whether a thread has the user and main-agent participants."""
    kinds = {participant.kind for participant in thread.participants}
    return ChatParticipantKind.USER in kinds and ChatParticipantKind.MAIN_AGENT in kinds


def chat_participant_from_dict(data: Mapping[str, Any]) -> ChatParticipantRef:
    data = _require_mapping(data, "required_participant")
    _reject_unknown_fields(data, _PARTICIPANT_FIELDS, "required_participant")
    return ChatParticipantRef(
        kind=ChatParticipantKind(
            _require_string(data.get("kind"), "participant.kind")
        ),
        participant_id=_require_string(data.get("participant_id"), "participant_id"),
    )


def chat_participant_to_dict(participant: ChatParticipantRef) -> dict[str, Any]:
    return {
        "kind": participant.kind.value,
        "participant_id": participant.participant_id,
    }


def _validate_required_participants(
    participants: tuple[ChatParticipantRef, ...]
) -> None:
    if len(set(participants)) != len(participants):
        raise DepartmentChatError("required_participants must be unique")
    user_count = sum(
        1 for participant in participants if participant.kind == ChatParticipantKind.USER
    )
    main_count = sum(
        1
        for participant in participants
        if participant.kind == ChatParticipantKind.MAIN_AGENT
    )
    if user_count != 1:
        raise DepartmentChatError("department chats require exactly one user")
    if main_count != 1:
        raise DepartmentChatError("department chats require the main agent")
    unsupported = [
        participant.kind.value
        for participant in participants
        if participant.kind
        not in {ChatParticipantKind.USER, ChatParticipantKind.MAIN_AGENT}
    ]
    if unsupported:
        raise DepartmentChatError(
            "required_participants may only include user and main_agent"
        )


def _binding_type(value: DepartmentChatBindingType | str) -> DepartmentChatBindingType:
    if isinstance(value, DepartmentChatBindingType):
        return value
    raw = _require_string(value, "binding_type")
    try:
        return DepartmentChatBindingType(raw)
    except ValueError as exc:
        raise DepartmentChatError(f"Unknown department chat binding type: {raw!r}") from exc


def _binding_state(value: DepartmentChatBindingState | str) -> DepartmentChatBindingState:
    if isinstance(value, DepartmentChatBindingState):
        return value
    raw = _require_string(value, "state")
    try:
        return DepartmentChatBindingState(raw)
    except ValueError as exc:
        raise DepartmentChatError(f"Unknown department chat binding state: {raw!r}") from exc


def _validate_binding_id(value: str, field_name: str) -> str:
    try:
        return validate_single_path_segment(value, field_name)
    except ValueError as exc:
        raise DepartmentChatError(str(exc)) from exc


def _validate_org_id(value: str, field_name: str) -> str:
    try:
        return validate_org_node_id(value)
    except OrganizationError as exc:
        raise DepartmentChatError(f"{field_name} is invalid: {exc}") from exc


def _validate_worker(value: str, field_name: str) -> str:
    try:
        return validate_worker_id(value)
    except WorkerProfileError as exc:
        raise DepartmentChatError(f"{field_name} is invalid: {exc}") from exc


def _unique_workers(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    result = tuple(values)
    for value in result:
        _validate_worker(value, field_name)
    if len(set(result)) != len(result):
        raise DepartmentChatError(f"{field_name} must not contain duplicates")
    return result


def _unique_org_ids(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    result = tuple(values)
    for value in result:
        _validate_org_id(value, field_name)
    if len(set(result)) != len(result):
        raise DepartmentChatError(f"{field_name} must not contain duplicates")
    return result


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DepartmentChatError(f"{field_name} must be an object")
    return value


def _require_list(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise DepartmentChatError(f"{field_name} must be a list")
    return value


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise DepartmentChatError(f"{field_name} must be a string")
    return value


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, field_name)


def _string_value(value: Any, field_name: str) -> str:
    return _require_string(value, field_name)


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise DepartmentChatError(f"{field_name} must be a list of strings")
    result = tuple(value)
    if any(not isinstance(item, str) or not item for item in result):
        raise DepartmentChatError(f"{field_name} must be a list of non-empty strings")
    return result


def _non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DepartmentChatError(f"{field_name} must be a non-negative integer")
    return value


def _reject_unknown_fields(
    data: Mapping[str, Any], allowed_fields: set[str], field_name: str
) -> None:
    unknown_fields = sorted(set(data) - allowed_fields)
    if unknown_fields:
        joined = ", ".join(unknown_fields)
        raise DepartmentChatError(f"{field_name} has unknown fields: {joined}")

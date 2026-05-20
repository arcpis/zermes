"""User-present chat contracts and routing for managed worker agents."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from .organization import MAIN_AGENT_ID, OrganizationError, validate_org_node_id
from .profile import WorkerProfileError, validate_worker_id
from .storage.safe_paths import validate_single_path_segment


MESSAGE_ROUTER_SCHEMA_VERSION = 1


class MessageRouterError(ValueError):
    """Raised when a managed worker chat contract or route is invalid."""


class ChatThreadType(StrEnum):
    """Thread kinds supported by the managed worker message router."""

    DIRECT = "direct"
    ORGANIZATION_GROUP = "organization_group"
    PROJECT_GROUP = "project_group"


class ChatParticipantKind(StrEnum):
    """Kinds of low-sensitivity participants stored in chat contracts."""

    USER = "user"
    MAIN_AGENT = "main_agent"
    WORKER = "worker"
    ORGANIZATION_NODE = "organization_node"


class ChatMessageType(StrEnum):
    """Message envelope types.

    Mention and broadcast are parsed in a later routing layer. Keeping stable
    enum values here lets stored envelopes survive that later expansion.
    """

    NORMAL = "normal"
    SYSTEM = "system"
    APPROVAL_REQUEST = "approval_request"
    SUMMARY = "summary"
    MENTION = "mention"
    BROADCAST = "broadcast"


class MessageDeliveryStatus(StrEnum):
    """Basic delivery states before detailed handled outcomes are added."""

    CREATED = "created"
    DELIVERED = "delivered"
    SEEN = "seen"
    HANDLED = "handled"
    FAILED = "failed"


class MessageVisibility(StrEnum):
    """Visibility levels for low-sensitivity message views."""

    THREAD = "thread"
    MAIN_AGENT = "main_agent"
    TARGETED = "targeted"


@dataclass(frozen=True)
class ChatParticipantRef:
    """Low-sensitivity reference to one chat participant."""

    kind: ChatParticipantKind
    participant_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _participant_kind(self.kind))
        _validate_participant_id(self.kind, self.participant_id)


@dataclass(frozen=True)
class ChatRecipientScope:
    """Low-sensitivity recipient scope for one message envelope."""

    participant_refs: tuple[ChatParticipantRef, ...] = ()
    include_entire_thread: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "participant_refs", tuple(self.participant_refs)
        )
        if not isinstance(self.include_entire_thread, bool):
            raise MessageRouterError("include_entire_thread must be a boolean")
        if not self.include_entire_thread and not self.participant_refs:
            raise MessageRouterError("targeted recipient scope requires participants")


@dataclass(frozen=True)
class WorkerChatThread:
    """Managed chat thread whose participants are low-sensitivity references."""

    thread_id: str
    thread_type: ChatThreadType
    participants: tuple[ChatParticipantRef, ...]
    title: str = ""
    created_at: str | None = None
    updated_at: str | None = None
    main_agent_visible: bool = True
    audit_summary: str = ""
    schema_version: int = MESSAGE_ROUTER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_router_id(self.thread_id, "thread_id")
        object.__setattr__(self, "thread_type", _thread_type(self.thread_type))
        object.__setattr__(self, "participants", tuple(self.participants))
        if not self.participants:
            raise MessageRouterError("participants must not be empty")
        if not isinstance(self.title, str):
            raise MessageRouterError("title must be a string")
        if not isinstance(self.audit_summary, str):
            raise MessageRouterError("audit_summary must be a string")
        if not isinstance(self.main_agent_visible, bool):
            raise MessageRouterError("main_agent_visible must be a boolean")
        _validate_optional_string(self.created_at, "created_at")
        _validate_optional_string(self.updated_at, "updated_at")
        _validate_schema_version(self.schema_version)


@dataclass(frozen=True)
class WorkerMessageEnvelope:
    """Low-sensitivity message envelope routed through a managed thread."""

    message_id: str
    thread_id: str
    sender: ChatParticipantRef
    recipient_scope: ChatRecipientScope = field(default_factory=ChatRecipientScope)
    message_type: ChatMessageType = ChatMessageType.NORMAL
    created_at: str | None = None
    delivery_status: MessageDeliveryStatus = MessageDeliveryStatus.CREATED
    visibility: MessageVisibility = MessageVisibility.THREAD
    body_preview: str = ""
    audit_summary: str = ""
    sensitive_flags: tuple[str, ...] = ()
    schema_version: int = MESSAGE_ROUTER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_router_id(self.message_id, "message_id")
        _validate_router_id(self.thread_id, "thread_id")
        object.__setattr__(self, "message_type", _message_type(self.message_type))
        object.__setattr__(
            self, "delivery_status", _delivery_status(self.delivery_status)
        )
        object.__setattr__(self, "visibility", _visibility(self.visibility))
        object.__setattr__(self, "sensitive_flags", tuple(self.sensitive_flags))
        _validate_optional_string(self.created_at, "created_at")
        _validate_string(self.body_preview, "body_preview")
        _validate_string(self.audit_summary, "audit_summary")
        _validate_string_tuple(self.sensitive_flags, "sensitive_flags")
        _validate_schema_version(self.schema_version)


_PARTICIPANT_FIELDS = {"kind", "participant_id"}
_RECIPIENT_SCOPE_FIELDS = {"participant_refs", "include_entire_thread"}
_THREAD_FIELDS = {
    "thread_id",
    "schema_version",
    "thread_type",
    "participants",
    "title",
    "created_at",
    "updated_at",
    "main_agent_visible",
    "audit_summary",
}
_MESSAGE_FIELDS = {
    "message_id",
    "schema_version",
    "thread_id",
    "sender",
    "recipient_scope",
    "message_type",
    "created_at",
    "delivery_status",
    "visibility",
    "body_preview",
    "audit_summary",
    "sensitive_flags",
}


def chat_participant_from_dict(data: Mapping[str, Any]) -> ChatParticipantRef:
    data = _require_mapping(data, "participant")
    _reject_unknown_fields(data, _PARTICIPANT_FIELDS, "participant")
    return ChatParticipantRef(
        kind=_participant_kind(data.get("kind")),
        participant_id=_require_string(data.get("participant_id"), "participant_id"),
    )


def chat_participant_to_dict(participant: ChatParticipantRef) -> dict[str, Any]:
    return {
        "kind": participant.kind.value,
        "participant_id": participant.participant_id,
    }


def recipient_scope_from_dict(data: Mapping[str, Any] | None) -> ChatRecipientScope:
    if data is None:
        return ChatRecipientScope()
    data = _require_mapping(data, "recipient_scope")
    _reject_unknown_fields(data, _RECIPIENT_SCOPE_FIELDS, "recipient_scope")
    refs = _require_list(data.get("participant_refs", ()), "participant_refs")
    return ChatRecipientScope(
        participant_refs=tuple(chat_participant_from_dict(ref) for ref in refs),
        include_entire_thread=_require_bool(
            data.get("include_entire_thread", True), "include_entire_thread"
        ),
    )


def recipient_scope_to_dict(scope: ChatRecipientScope) -> dict[str, Any]:
    return {
        "participant_refs": [
            chat_participant_to_dict(ref) for ref in scope.participant_refs
        ],
        "include_entire_thread": scope.include_entire_thread,
    }


def chat_thread_from_dict(data: Mapping[str, Any]) -> WorkerChatThread:
    data = _require_mapping(data, "chat_thread")
    _reject_unknown_fields(data, _THREAD_FIELDS, "chat_thread")
    participants = _require_list(data.get("participants"), "participants")
    return WorkerChatThread(
        thread_id=_require_string(data.get("thread_id"), "thread_id"),
        schema_version=data.get(
            "schema_version", MESSAGE_ROUTER_SCHEMA_VERSION
        ),
        thread_type=_thread_type(data.get("thread_type")),
        participants=tuple(
            chat_participant_from_dict(participant) for participant in participants
        ),
        title=_require_string(data.get("title", ""), "title"),
        created_at=_optional_string(data.get("created_at"), "created_at"),
        updated_at=_optional_string(data.get("updated_at"), "updated_at"),
        main_agent_visible=_require_bool(
            data.get("main_agent_visible", True), "main_agent_visible"
        ),
        audit_summary=_require_string(data.get("audit_summary", ""), "audit_summary"),
    )


def chat_thread_to_dict(thread: WorkerChatThread) -> dict[str, Any]:
    return {
        "thread_id": thread.thread_id,
        "schema_version": thread.schema_version,
        "thread_type": thread.thread_type.value,
        "participants": [
            chat_participant_to_dict(participant)
            for participant in thread.participants
        ],
        "title": thread.title,
        "created_at": thread.created_at,
        "updated_at": thread.updated_at,
        "main_agent_visible": thread.main_agent_visible,
        "audit_summary": thread.audit_summary,
    }


def message_envelope_from_dict(data: Mapping[str, Any]) -> WorkerMessageEnvelope:
    data = _require_mapping(data, "message")
    _reject_unknown_fields(data, _MESSAGE_FIELDS, "message")
    return WorkerMessageEnvelope(
        message_id=_require_string(data.get("message_id"), "message_id"),
        schema_version=data.get(
            "schema_version", MESSAGE_ROUTER_SCHEMA_VERSION
        ),
        thread_id=_require_string(data.get("thread_id"), "thread_id"),
        sender=chat_participant_from_dict(_require_mapping(data.get("sender"), "sender")),
        recipient_scope=recipient_scope_from_dict(data.get("recipient_scope")),
        message_type=_message_type(data.get("message_type", ChatMessageType.NORMAL)),
        created_at=_optional_string(data.get("created_at"), "created_at"),
        delivery_status=_delivery_status(
            data.get("delivery_status", MessageDeliveryStatus.CREATED)
        ),
        visibility=_visibility(data.get("visibility", MessageVisibility.THREAD)),
        body_preview=_require_string(data.get("body_preview", ""), "body_preview"),
        audit_summary=_require_string(data.get("audit_summary", ""), "audit_summary"),
        sensitive_flags=_string_tuple(
            data.get("sensitive_flags", ()), "sensitive_flags"
        ),
    )


def message_envelope_to_dict(message: WorkerMessageEnvelope) -> dict[str, Any]:
    return {
        "message_id": message.message_id,
        "schema_version": message.schema_version,
        "thread_id": message.thread_id,
        "sender": chat_participant_to_dict(message.sender),
        "recipient_scope": recipient_scope_to_dict(message.recipient_scope),
        "message_type": message.message_type.value,
        "created_at": message.created_at,
        "delivery_status": message.delivery_status.value,
        "visibility": message.visibility.value,
        "body_preview": message.body_preview,
        "audit_summary": message.audit_summary,
        "sensitive_flags": list(message.sensitive_flags),
    }


def dump_chat_thread_json(thread: WorkerChatThread) -> str:
    return json.dumps(chat_thread_to_dict(thread), ensure_ascii=False, indent=2)


def load_chat_thread_json(payload: str) -> WorkerChatThread:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise MessageRouterError(f"Invalid chat thread JSON: {exc.msg}") from exc
    return chat_thread_from_dict(data)


def dump_message_envelope_json(message: WorkerMessageEnvelope) -> str:
    return json.dumps(message_envelope_to_dict(message), ensure_ascii=False, indent=2)


def load_message_envelope_json(payload: str) -> WorkerMessageEnvelope:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise MessageRouterError(f"Invalid message envelope JSON: {exc.msg}") from exc
    return message_envelope_from_dict(data)


def is_user_present_thread(thread: WorkerChatThread) -> bool:
    """Return whether a thread includes the user participant required by policy."""
    return any(
        participant.kind == ChatParticipantKind.USER for participant in thread.participants
    )


def validate_thread_participants(thread: WorkerChatThread) -> None:
    """Validate user-present direct and group thread membership rules."""
    user_count = _participant_count(thread, ChatParticipantKind.USER)
    main_agent_count = _participant_count(thread, ChatParticipantKind.MAIN_AGENT)
    worker_count = _participant_count(thread, ChatParticipantKind.WORKER)
    org_node_count = _participant_count(thread, ChatParticipantKind.ORGANIZATION_NODE)

    if user_count != 1:
        raise MessageRouterError("chat threads must include exactly one user")
    if len(set(thread.participants)) != len(thread.participants):
        raise MessageRouterError("chat thread participants must be unique")

    if thread.thread_type == ChatThreadType.DIRECT:
        if worker_count != 1:
            raise MessageRouterError("direct threads must include exactly one worker")
        if main_agent_count or org_node_count:
            raise MessageRouterError(
                "direct threads may only contain the user and one worker"
            )
        if not thread.main_agent_visible:
            raise MessageRouterError("direct threads must remain main-agent visible")
        return

    if main_agent_count != 1:
        raise MessageRouterError("group threads must include the main agent")
    if worker_count + org_node_count < 1:
        raise MessageRouterError(
            "group threads must include a worker or organization node"
        )


def validate_message_route(
    thread: WorkerChatThread, message: WorkerMessageEnvelope
) -> None:
    """Validate that a message stays inside a user-present managed thread."""
    validate_thread_participants(thread)
    if message.thread_id != thread.thread_id:
        raise MessageRouterError("message thread_id must match the thread")
    if message.sender not in thread.participants:
        raise MessageRouterError("message sender must be a thread participant")

    thread_participants = set(thread.participants)
    for recipient in message.recipient_scope.participant_refs:
        if recipient not in thread_participants:
            raise MessageRouterError("message recipients must be thread participants")

    if (
        thread.thread_type == ChatThreadType.DIRECT
        and message.sender.kind == ChatParticipantKind.WORKER
    ):
        worker_recipients = [
            recipient
            for recipient in message.recipient_scope.participant_refs
            if recipient.kind == ChatParticipantKind.WORKER
        ]
        if worker_recipients:
            raise MessageRouterError(
                "workers cannot directly route messages to other workers"
            )


def _validate_participant_id(
    kind: ChatParticipantKind, participant_id: str
) -> None:
    if kind == ChatParticipantKind.USER:
        _validate_router_id(participant_id, "participant_id")
    elif kind == ChatParticipantKind.MAIN_AGENT:
        if participant_id != MAIN_AGENT_ID:
            raise MessageRouterError(
                f"main_agent participant_id must be {MAIN_AGENT_ID!r}"
            )
    elif kind == ChatParticipantKind.WORKER:
        try:
            validate_worker_id(participant_id)
        except WorkerProfileError as exc:
            raise MessageRouterError(f"worker participant_id is invalid: {exc}") from exc
    elif kind == ChatParticipantKind.ORGANIZATION_NODE:
        try:
            validate_org_node_id(participant_id)
        except OrganizationError as exc:
            raise MessageRouterError(
                f"organization_node participant_id is invalid: {exc}"
            ) from exc


def _validate_router_id(value: str, field_name: str) -> str:
    try:
        return validate_single_path_segment(value, field_name)
    except ValueError as exc:
        raise MessageRouterError(str(exc)) from exc


def _participant_count(
    thread: WorkerChatThread, kind: ChatParticipantKind
) -> int:
    return sum(1 for participant in thread.participants if participant.kind == kind)


def _thread_type(value: ChatThreadType | str) -> ChatThreadType:
    if isinstance(value, ChatThreadType):
        return value
    raw = _require_string(value, "thread_type")
    try:
        return ChatThreadType(raw)
    except ValueError as exc:
        raise MessageRouterError(f"Unknown chat thread type: {raw!r}") from exc


def _participant_kind(value: ChatParticipantKind | str) -> ChatParticipantKind:
    if isinstance(value, ChatParticipantKind):
        return value
    raw = _require_string(value, "participant.kind")
    try:
        return ChatParticipantKind(raw)
    except ValueError as exc:
        raise MessageRouterError(f"Unknown chat participant kind: {raw!r}") from exc


def _message_type(value: ChatMessageType | str) -> ChatMessageType:
    if isinstance(value, ChatMessageType):
        return value
    raw = _require_string(value, "message_type")
    try:
        return ChatMessageType(raw)
    except ValueError as exc:
        raise MessageRouterError(f"Unknown chat message type: {raw!r}") from exc


def _delivery_status(value: MessageDeliveryStatus | str) -> MessageDeliveryStatus:
    if isinstance(value, MessageDeliveryStatus):
        return value
    raw = _require_string(value, "delivery_status")
    try:
        return MessageDeliveryStatus(raw)
    except ValueError as exc:
        raise MessageRouterError(f"Unknown delivery status: {raw!r}") from exc


def _visibility(value: MessageVisibility | str) -> MessageVisibility:
    if isinstance(value, MessageVisibility):
        return value
    raw = _require_string(value, "visibility")
    try:
        return MessageVisibility(raw)
    except ValueError as exc:
        raise MessageRouterError(f"Unknown message visibility: {raw!r}") from exc


def _validate_schema_version(value: int) -> None:
    if value != MESSAGE_ROUTER_SCHEMA_VERSION:
        raise MessageRouterError(f"Unsupported message schema_version: {value!r}")


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MessageRouterError(f"{field_name} must be an object")
    return value


def _require_list(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise MessageRouterError(f"{field_name} must be a list")
    return value


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise MessageRouterError(f"{field_name} must be a string")
    return value


def _validate_string(value: Any, field_name: str) -> None:
    _require_string(value, field_name)


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, field_name)


def _validate_optional_string(value: Any, field_name: str) -> None:
    _optional_string(value, field_name)


def _require_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise MessageRouterError(f"{field_name} must be a boolean")
    return value


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise MessageRouterError(f"{field_name} must be a list of strings")
    result = tuple(value)
    _validate_string_tuple(result, field_name)
    return result


def _validate_string_tuple(value: tuple[str, ...], field_name: str) -> None:
    if any(not isinstance(item, str) or not item for item in value):
        raise MessageRouterError(f"{field_name} must be a list of non-empty strings")


def _reject_unknown_fields(
    data: Mapping[str, Any], allowed_fields: set[str], field_name: str
) -> None:
    unknown_fields = sorted(set(data) - allowed_fields)
    if unknown_fields:
        joined = ", ".join(unknown_fields)
        raise MessageRouterError(f"{field_name} has unknown fields: {joined}")

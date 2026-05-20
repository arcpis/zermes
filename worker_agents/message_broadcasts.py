"""Broadcast delivery tracking for managed worker chat messages."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .message_router import ChatParticipantKind, ChatParticipantRef, MessageRouterError
from .organization import OrgLeaderKind, OrgNode, OrgNodeType, OrgTree
from .storage.safe_paths import validate_single_path_segment


MESSAGE_BROADCAST_SCHEMA_VERSION = 1


class BroadcastTargetKind(StrEnum):
    """Kinds of recipient scopes supported by managed broadcasts."""

    THREAD = "thread"
    ORGANIZATION_NODE = "organization_node"
    DEPARTMENT = "department"
    TEAM = "team"
    EXPLICIT_WORKERS = "explicit_workers"


class BroadcastImportance(StrEnum):
    """How much follow-up a broadcast may need."""

    INFORMATIONAL = "informational"
    IMPORTANT = "important"
    REQUIRES_ACK = "requires_ack"


class BroadcastDeliveryStatus(StrEnum):
    """Per-recipient broadcast delivery state."""

    DELIVERED = "delivered"
    SEEN = "seen"
    HANDLED = "handled"
    IGNORED = "ignored"
    FAILED = "failed"


@dataclass(frozen=True)
class BroadcastTarget:
    """One requested broadcast target."""

    target_kind: BroadcastTargetKind
    target_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_kind", _target_kind(self.target_kind))
        _validate_broadcast_id(self.target_id, "target_id")


@dataclass(frozen=True)
class BroadcastDeliveryRecord:
    """Tracked broadcast delivery for one worker recipient."""

    delivery_id: str
    message_id: str
    thread_id: str
    target: BroadcastTarget
    recipient: ChatParticipantRef | None
    status: BroadcastDeliveryStatus = BroadcastDeliveryStatus.DELIVERED
    importance: BroadcastImportance = BroadcastImportance.INFORMATIONAL
    created_at: str | None = None
    updated_at: str | None = None
    status_summary: str = ""
    audit_summary: str = ""
    schema_version: int = MESSAGE_BROADCAST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_broadcast_id(self.delivery_id, "delivery_id")
        _validate_broadcast_id(self.message_id, "message_id")
        _validate_broadcast_id(self.thread_id, "thread_id")
        object.__setattr__(self, "status", _delivery_status(self.status))
        object.__setattr__(self, "importance", _importance(self.importance))
        _validate_optional_string(self.created_at, "created_at")
        _validate_optional_string(self.updated_at, "updated_at")
        _validate_string(self.status_summary, "status_summary")
        _validate_string(self.audit_summary, "audit_summary")
        if self.schema_version != MESSAGE_BROADCAST_SCHEMA_VERSION:
            raise MessageRouterError(
                f"Unsupported broadcast schema_version: {self.schema_version!r}"
            )
        if self.status != BroadcastDeliveryStatus.FAILED and self.recipient is None:
            raise MessageRouterError("broadcast delivery requires a recipient")


@dataclass(frozen=True)
class BroadcastDeliveryUpdate:
    """Safe status update for one broadcast delivery."""

    status: BroadcastDeliveryStatus
    actor: ChatParticipantRef
    updated_at: str | None = None
    status_summary: str = ""
    audit_summary: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _delivery_status(self.status))
        _validate_optional_string(self.updated_at, "updated_at")
        _validate_string(self.status_summary, "status_summary")
        _validate_string(self.audit_summary, "audit_summary")


def resolve_broadcast_recipients(
    *,
    target: BroadcastTarget,
    thread_participants: tuple[ChatParticipantRef, ...],
    organization_tree: OrgTree | None = None,
    explicit_worker_ids: tuple[str, ...] = (),
) -> tuple[ChatParticipantRef, ...]:
    """Resolve a broadcast target to recipients already allowed by the thread."""
    thread_workers = {
        participant.participant_id: participant
        for participant in thread_participants
        if participant.kind == ChatParticipantKind.WORKER
    }
    if target.target_kind == BroadcastTargetKind.THREAD:
        return tuple(thread_workers.values())
    if target.target_kind == BroadcastTargetKind.EXPLICIT_WORKERS:
        return tuple(_require_thread_worker(worker_id, thread_workers) for worker_id in explicit_worker_ids)
    if organization_tree is None:
        return ()
    node = organization_tree.nodes.get(target.target_id)
    if node is None or node.node_type not in _allowed_node_types(target.target_kind):
        return ()
    leader_id = _worker_leader_id(node)
    if leader_id is None:
        return ()
    if leader_id not in thread_workers:
        raise MessageRouterError("broadcast recipient must be a thread participant")
    return (thread_workers[leader_id],)


def create_broadcast_delivery_records(
    *,
    message_id: str,
    thread_id: str,
    target: BroadcastTarget,
    recipients: tuple[ChatParticipantRef, ...],
    importance: BroadcastImportance = BroadcastImportance.INFORMATIONAL,
    created_at: str | None = None,
) -> tuple[BroadcastDeliveryRecord, ...]:
    """Create low-sensitivity delivery records for broadcast recipients."""
    if not recipients:
        return (
            BroadcastDeliveryRecord(
                delivery_id=f"{message_id}-broadcast-1",
                message_id=message_id,
                thread_id=thread_id,
                target=target,
                recipient=None,
                status=BroadcastDeliveryStatus.FAILED,
                importance=importance,
                created_at=created_at,
                updated_at=created_at,
                status_summary="broadcast target had no routable recipients",
                audit_summary="Broadcast could not be routed to a thread participant.",
            ),
        )
    return tuple(
        BroadcastDeliveryRecord(
            delivery_id=f"{message_id}-broadcast-{index + 1}",
            message_id=message_id,
            thread_id=thread_id,
            target=target,
            recipient=recipient,
            importance=importance,
            created_at=created_at,
            audit_summary="Broadcast delivered for low-sensitivity context sync.",
        )
        for index, recipient in enumerate(recipients)
    )


def update_broadcast_delivery_record(
    record: BroadcastDeliveryRecord, update: BroadcastDeliveryUpdate
) -> BroadcastDeliveryRecord:
    """Return a broadcast delivery with an authorized status update applied."""
    _validate_broadcast_status_actor(record, update.actor)
    return BroadcastDeliveryRecord(
        delivery_id=record.delivery_id,
        message_id=record.message_id,
        thread_id=record.thread_id,
        target=record.target,
        recipient=record.recipient,
        status=update.status,
        importance=record.importance,
        created_at=record.created_at,
        updated_at=update.updated_at,
        status_summary=update.status_summary,
        audit_summary=update.audit_summary,
    )


def broadcast_delivery_record_to_dict(
    record: BroadcastDeliveryRecord,
) -> dict[str, Any]:
    """Return a stable low-sensitivity broadcast delivery representation."""
    return {
        "delivery_id": record.delivery_id,
        "message_id": record.message_id,
        "thread_id": record.thread_id,
        "schema_version": record.schema_version,
        "target": {
            "target_kind": record.target.target_kind.value,
            "target_id": record.target.target_id,
        },
        "recipient": _participant_to_dict(record.recipient),
        "status": record.status.value,
        "importance": record.importance.value,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "status_summary": record.status_summary,
        "audit_summary": record.audit_summary,
    }


def _require_thread_worker(
    worker_id: str, thread_workers: dict[str, ChatParticipantRef]
) -> ChatParticipantRef:
    try:
        return thread_workers[worker_id]
    except KeyError as exc:
        raise MessageRouterError("broadcast recipient must be a thread participant") from exc


def _worker_leader_id(node: OrgNode) -> str | None:
    if node.leader.kind == OrgLeaderKind.WORKER:
        return node.leader.worker_id
    return None


def _allowed_node_types(kind: BroadcastTargetKind) -> set[OrgNodeType]:
    if kind == BroadcastTargetKind.DEPARTMENT:
        return {OrgNodeType.DEPARTMENT}
    if kind == BroadcastTargetKind.TEAM:
        return {OrgNodeType.TEAM}
    if kind == BroadcastTargetKind.ORGANIZATION_NODE:
        return {OrgNodeType.ROOT, OrgNodeType.DEPARTMENT, OrgNodeType.TEAM}
    return set()


def _validate_broadcast_status_actor(
    record: BroadcastDeliveryRecord, actor: ChatParticipantRef
) -> None:
    if actor.kind == ChatParticipantKind.MAIN_AGENT:
        return
    if record.recipient is not None and actor == record.recipient:
        return
    raise MessageRouterError("actor cannot update this broadcast delivery")


def _target_kind(value: BroadcastTargetKind | str) -> BroadcastTargetKind:
    if isinstance(value, BroadcastTargetKind):
        return value
    try:
        return BroadcastTargetKind(value)
    except ValueError as exc:
        raise MessageRouterError(f"Unknown broadcast target kind: {value!r}") from exc


def _delivery_status(
    value: BroadcastDeliveryStatus | str,
) -> BroadcastDeliveryStatus:
    if isinstance(value, BroadcastDeliveryStatus):
        return value
    try:
        return BroadcastDeliveryStatus(value)
    except ValueError as exc:
        raise MessageRouterError(
            f"Unknown broadcast delivery status: {value!r}"
        ) from exc


def _importance(value: BroadcastImportance | str) -> BroadcastImportance:
    if isinstance(value, BroadcastImportance):
        return value
    try:
        return BroadcastImportance(value)
    except ValueError as exc:
        raise MessageRouterError(f"Unknown broadcast importance: {value!r}") from exc


def _validate_broadcast_id(value: str, field_name: str) -> str:
    try:
        return validate_single_path_segment(value, field_name)
    except ValueError as exc:
        raise MessageRouterError(str(exc)) from exc


def _validate_optional_string(value: Any, field_name: str) -> None:
    if value is not None:
        _validate_string(value, field_name)


def _validate_string(value: Any, field_name: str) -> None:
    if not isinstance(value, str):
        raise MessageRouterError(f"{field_name} must be a string")


def _participant_to_dict(participant: ChatParticipantRef | None) -> dict[str, str] | None:
    if participant is None:
        return None
    return {
        "kind": participant.kind.value,
        "participant_id": participant.participant_id,
    }


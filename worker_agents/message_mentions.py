"""Mention target resolution for managed worker chat messages."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

from .message_router import ChatParticipantKind, ChatParticipantRef, MessageRouterError
from .organization import (
    OrgLeaderKind,
    OrgLifecycleState,
    OrgNode,
    OrgNodeType,
    OrgTree,
    validate_org_node_id,
)
from .profile import WorkerProfileError, validate_worker_id
from .registry import WorkerLifecycleStatus
from .storage.safe_paths import validate_single_path_segment


MESSAGE_MENTION_SCHEMA_VERSION = 1
_INACTIVE_WORKER_STATUSES = {
    WorkerLifecycleStatus.ARCHIVED.value,
    WorkerLifecycleStatus.DELETED.value,
}
_INACTIVE_ORG_NODE_STATES = {
    OrgLifecycleState.ARCHIVED,
}


class MentionTargetKind(StrEnum):
    """Kinds of targets that can be mentioned in managed chat."""

    WORKER = "worker"
    ORGANIZATION_NODE = "organization_node"
    DEPARTMENT = "department"
    TEAM = "team"


class MentionResolutionStatus(StrEnum):
    """Resolution outcome for one mention target."""

    RESOLVED = "resolved"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    INACTIVE = "inactive"
    MISSING_OWNER = "missing_owner"
    INVALID = "invalid"


class MentionDeliveryStatus(StrEnum):
    """Per-recipient handling state for one mention delivery."""

    PENDING = "pending"
    SEEN = "seen"
    PUBLIC_REPLIED = "public_replied"
    SILENT_ACK = "silent_ack"
    NO_RESPONSE_NEEDED = "no_response_needed"
    REJECTED = "rejected"
    DELEGATED = "delegated"
    DEFERRED = "deferred"
    INTERNAL_TODO = "internal_todo"
    TIMED_OUT = "timed_out"
    FAILED = "failed"


_MENTION_TERMINAL_STATUSES = {
    MentionDeliveryStatus.PUBLIC_REPLIED,
    MentionDeliveryStatus.SILENT_ACK,
    MentionDeliveryStatus.NO_RESPONSE_NEEDED,
    MentionDeliveryStatus.REJECTED,
    MentionDeliveryStatus.DELEGATED,
    MentionDeliveryStatus.TIMED_OUT,
    MentionDeliveryStatus.FAILED,
}


@dataclass(frozen=True)
class MentionTarget:
    """One requested mention target before routing."""

    raw_target: str
    target_kind: MentionTargetKind | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.raw_target, str) or not self.raw_target.strip():
            raise MessageRouterError("mention raw_target must be a non-empty string")
        if self.target_kind is not None:
            object.__setattr__(self, "target_kind", _target_kind(self.target_kind))


@dataclass(frozen=True)
class MentionResolvedTarget:
    """Low-sensitivity result of resolving one mention target."""

    raw_target: str
    status: MentionResolutionStatus
    requested_kind: MentionTargetKind | None = None
    matched_kind: MentionTargetKind | None = None
    mentioned_ref: ChatParticipantRef | None = None
    recipient_ref: ChatParticipantRef | None = None
    routed_via_org_node_id: str | None = None
    display_label: str = ""
    failure_reason: str = ""
    schema_version: int = MESSAGE_MENTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _resolution_status(self.status))
        if self.requested_kind is not None:
            object.__setattr__(
                self, "requested_kind", _target_kind(self.requested_kind)
            )
        if self.matched_kind is not None:
            object.__setattr__(self, "matched_kind", _target_kind(self.matched_kind))
        if self.schema_version != MESSAGE_MENTION_SCHEMA_VERSION:
            raise MessageRouterError(
                f"Unsupported mention schema_version: {self.schema_version!r}"
            )


@dataclass(frozen=True)
class MentionDeliveryRecord:
    """Tracked delivery and handling state for one resolved mention target."""

    delivery_id: str
    message_id: str
    thread_id: str
    mentioned_target: MentionResolvedTarget
    resolved_recipient: ChatParticipantRef | None
    status: MentionDeliveryStatus = MentionDeliveryStatus.PENDING
    created_at: str | None = None
    updated_at: str | None = None
    deadline_at: str | None = None
    reply_message_id: str | None = None
    delegated_to: ChatParticipantRef | None = None
    status_summary: str = ""
    audit_summary: str = ""
    schema_version: int = MESSAGE_MENTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_mention_id(self.delivery_id, "delivery_id")
        _validate_mention_id(self.message_id, "message_id")
        _validate_mention_id(self.thread_id, "thread_id")
        object.__setattr__(self, "status", _delivery_status(self.status))
        _validate_optional_string(self.created_at, "created_at")
        _validate_optional_string(self.updated_at, "updated_at")
        _validate_optional_string(self.deadline_at, "deadline_at")
        _validate_optional_string(self.reply_message_id, "reply_message_id")
        _validate_string(self.status_summary, "status_summary")
        _validate_string(self.audit_summary, "audit_summary")
        if self.schema_version != MESSAGE_MENTION_SCHEMA_VERSION:
            raise MessageRouterError(
                f"Unsupported mention schema_version: {self.schema_version!r}"
            )
        if self.status == MentionDeliveryStatus.PUBLIC_REPLIED:
            _validate_mention_id(
                _require_string(self.reply_message_id, "reply_message_id"),
                "reply_message_id",
            )
        if self.status == MentionDeliveryStatus.DELEGATED and self.delegated_to is None:
            raise MessageRouterError("delegated mention status requires delegated_to")
        if self.status == MentionDeliveryStatus.PENDING and self.resolved_recipient is None:
            raise MessageRouterError("pending mention delivery requires a recipient")


@dataclass(frozen=True)
class MentionDeliveryUpdate:
    """Safe status update payload for one mention delivery."""

    status: MentionDeliveryStatus
    actor: ChatParticipantRef
    updated_at: str | None = None
    status_summary: str = ""
    audit_summary: str = ""
    reply_message_id: str | None = None
    delegated_to: ChatParticipantRef | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _delivery_status(self.status))
        _validate_optional_string(self.updated_at, "updated_at")
        _validate_optional_string(self.reply_message_id, "reply_message_id")
        _validate_string(self.status_summary, "status_summary")
        _validate_string(self.audit_summary, "audit_summary")


def create_mention_delivery_record(
    *,
    delivery_id: str,
    message_id: str,
    thread_id: str,
    mentioned_target: MentionResolvedTarget,
    created_at: str | None = None,
    deadline_at: str | None = None,
) -> MentionDeliveryRecord:
    """Create one delivery record from a resolution result."""
    if (
        mentioned_target.status == MentionResolutionStatus.RESOLVED
        and mentioned_target.recipient_ref is not None
    ):
        return MentionDeliveryRecord(
            delivery_id=delivery_id,
            message_id=message_id,
            thread_id=thread_id,
            mentioned_target=mentioned_target,
            resolved_recipient=mentioned_target.recipient_ref,
            status=MentionDeliveryStatus.PENDING,
            created_at=created_at,
            deadline_at=deadline_at,
            audit_summary="Mention target resolved and queued for handling.",
        )
    return MentionDeliveryRecord(
        delivery_id=delivery_id,
        message_id=message_id,
        thread_id=thread_id,
        mentioned_target=mentioned_target,
        resolved_recipient=None,
        status=MentionDeliveryStatus.FAILED,
        created_at=created_at,
        updated_at=created_at,
        status_summary=mentioned_target.failure_reason,
        audit_summary="Mention target could not be routed.",
    )


def update_mention_delivery_record(
    record: MentionDeliveryRecord, update: MentionDeliveryUpdate
) -> MentionDeliveryRecord:
    """Return a mention delivery with an authorized status update applied."""
    _validate_mention_status_actor(record, update.actor)
    return MentionDeliveryRecord(
        delivery_id=record.delivery_id,
        message_id=record.message_id,
        thread_id=record.thread_id,
        mentioned_target=record.mentioned_target,
        resolved_recipient=record.resolved_recipient,
        status=update.status,
        created_at=record.created_at,
        updated_at=update.updated_at,
        deadline_at=record.deadline_at,
        reply_message_id=update.reply_message_id,
        delegated_to=update.delegated_to,
        status_summary=update.status_summary,
        audit_summary=update.audit_summary,
    )


def is_mention_delivery_open(record: MentionDeliveryRecord) -> bool:
    """Return whether a delivery still needs handling or follow-up."""
    return record.status not in _MENTION_TERMINAL_STATUSES


def mention_delivery_record_to_dict(record: MentionDeliveryRecord) -> dict[str, Any]:
    """Return a stable low-sensitivity mention delivery representation."""
    return {
        "delivery_id": record.delivery_id,
        "message_id": record.message_id,
        "thread_id": record.thread_id,
        "schema_version": record.schema_version,
        "mentioned_target": mention_resolved_target_to_dict(record.mentioned_target),
        "resolved_recipient": _participant_to_dict(record.resolved_recipient),
        "status": record.status.value,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "deadline_at": record.deadline_at,
        "reply_message_id": record.reply_message_id,
        "delegated_to": _participant_to_dict(record.delegated_to),
        "status_summary": record.status_summary,
        "audit_summary": record.audit_summary,
    }


def resolve_mention_targets(
    targets: tuple[MentionTarget | str, ...] | list[MentionTarget | str],
    *,
    organization_tree: OrgTree | None = None,
    worker_lookup: Mapping[str, Any] | set[str] | None = None,
) -> tuple[MentionResolvedTarget, ...]:
    """Resolve requested mention targets without creating messages or tasks."""
    return tuple(
        resolve_mention_target(
            target,
            organization_tree=organization_tree,
            worker_lookup=worker_lookup,
        )
        for target in targets
    )


def resolve_mention_target(
    target: MentionTarget | str,
    *,
    organization_tree: OrgTree | None = None,
    worker_lookup: Mapping[str, Any] | set[str] | None = None,
) -> MentionResolvedTarget:
    """Resolve one worker or organization mention to its routed recipient."""
    mention_target = target if isinstance(target, MentionTarget) else MentionTarget(target)
    raw = mention_target.raw_target
    try:
        label = _normalize_target_label(raw)
    except MessageRouterError as exc:
        return _failed(raw, MentionResolutionStatus.INVALID, str(exc), mention_target)

    if mention_target.target_kind in {None, MentionTargetKind.WORKER}:
        worker = _resolve_worker(label, worker_lookup)
        if worker is not None:
            return worker
        if mention_target.target_kind == MentionTargetKind.WORKER:
            return _failed(
                raw,
                MentionResolutionStatus.NOT_FOUND,
                "worker mention target was not found",
                mention_target,
            )

    if organization_tree is None:
        return _failed(
            raw,
            MentionResolutionStatus.NOT_FOUND,
            "organization mention target was not found",
            mention_target,
        )
    return _resolve_org_node(label, mention_target, organization_tree)


def mention_resolved_target_to_dict(
    resolved: MentionResolvedTarget,
) -> dict[str, Any]:
    """Return a stable low-sensitivity representation of a resolution result."""
    return {
        "raw_target": resolved.raw_target,
        "schema_version": resolved.schema_version,
        "status": resolved.status.value,
        "requested_kind": resolved.requested_kind.value
        if resolved.requested_kind is not None
        else None,
        "matched_kind": resolved.matched_kind.value
        if resolved.matched_kind is not None
        else None,
        "mentioned_ref": _participant_to_dict(resolved.mentioned_ref),
        "recipient_ref": _participant_to_dict(resolved.recipient_ref),
        "routed_via_org_node_id": resolved.routed_via_org_node_id,
        "display_label": resolved.display_label,
        "failure_reason": resolved.failure_reason,
    }


def _resolve_worker(
    label: str, worker_lookup: Mapping[str, Any] | set[str] | None
) -> MentionResolvedTarget | None:
    try:
        worker_id = validate_worker_id(label)
    except WorkerProfileError:
        return None
    if worker_lookup is not None:
        worker_record = _lookup_worker(worker_id, worker_lookup)
        if worker_record is None or worker_record is False:
            return None
        status = _worker_status_value(worker_record)
        if status in _INACTIVE_WORKER_STATUSES:
            return MentionResolvedTarget(
                raw_target=label,
                status=MentionResolutionStatus.INACTIVE,
                requested_kind=MentionTargetKind.WORKER,
                matched_kind=MentionTargetKind.WORKER,
                mentioned_ref=ChatParticipantRef(ChatParticipantKind.WORKER, worker_id),
                display_label=worker_id,
                failure_reason="worker is archived or deleted",
            )
    worker_ref = ChatParticipantRef(ChatParticipantKind.WORKER, worker_id)
    return MentionResolvedTarget(
        raw_target=label,
        status=MentionResolutionStatus.RESOLVED,
        requested_kind=MentionTargetKind.WORKER,
        matched_kind=MentionTargetKind.WORKER,
        mentioned_ref=worker_ref,
        recipient_ref=worker_ref,
        display_label=worker_id,
    )


def _resolve_org_node(
    label: str, target: MentionTarget, tree: OrgTree
) -> MentionResolvedTarget:
    matches = _matching_org_nodes(label, target.target_kind, tree)
    if not matches:
        return _failed(
            target.raw_target,
            MentionResolutionStatus.NOT_FOUND,
            "organization mention target was not found",
            target,
        )
    if len(matches) > 1:
        return _failed(
            target.raw_target,
            MentionResolutionStatus.AMBIGUOUS,
            "organization mention target matched more than one node",
            target,
        )
    node = matches[0]
    matched_kind = _node_target_kind(node)
    mentioned_ref = ChatParticipantRef(
        ChatParticipantKind.ORGANIZATION_NODE, node.org_node_id
    )
    if node.lifecycle in _INACTIVE_ORG_NODE_STATES:
        return MentionResolvedTarget(
            raw_target=target.raw_target,
            status=MentionResolutionStatus.INACTIVE,
            requested_kind=target.target_kind,
            matched_kind=matched_kind,
            mentioned_ref=mentioned_ref,
            routed_via_org_node_id=node.org_node_id,
            display_label=node.name,
            failure_reason="organization node is archived",
        )
    if node.leader.kind != OrgLeaderKind.WORKER or node.leader.worker_id is None:
        return MentionResolvedTarget(
            raw_target=target.raw_target,
            status=MentionResolutionStatus.MISSING_OWNER,
            requested_kind=target.target_kind,
            matched_kind=matched_kind,
            mentioned_ref=mentioned_ref,
            routed_via_org_node_id=node.org_node_id,
            display_label=node.name,
            failure_reason="organization mention requires a worker leader",
        )
    return MentionResolvedTarget(
        raw_target=target.raw_target,
        status=MentionResolutionStatus.RESOLVED,
        requested_kind=target.target_kind,
        matched_kind=matched_kind,
        mentioned_ref=mentioned_ref,
        recipient_ref=ChatParticipantRef(
            ChatParticipantKind.WORKER, node.leader.worker_id
        ),
        routed_via_org_node_id=node.org_node_id,
        display_label=node.name,
    )


def _matching_org_nodes(
    label: str, requested_kind: MentionTargetKind | None, tree: OrgTree
) -> list[OrgNode]:
    allowed_types = _allowed_node_types(requested_kind)
    exact_id_matches = [
        node
        for node in tree.nodes.values()
        if node.org_node_id == label and node.node_type in allowed_types
    ]
    if exact_id_matches:
        return exact_id_matches
    label_fold = label.casefold()
    return [
        node
        for node in tree.nodes.values()
        if node.name.casefold() == label_fold and node.node_type in allowed_types
    ]


def _allowed_node_types(kind: MentionTargetKind | None) -> set[OrgNodeType]:
    if kind == MentionTargetKind.DEPARTMENT:
        return {OrgNodeType.DEPARTMENT}
    if kind == MentionTargetKind.TEAM:
        return {OrgNodeType.TEAM}
    if kind == MentionTargetKind.WORKER:
        return set()
    return {OrgNodeType.ROOT, OrgNodeType.DEPARTMENT, OrgNodeType.TEAM}


def _node_target_kind(node: OrgNode) -> MentionTargetKind:
    if node.node_type == OrgNodeType.DEPARTMENT:
        return MentionTargetKind.DEPARTMENT
    if node.node_type == OrgNodeType.TEAM:
        return MentionTargetKind.TEAM
    return MentionTargetKind.ORGANIZATION_NODE


def _normalize_target_label(raw_target: str) -> str:
    label = raw_target.strip()
    if label.startswith("@"):
        label = label[1:].strip()
    if not label:
        raise MessageRouterError("mention target must not be empty")
    if any(ord(char) < 32 for char in label):
        raise MessageRouterError("mention target must not contain control characters")
    if "/" in label or "\\" in label:
        raise MessageRouterError("mention target must not contain path separators")
    return label


def _lookup_worker(worker_id: str, worker_lookup: Mapping[str, Any] | set[str]) -> Any:
    if isinstance(worker_lookup, set):
        return True if worker_id in worker_lookup else None
    return worker_lookup.get(worker_id)


def _worker_status_value(worker_record: Any) -> str | None:
    if isinstance(worker_record, WorkerLifecycleStatus):
        return worker_record.value
    if isinstance(worker_record, str):
        return worker_record or None
    status = getattr(worker_record, "status", None)
    if isinstance(status, WorkerLifecycleStatus):
        return status.value
    if isinstance(status, str):
        return status
    if isinstance(worker_record, Mapping):
        raw_status = worker_record.get("status")
        if isinstance(raw_status, WorkerLifecycleStatus):
            return raw_status.value
        if isinstance(raw_status, str):
            return raw_status
    return None


def _failed(
    raw_target: str,
    status: MentionResolutionStatus,
    reason: str,
    target: MentionTarget,
) -> MentionResolvedTarget:
    return MentionResolvedTarget(
        raw_target=raw_target,
        status=status,
        requested_kind=target.target_kind,
        display_label=raw_target.lstrip("@").strip(),
        failure_reason=reason,
    )


def _validate_mention_status_actor(
    record: MentionDeliveryRecord, actor: ChatParticipantRef
) -> None:
    if actor.kind == ChatParticipantKind.MAIN_AGENT:
        return
    if record.resolved_recipient is not None and actor == record.resolved_recipient:
        return
    raise MessageRouterError("actor cannot update this mention delivery")


def _delivery_status(value: MentionDeliveryStatus | str) -> MentionDeliveryStatus:
    if isinstance(value, MentionDeliveryStatus):
        return value
    try:
        return MentionDeliveryStatus(value)
    except ValueError as exc:
        raise MessageRouterError(
            f"Unknown mention delivery status: {value!r}"
        ) from exc


def _validate_mention_id(value: str, field_name: str) -> str:
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


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise MessageRouterError(f"{field_name} must be a non-empty string")
    return value


def _target_kind(value: MentionTargetKind | str) -> MentionTargetKind:
    if isinstance(value, MentionTargetKind):
        return value
    try:
        return MentionTargetKind(value)
    except ValueError as exc:
        raise MessageRouterError(f"Unknown mention target kind: {value!r}") from exc


def _resolution_status(
    value: MentionResolutionStatus | str,
) -> MentionResolutionStatus:
    if isinstance(value, MentionResolutionStatus):
        return value
    try:
        return MentionResolutionStatus(value)
    except ValueError as exc:
        raise MessageRouterError(
            f"Unknown mention resolution status: {value!r}"
        ) from exc


def _participant_to_dict(participant: ChatParticipantRef | None) -> dict[str, str] | None:
    if participant is None:
        return None
    return {
        "kind": participant.kind.value,
        "participant_id": participant.participant_id,
    }

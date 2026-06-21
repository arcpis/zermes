"""Follow-up summaries for mention and broadcast delivery tracking."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .message_broadcasts import (
    BroadcastDeliveryRecord,
    BroadcastDeliveryStatus,
    BroadcastImportance,
)
from .message_mentions import (
    MentionDeliveryRecord,
    MentionDeliveryStatus,
    MentionDeliveryUpdate,
    update_mention_delivery_record,
)
from .message_router import ChatParticipantKind, ChatParticipantRef, MessageRouterError


class FollowUpKind(StrEnum):
    """Kinds of items the main agent may need to review."""

    MENTION_OPEN = "mention_open"
    MENTION_TIMED_OUT = "mention_timed_out"
    MENTION_FAILED = "mention_failed"
    MENTION_DELEGATED = "mention_delegated"
    MENTION_DEFERRED = "mention_deferred"
    BROADCAST_IMPORTANT = "broadcast_important"


@dataclass(frozen=True)
class MentionTimeoutPolicy:
    """Conservative timeout settings for mention follow-up scans."""

    policy_id: str = "default"
    mention_default_timeout_seconds: int = 3600
    deferred_grace_seconds: int = 3600
    important_broadcast_review_seconds: int = 3600
    enabled: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.policy_id, str) or not self.policy_id:
            raise MessageRouterError("policy_id must be a non-empty string")
        _validate_non_negative_int(
            self.mention_default_timeout_seconds,
            "mention_default_timeout_seconds",
        )
        _validate_non_negative_int(
            self.deferred_grace_seconds, "deferred_grace_seconds"
        )
        _validate_non_negative_int(
            self.important_broadcast_review_seconds,
            "important_broadcast_review_seconds",
        )
        if not isinstance(self.enabled, bool):
            raise MessageRouterError("enabled must be a boolean")


@dataclass(frozen=True)
class DeliveryFollowUpSummary:
    """Low-sensitivity summary for one delivery requiring main-agent review."""

    follow_up_kind: FollowUpKind
    thread_id: str
    message_id: str
    delivery_id: str
    target_summary: str
    status: str
    created_at: str | None = None
    updated_at: str | None = None
    reason: str = ""
    audit_summary: str = ""


def apply_mention_timeouts(
    records: tuple[MentionDeliveryRecord, ...],
    *,
    now: str,
    policy: MentionTimeoutPolicy | None = None,
) -> tuple[MentionDeliveryRecord, ...]:
    """Return mention deliveries with eligible open records marked timed out."""
    timeout_policy = policy or MentionTimeoutPolicy()
    if not timeout_policy.enabled:
        return records
    main_agent = ChatParticipantRef(ChatParticipantKind.MAIN_AGENT, "zermes_main_agent")
    updated_records: list[MentionDeliveryRecord] = []
    for record in records:
        if _mention_should_time_out(record, now):
            updated_records.append(
                update_mention_delivery_record(
                    record,
                    MentionDeliveryUpdate(
                        status=MentionDeliveryStatus.TIMED_OUT,
                        actor=main_agent,
                        updated_at=now,
                        status_summary="Mention delivery timed out before handling.",
                        audit_summary="Main agent timeout scan marked the mention.",
                    ),
                )
            )
        else:
            updated_records.append(record)
    return tuple(updated_records)


def summarize_delivery_followups(
    *,
    mention_deliveries: tuple[MentionDeliveryRecord, ...] = (),
    broadcast_deliveries: tuple[BroadcastDeliveryRecord, ...] = (),
) -> tuple[DeliveryFollowUpSummary, ...]:
    """Summarize mention and broadcast deliveries that need review."""
    summaries: list[DeliveryFollowUpSummary] = []
    summaries.extend(_summarize_mentions(mention_deliveries))
    summaries.extend(_summarize_broadcasts(broadcast_deliveries))
    return tuple(summaries)


def _summarize_mentions(
    records: tuple[MentionDeliveryRecord, ...]
) -> tuple[DeliveryFollowUpSummary, ...]:
    summaries: list[DeliveryFollowUpSummary] = []
    for record in records:
        kind = _mention_follow_up_kind(record)
        if kind is None:
            continue
        summaries.append(
            DeliveryFollowUpSummary(
                follow_up_kind=kind,
                thread_id=record.thread_id,
                message_id=record.message_id,
                delivery_id=record.delivery_id,
                target_summary=_mention_target_summary(record),
                status=record.status.value,
                created_at=record.created_at,
                updated_at=record.updated_at,
                reason=record.status_summary,
                audit_summary=record.audit_summary,
            )
        )
    return tuple(summaries)


def _summarize_broadcasts(
    records: tuple[BroadcastDeliveryRecord, ...]
) -> tuple[DeliveryFollowUpSummary, ...]:
    summaries: list[DeliveryFollowUpSummary] = []
    for record in records:
        if record.importance == BroadcastImportance.INFORMATIONAL:
            continue
        if record.status in {
            BroadcastDeliveryStatus.HANDLED,
            BroadcastDeliveryStatus.IGNORED,
            BroadcastDeliveryStatus.FAILED,
        }:
            continue
        summaries.append(
            DeliveryFollowUpSummary(
                follow_up_kind=FollowUpKind.BROADCAST_IMPORTANT,
                thread_id=record.thread_id,
                message_id=record.message_id,
                delivery_id=record.delivery_id,
                target_summary=record.target.target_id,
                status=record.status.value,
                created_at=record.created_at,
                updated_at=record.updated_at,
                reason=record.status_summary,
                audit_summary=record.audit_summary,
            )
        )
    return tuple(summaries)


def _mention_follow_up_kind(
    record: MentionDeliveryRecord,
) -> FollowUpKind | None:
    if record.status == MentionDeliveryStatus.PENDING:
        return FollowUpKind.MENTION_OPEN
    if record.status == MentionDeliveryStatus.SEEN:
        return FollowUpKind.MENTION_OPEN
    if record.status == MentionDeliveryStatus.INTERNAL_TODO:
        return FollowUpKind.MENTION_OPEN
    if record.status == MentionDeliveryStatus.TIMED_OUT:
        return FollowUpKind.MENTION_TIMED_OUT
    if record.status == MentionDeliveryStatus.FAILED:
        return FollowUpKind.MENTION_FAILED
    if record.status == MentionDeliveryStatus.DELEGATED:
        return FollowUpKind.MENTION_DELEGATED
    if record.status == MentionDeliveryStatus.DEFERRED:
        return FollowUpKind.MENTION_DEFERRED
    return None


def _mention_should_time_out(record: MentionDeliveryRecord, now: str) -> bool:
    if record.deadline_at is None:
        return False
    if record.status not in {
        MentionDeliveryStatus.PENDING,
        MentionDeliveryStatus.SEEN,
        MentionDeliveryStatus.INTERNAL_TODO,
    }:
        return False
    return record.deadline_at <= now


def _mention_target_summary(record: MentionDeliveryRecord) -> str:
    target = record.mentioned_target
    if target.display_label:
        return target.display_label
    if target.recipient_ref is not None:
        return target.recipient_ref.participant_id
    if record.resolved_recipient is not None:
        return record.resolved_recipient.participant_id
    return target.raw_target


def _validate_non_negative_int(value: Any, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MessageRouterError(f"{field_name} must be a non-negative integer")


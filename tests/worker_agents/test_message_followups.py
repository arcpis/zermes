from worker_agents.message_broadcasts import (
    BroadcastImportance,
    BroadcastTarget,
    BroadcastTargetKind,
)
from worker_agents.message_followups import (
    FollowUpKind,
    MentionTimeoutPolicy,
)
from worker_agents.message_mentions import (
    MentionDeliveryStatus,
    MentionDeliveryUpdate,
    resolve_mention_targets,
)
from worker_agents.message_router import (
    ChatMessageType,
    ChatParticipantKind,
    ChatParticipantRef,
    MessageRouter,
    WorkerMessageEnvelope,
)
from worker_agents.registry import WorkerLifecycleStatus


def _router_with_frontend_mention(deadline_at: str = "2026-05-20T00:30:00Z"):
    router = MessageRouter()
    router.create_group_thread(
        thread_id="thread-1",
        user_id="user",
        worker_ids=("frontend",),
    )
    records = router.append_mention_message(
        message=WorkerMessageEnvelope(
            message_id="message-1",
            thread_id="thread-1",
            sender=ChatParticipantRef(ChatParticipantKind.USER, "user"),
            message_type=ChatMessageType.MENTION,
            created_at="2026-05-20T00:00:00Z",
        ),
        resolved_targets=resolve_mention_targets(
            ("frontend",), worker_lookup={"frontend": WorkerLifecycleStatus.ENABLED}
        ),
        deadline_at=deadline_at,
    )
    return router, records[0]


def test_pending_mention_times_out_after_deadline():
    router, record = _router_with_frontend_mention()

    updated = router.apply_mention_timeouts(
        thread_id="thread-1", now="2026-05-20T00:31:00Z"
    )

    assert updated[0].delivery_id == record.delivery_id
    assert updated[0].status == MentionDeliveryStatus.TIMED_OUT
    assert updated[0].updated_at == "2026-05-20T00:31:00Z"


def test_timeout_scan_is_idempotent():
    router, _ = _router_with_frontend_mention()

    first = router.apply_mention_timeouts(
        thread_id="thread-1", now="2026-05-20T00:31:00Z"
    )
    second = router.apply_mention_timeouts(
        thread_id="thread-1", now="2026-05-20T00:32:00Z"
    )

    assert first[0].status == MentionDeliveryStatus.TIMED_OUT
    assert second[0].status == MentionDeliveryStatus.TIMED_OUT
    assert second[0].updated_at == first[0].updated_at


def test_deferred_mention_is_summarized_but_not_timed_out():
    router, record = _router_with_frontend_mention()
    router.update_mention_delivery_status(
        thread_id="thread-1",
        delivery_id=record.delivery_id,
        update=MentionDeliveryUpdate(
            status=MentionDeliveryStatus.DEFERRED,
            actor=ChatParticipantRef(ChatParticipantKind.WORKER, "frontend"),
            updated_at="2026-05-20T00:10:00Z",
            status_summary="Will revisit after design review.",
        ),
    )

    router.apply_mention_timeouts(thread_id="thread-1", now="2026-05-20T00:31:00Z")
    summaries = router.summarize_delivery_followups(thread_id="thread-1")

    assert summaries[0].follow_up_kind == FollowUpKind.MENTION_DEFERRED
    assert summaries[0].reason == "Will revisit after design review."


def test_internal_todo_enters_followup_without_creating_task():
    router, record = _router_with_frontend_mention(deadline_at="2026-05-20T02:00:00Z")
    router.update_mention_delivery_status(
        thread_id="thread-1",
        delivery_id=record.delivery_id,
        update=MentionDeliveryUpdate(
            status=MentionDeliveryStatus.INTERNAL_TODO,
            actor=ChatParticipantRef(ChatParticipantKind.WORKER, "frontend"),
            status_summary="Track locally before replying.",
        ),
    )

    summaries = router.summarize_delivery_followups(thread_id="thread-1")

    assert len(summaries) == 1
    assert summaries[0].follow_up_kind == FollowUpKind.MENTION_OPEN
    assert summaries[0].status == MentionDeliveryStatus.INTERNAL_TODO.value


def test_informational_broadcast_without_seen_does_not_need_followup():
    router = MessageRouter()
    router.create_group_thread(
        thread_id="thread-1",
        user_id="user",
        worker_ids=("frontend",),
    )
    router.append_broadcast_message(
        message=WorkerMessageEnvelope(
            message_id="message-1",
            thread_id="thread-1",
            sender=ChatParticipantRef(ChatParticipantKind.USER, "user"),
            message_type=ChatMessageType.BROADCAST,
        ),
        target=BroadcastTarget(BroadcastTargetKind.THREAD, "thread-1"),
        importance=BroadcastImportance.INFORMATIONAL,
    )

    assert router.summarize_delivery_followups(thread_id="thread-1") == ()


def test_important_broadcast_enters_main_agent_summary():
    router = MessageRouter()
    router.create_group_thread(
        thread_id="thread-1",
        user_id="user",
        worker_ids=("frontend",),
    )
    router.append_broadcast_message(
        message=WorkerMessageEnvelope(
            message_id="message-1",
            thread_id="thread-1",
            sender=ChatParticipantRef(ChatParticipantKind.USER, "user"),
            message_type=ChatMessageType.BROADCAST,
            audit_summary="Important low-sensitivity decision.",
        ),
        target=BroadcastTarget(BroadcastTargetKind.THREAD, "thread-1"),
        importance=BroadcastImportance.IMPORTANT,
    )

    summaries = router.summarize_delivery_followups(thread_id="thread-1")

    assert len(summaries) == 1
    assert summaries[0].follow_up_kind == FollowUpKind.BROADCAST_IMPORTANT
    assert summaries[0].audit_summary == "Broadcast delivered for low-sensitivity context sync."


def test_timeout_policy_validates_non_negative_values():
    try:
        MentionTimeoutPolicy(mention_default_timeout_seconds=-1)
    except ValueError as exc:
        assert "non-negative" in str(exc)
    else:
        raise AssertionError("negative timeout should be rejected")

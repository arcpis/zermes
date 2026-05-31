import pytest

from worker_agents.message_router import (
    ChatParticipantKind,
    ChatParticipantRef,
    ChatRecipientScope,
    ChatThreadType,
    MessageDeliveryStatus,
    MessageRouter,
    MessageRouterError,
    WorkerChatThread,
    WorkerMessageEnvelope,
)


def _user():
    return ChatParticipantRef(ChatParticipantKind.USER, "user")


def _main_agent():
    return ChatParticipantRef(ChatParticipantKind.MAIN_AGENT, "zermes_main_agent")


def _worker(worker_id):
    return ChatParticipantRef(ChatParticipantKind.WORKER, worker_id)


def test_router_creates_direct_thread_and_appends_message():
    router = MessageRouter()
    thread = router.create_direct_thread(
        thread_id="direct-1",
        user_id="user",
        worker_id="frontend",
        title="Frontend",
    )
    message = WorkerMessageEnvelope(
        message_id="message-1",
        thread_id="direct-1",
        sender=_user(),
        body_preview="Please inspect this component.",
        audit_summary="User asked frontend to inspect a component.",
    )

    stored = router.append_message(message)

    assert thread.thread_type == ChatThreadType.DIRECT
    assert router.get_thread_messages("direct-1") == (stored,)


def test_router_creates_group_thread_and_appends_message():
    router = MessageRouter()
    router.create_group_thread(
        thread_id="group-1",
        user_id="user",
        worker_ids=("frontend", "backend"),
        title="Project",
    )
    message = WorkerMessageEnvelope(
        message_id="message-1",
        thread_id="group-1",
        sender=_main_agent(),
        body_preview="User approved the implementation direction.",
        audit_summary="Main agent synchronized user approval.",
    )

    router.append_message(message)

    assert len(router.get_thread_messages("group-1")) == 1


def test_router_rejects_invalid_thread_creation():
    router = MessageRouter()
    thread = WorkerChatThread(
        thread_id="hidden",
        thread_type=ChatThreadType.ORGANIZATION_GROUP,
        participants=(_main_agent(), _worker("frontend")),
    )

    with pytest.raises(MessageRouterError, match="exactly one user"):
        router.add_thread(thread)


def test_router_updates_delivery_status():
    router = MessageRouter()
    router.create_direct_thread(
        thread_id="direct-1", user_id="user", worker_id="frontend"
    )
    router.append_message(
        WorkerMessageEnvelope(
            message_id="message-1",
            thread_id="direct-1",
            sender=_user(),
        )
    )

    updated = router.update_delivery_status(
        thread_id="direct-1",
        message_id="message-1",
        delivery_status=MessageDeliveryStatus.SEEN,
    )

    assert updated.delivery_status == MessageDeliveryStatus.SEEN
    assert router.get_thread_messages("direct-1")[0].delivery_status == (
        MessageDeliveryStatus.SEEN
    )


def test_router_rejects_unknown_delivery_status_update():
    router = MessageRouter()
    router.create_direct_thread(
        thread_id="direct-1", user_id="user", worker_id="frontend"
    )
    router.append_message(
        WorkerMessageEnvelope(
            message_id="message-1",
            thread_id="direct-1",
            sender=_user(),
        )
    )

    with pytest.raises(MessageRouterError, match="delivery status"):
        router.update_delivery_status(
            thread_id="direct-1",
            message_id="message-1",
            delivery_status="queued",
        )


def test_worker_views_only_include_messages_routed_to_worker():
    router = MessageRouter()
    router.create_group_thread(
        thread_id="group-1",
        user_id="user",
        worker_ids=("frontend", "backend"),
    )
    router.append_message(
        WorkerMessageEnvelope(
            message_id="message-all",
            thread_id="group-1",
            sender=_user(),
            body_preview="Shared context.",
            audit_summary="Visible to whole thread.",
        )
    )
    router.append_message(
        WorkerMessageEnvelope(
            message_id="message-frontend",
            thread_id="group-1",
            sender=_user(),
            recipient_scope=ChatRecipientScope(
                participant_refs=(_worker("frontend"),),
                include_entire_thread=False,
            ),
            body_preview="Frontend-only context.",
            audit_summary="Visible to frontend worker.",
        )
    )
    router.append_message(
        WorkerMessageEnvelope(
            message_id="message-backend",
            thread_id="group-1",
            sender=_user(),
            recipient_scope=ChatRecipientScope(
                participant_refs=(_worker("backend"),),
                include_entire_thread=False,
            ),
            body_preview="Backend-only context.",
            audit_summary="Visible to backend worker.",
        )
    )

    views = router.get_worker_message_views(thread_id="group-1", worker_id="frontend")

    assert [view.message_id for view in views] == [
        "message-all",
        "message-frontend",
    ]
    assert views[1].body_preview == "Frontend-only context."


def test_worker_view_rejects_non_participant_worker():
    router = MessageRouter()
    router.create_group_thread(
        thread_id="group-1",
        user_id="user",
        worker_ids=("frontend",),
    )

    with pytest.raises(MessageRouterError, match="thread participant"):
        router.get_worker_message_views(thread_id="group-1", worker_id="backend")


def test_router_does_not_call_runtime_adapter_or_executor():
    router = MessageRouter()
    router.create_direct_thread(
        thread_id="direct-1", user_id="user", worker_id="frontend"
    )

    assert not hasattr(router, "adapter")
    assert not hasattr(router, "executor")

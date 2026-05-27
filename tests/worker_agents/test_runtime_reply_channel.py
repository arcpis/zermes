import json

import pytest

from worker_agents.message_router import (
    ChatParticipantRef,
    MessageRouter,
    WorkerMessageEnvelope,
)
from worker_agents.runtime_contract import RuntimeResult, RuntimeState, RuntimeType
from worker_agents.runtime_reply_channel import (
    build_runtime_request_from_chat_message,
    dispatch_chat_message_to_worker_runtime,
    target_worker_ids_for_chat_message,
)


def _result(request, *, public_message="Runtime reply"):
    return RuntimeResult(
        request_id=request.request_id,
        task_id=request.task_id,
        worker_id=request.worker_id,
        runtime_type=RuntimeType.INTERNAL_WORKER,
        final_state=RuntimeState.SUCCEEDED,
        started_at=request.created_at,
        completed_at="2026-05-27T00:01:00Z",
        public_message=public_message,
        internal_summary="raw runtime transcript should stay out of chat history",
    )


def test_chat_message_builds_low_sensitive_runtime_request():
    router = MessageRouter()
    thread = router.create_group_thread(
        thread_id="dept-engineering",
        user_id="user",
        worker_ids=("worker-a", "worker-b"),
        organization_node_ids=("engineering",),
    )
    message = router.append_message(
        WorkerMessageEnvelope(
            message_id="msg-123",
            thread_id="dept-engineering",
            sender=ChatParticipantRef("user", "user"),
            body_preview="Please review the deployment plan.",
        )
    )

    request = build_runtime_request_from_chat_message(
        thread=thread,
        source_message=message,
        target_worker_id="worker-a",
        created_at="2026-05-27T00:00:00Z",
    )

    payload = json.dumps(request.context.__dict__)
    assert request.worker_id == "worker-a"
    assert request.context.source_thread_id == "dept-engineering"
    assert request.context.source_message_refs == (
        "worker_agents/threads/dept-engineering/messages/msg-123",
    )
    assert request.context.input_message == "Please review the deployment plan."
    assert "raw_transcript" not in payload


def test_dispatch_routes_public_reply_to_source_thread():
    router = MessageRouter()
    thread = router.create_direct_thread(
        thread_id="direct-user-worker-a",
        user_id="user",
        worker_id="worker-a",
    )
    message = router.append_message(
        WorkerMessageEnvelope(
            message_id="msg-123",
            thread_id="direct-user-worker-a",
            sender=ChatParticipantRef("user", "user"),
            body_preview="Status?",
        )
    )

    dispatch = dispatch_chat_message_to_worker_runtime(
        router=router,
        thread=thread,
        source_message=message,
        target_worker_id="worker-a",
        reply_handler=_result,
        created_at="2026-05-27T00:00:00Z",
    )

    messages = router.get_thread_messages("direct-user-worker-a")
    assert dispatch.delivered_messages[0].body_preview == "Runtime reply"
    assert [message.body_preview for message in messages] == ["Status?", "Runtime reply"]


def test_runtime_failure_routes_safe_summary_to_thread():
    router = MessageRouter()
    thread = router.create_direct_thread(
        thread_id="direct-user-worker-a",
        user_id="user",
        worker_id="worker-a",
    )
    message = router.append_message(
        WorkerMessageEnvelope(
            message_id="msg-123",
            thread_id="direct-user-worker-a",
            sender=ChatParticipantRef("user", "user"),
            body_preview="Status?",
        )
    )

    def fail(_request):
        raise RuntimeError("raw runtime failure details")

    dispatch = dispatch_chat_message_to_worker_runtime(
        router=router,
        thread=thread,
        source_message=message,
        target_worker_id="worker-a",
        reply_handler=fail,
        created_at="2026-05-27T00:00:00Z",
    )

    assert dispatch.delivered_messages[0].body_preview == (
        "Worker runtime could not produce a reply for this message."
    )


def test_group_message_without_specific_target_does_not_fan_out():
    router = MessageRouter()
    thread = router.create_group_thread(
        thread_id="dept-engineering",
        user_id="user",
        worker_ids=("worker-a", "worker-b"),
    )
    message = router.append_message(
        WorkerMessageEnvelope(
            message_id="msg-123",
            thread_id="dept-engineering",
            sender=ChatParticipantRef("user", "user"),
            body_preview="FYI",
        )
    )

    assert target_worker_ids_for_chat_message(thread, message) == ()


def test_source_message_must_match_thread():
    router = MessageRouter()
    thread = router.create_direct_thread(
        thread_id="direct-user-worker-a",
        user_id="user",
        worker_id="worker-a",
    )
    with pytest.raises(ValueError, match="source message"):
        build_runtime_request_from_chat_message(
            thread=thread,
            source_message=WorkerMessageEnvelope(
                message_id="msg-123",
                thread_id="other-thread",
                sender=ChatParticipantRef("user", "user"),
                body_preview="Status?",
            ),
            target_worker_id="worker-a",
            created_at="2026-05-27T00:00:00Z",
        )

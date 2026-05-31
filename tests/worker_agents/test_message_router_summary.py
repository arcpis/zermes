from worker_agents.message_router import (
    ChatParticipantKind,
    ChatParticipantRef,
    ChatRecipientScope,
    MessageRouter,
    WorkerMessageEnvelope,
    chat_thread_summary_to_dict,
    message_summary_to_dict,
    summarize_chat_thread,
    summarize_message,
)


def _user():
    return ChatParticipantRef(ChatParticipantKind.USER, "user")


def _worker(worker_id):
    return ChatParticipantRef(ChatParticipantKind.WORKER, worker_id)


def test_thread_summary_excludes_private_assets_and_transcripts():
    router = MessageRouter()
    thread = router.create_group_thread(
        thread_id="group-1",
        user_id="user",
        worker_ids=("frontend", "backend"),
        organization_node_ids=("engineering",),
        title="Engineering",
        audit_summary="Low-sensitivity thread audit.",
    )

    summary = summarize_chat_thread(thread)
    data = chat_thread_summary_to_dict(summary)

    assert data["participant_count"] == 5
    assert data["worker_count"] == 2
    assert data["organization_node_count"] == 1
    assert data["audit_summary"] == "Low-sensitivity thread audit."
    assert "raw_transcript" not in data
    assert "private_memory" not in data
    assert "credentials" not in data


def test_message_summary_excludes_raw_transcript_and_credentials():
    message = WorkerMessageEnvelope(
        message_id="message-1",
        thread_id="group-1",
        sender=_user(),
        recipient_scope=ChatRecipientScope(
            participant_refs=(_worker("frontend"),),
            include_entire_thread=False,
        ),
        body_preview="Short routed preview.",
        audit_summary="Low-sensitivity message audit.",
        sensitive_flags=("contains_user_decision",),
    )

    summary = summarize_message(message)
    data = message_summary_to_dict(summary)

    assert data["body_preview"] == "Short routed preview."
    assert data["audit_summary"] == "Low-sensitivity message audit."
    assert data["sensitive_flags"] == ["contains_user_decision"]
    assert "raw_transcript" not in data
    assert "private_memory" not in data
    assert "environment" not in data
    assert "credentials" not in data


def test_router_returns_thread_and_message_summaries():
    router = MessageRouter()
    router.create_direct_thread(
        thread_id="direct-1",
        user_id="user",
        worker_id="frontend",
        title="Frontend",
    )
    router.append_message(
        WorkerMessageEnvelope(
            message_id="message-1",
            thread_id="direct-1",
            sender=_user(),
            body_preview="Please inspect the component.",
            audit_summary="User asked frontend to inspect a component.",
        )
    )

    thread_summary = router.summarize_thread("direct-1")
    message_summaries = router.summarize_thread_messages("direct-1")

    assert thread_summary.thread_id == "direct-1"
    assert thread_summary.worker_count == 1
    assert [summary.message_id for summary in message_summaries] == ["message-1"]

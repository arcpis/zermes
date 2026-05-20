import pytest

from worker_agents.message_router import (
    MESSAGE_ROUTER_SCHEMA_VERSION,
    ChatMessageType,
    ChatParticipantKind,
    ChatParticipantRef,
    ChatRecipientScope,
    ChatThreadType,
    MessageDeliveryStatus,
    MessageRouterError,
    MessageVisibility,
    WorkerChatThread,
    WorkerMessageEnvelope,
    chat_thread_from_dict,
    chat_thread_to_dict,
    dump_chat_thread_json,
    dump_message_envelope_json,
    load_chat_thread_json,
    load_message_envelope_json,
    message_envelope_from_dict,
    message_envelope_to_dict,
)


def _user():
    return ChatParticipantRef(ChatParticipantKind.USER, "user")


def _main_agent():
    return ChatParticipantRef(ChatParticipantKind.MAIN_AGENT, "zermes_main_agent")


def _worker(worker_id="frontend"):
    return ChatParticipantRef(ChatParticipantKind.WORKER, worker_id)


def test_direct_thread_round_trips_through_json():
    thread = WorkerChatThread(
        thread_id="thread-1",
        thread_type=ChatThreadType.DIRECT,
        participants=(_user(), _worker()),
        title="Frontend chat",
        created_at="2026-05-20T00:00:00Z",
        audit_summary="User and frontend worker private chat.",
    )

    loaded = load_chat_thread_json(dump_chat_thread_json(thread))

    assert loaded == thread


@pytest.mark.parametrize("thread_type", list(ChatThreadType))
def test_thread_accepts_supported_thread_types(thread_type):
    thread = WorkerChatThread(
        thread_id=f"{thread_type.value}-thread",
        thread_type=thread_type,
        participants=(_user(), _main_agent(), _worker()),
    )

    assert thread.thread_type == thread_type
    assert thread.schema_version == MESSAGE_ROUTER_SCHEMA_VERSION


@pytest.mark.parametrize(
    "participant",
    [
        ChatParticipantRef(ChatParticipantKind.USER, "user"),
        ChatParticipantRef(ChatParticipantKind.MAIN_AGENT, "zermes_main_agent"),
        ChatParticipantRef(ChatParticipantKind.WORKER, "frontend"),
        ChatParticipantRef(ChatParticipantKind.ORGANIZATION_NODE, "engineering"),
    ],
)
def test_participant_refs_accept_supported_kinds(participant):
    data = chat_thread_to_dict(
        WorkerChatThread(
            thread_id="thread-1",
            thread_type=ChatThreadType.ORGANIZATION_GROUP,
            participants=(participant,),
        )
    )

    assert data["participants"][0]["kind"] == participant.kind.value


@pytest.mark.parametrize("bad_id", ["", ".", "..", "thread/nested", r"thread\nested"])
def test_thread_rejects_path_like_thread_ids(bad_id):
    with pytest.raises(MessageRouterError):
        WorkerChatThread(
            thread_id=bad_id,
            thread_type=ChatThreadType.DIRECT,
            participants=(_user(), _worker()),
        )


def test_main_agent_participant_requires_canonical_id():
    with pytest.raises(MessageRouterError, match="main_agent participant_id"):
        ChatParticipantRef(ChatParticipantKind.MAIN_AGENT, "other_agent")


def test_chat_thread_rejects_unknown_fields():
    with pytest.raises(MessageRouterError, match="unknown fields"):
        chat_thread_from_dict(
            {
                "thread_id": "thread-1",
                "schema_version": MESSAGE_ROUTER_SCHEMA_VERSION,
                "thread_type": "direct",
                "participants": [
                    {"kind": "user", "participant_id": "user"},
                    {"kind": "worker", "participant_id": "frontend"},
                ],
                "raw_transcript": "do not store full transcript here",
            }
        )


def test_message_envelope_round_trips_through_json():
    message = WorkerMessageEnvelope(
        message_id="message-1",
        thread_id="thread-1",
        sender=_user(),
        recipient_scope=ChatRecipientScope(participant_refs=(_worker(),)),
        message_type=ChatMessageType.NORMAL,
        created_at="2026-05-20T00:01:00Z",
        delivery_status=MessageDeliveryStatus.DELIVERED,
        visibility=MessageVisibility.TARGETED,
        body_preview="Please inspect the UI.",
        audit_summary="User asked frontend worker to inspect UI.",
        sensitive_flags=("low_sensitivity_summary",),
    )

    loaded = load_message_envelope_json(dump_message_envelope_json(message))

    assert loaded == message


@pytest.mark.parametrize("status", list(MessageDeliveryStatus))
def test_message_envelope_accepts_supported_delivery_status(status):
    message = WorkerMessageEnvelope(
        message_id=f"message-{status.value}",
        thread_id="thread-1",
        sender=_user(),
        delivery_status=status,
    )

    assert message.delivery_status == status


def test_message_envelope_rejects_unknown_delivery_status():
    with pytest.raises(MessageRouterError, match="delivery status"):
        message_envelope_from_dict(
            {
                "message_id": "message-1",
                "thread_id": "thread-1",
                "sender": {"kind": "user", "participant_id": "user"},
                "delivery_status": "queued",
            }
        )


def test_targeted_recipient_scope_requires_participants():
    with pytest.raises(MessageRouterError, match="targeted"):
        ChatRecipientScope(include_entire_thread=False)


def test_message_dict_keeps_only_summary_fields():
    message = WorkerMessageEnvelope(
        message_id="message-1",
        thread_id="thread-1",
        sender=_user(),
        body_preview="Short preview.",
        audit_summary="Low-sensitivity audit summary.",
    )

    data = message_envelope_to_dict(message)

    assert data["body_preview"] == "Short preview."
    assert data["audit_summary"] == "Low-sensitivity audit summary."
    assert "raw_transcript" not in data
    assert "private_memory" not in data
    assert "credentials" not in data
    assert "environment" not in data

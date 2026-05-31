import pytest

from worker_agents.message_router import (
    ChatParticipantKind,
    ChatParticipantRef,
    ChatRecipientScope,
    ChatThreadType,
    MessageRouterError,
    WorkerChatThread,
    WorkerMessageEnvelope,
    is_user_present_thread,
    validate_message_route,
    validate_thread_participants,
)


def _user():
    return ChatParticipantRef(ChatParticipantKind.USER, "user")


def _main_agent():
    return ChatParticipantRef(ChatParticipantKind.MAIN_AGENT, "zermes_main_agent")


def _worker(worker_id):
    return ChatParticipantRef(ChatParticipantKind.WORKER, worker_id)


def _org_node(node_id="engineering"):
    return ChatParticipantRef(ChatParticipantKind.ORGANIZATION_NODE, node_id)


def test_user_and_worker_direct_thread_passes_policy():
    thread = WorkerChatThread(
        thread_id="direct-1",
        thread_type=ChatThreadType.DIRECT,
        participants=(_user(), _worker("frontend")),
    )

    validate_thread_participants(thread)

    assert is_user_present_thread(thread)


def test_worker_to_worker_direct_thread_is_rejected():
    thread = WorkerChatThread(
        thread_id="direct-1",
        thread_type=ChatThreadType.DIRECT,
        participants=(_worker("frontend"), _worker("backend"), _user()),
    )

    with pytest.raises(MessageRouterError, match="exactly one worker"):
        validate_thread_participants(thread)


def test_direct_thread_without_user_is_rejected():
    thread = WorkerChatThread(
        thread_id="direct-1",
        thread_type=ChatThreadType.DIRECT,
        participants=(_worker("frontend"),),
    )

    with pytest.raises(MessageRouterError, match="exactly one user"):
        validate_thread_participants(thread)


def test_direct_thread_must_remain_main_agent_visible():
    thread = WorkerChatThread(
        thread_id="direct-1",
        thread_type=ChatThreadType.DIRECT,
        participants=(_user(), _worker("frontend")),
        main_agent_visible=False,
    )

    with pytest.raises(MessageRouterError, match="main-agent visible"):
        validate_thread_participants(thread)


def test_group_thread_requires_user_and_main_agent():
    thread = WorkerChatThread(
        thread_id="group-1",
        thread_type=ChatThreadType.ORGANIZATION_GROUP,
        participants=(_user(), _worker("frontend")),
    )

    with pytest.raises(MessageRouterError, match="main agent"):
        validate_thread_participants(thread)


def test_group_thread_requires_worker_or_organization_node():
    thread = WorkerChatThread(
        thread_id="group-1",
        thread_type=ChatThreadType.ORGANIZATION_GROUP,
        participants=(_user(), _main_agent()),
    )

    with pytest.raises(MessageRouterError, match="worker or organization node"):
        validate_thread_participants(thread)


def test_group_thread_allows_organization_node_without_expanding_store():
    thread = WorkerChatThread(
        thread_id="group-1",
        thread_type=ChatThreadType.ORGANIZATION_GROUP,
        participants=(_user(), _main_agent(), _org_node()),
    )

    validate_thread_participants(thread)


def test_message_sender_must_be_thread_participant():
    thread = WorkerChatThread(
        thread_id="group-1",
        thread_type=ChatThreadType.ORGANIZATION_GROUP,
        participants=(_user(), _main_agent(), _worker("frontend")),
    )
    message = WorkerMessageEnvelope(
        message_id="message-1",
        thread_id="group-1",
        sender=_worker("backend"),
    )

    with pytest.raises(MessageRouterError, match="sender"):
        validate_message_route(thread, message)


def test_message_recipient_must_be_thread_participant():
    thread = WorkerChatThread(
        thread_id="group-1",
        thread_type=ChatThreadType.ORGANIZATION_GROUP,
        participants=(_user(), _main_agent(), _worker("frontend")),
    )
    message = WorkerMessageEnvelope(
        message_id="message-1",
        thread_id="group-1",
        sender=_user(),
        recipient_scope=ChatRecipientScope(
            participant_refs=(_worker("backend"),),
            include_entire_thread=False,
        ),
    )

    with pytest.raises(MessageRouterError, match="recipients"):
        validate_message_route(thread, message)


def test_message_thread_id_must_match_thread():
    thread = WorkerChatThread(
        thread_id="group-1",
        thread_type=ChatThreadType.ORGANIZATION_GROUP,
        participants=(_user(), _main_agent(), _worker("frontend")),
    )
    message = WorkerMessageEnvelope(
        message_id="message-1",
        thread_id="group-2",
        sender=_user(),
    )

    with pytest.raises(MessageRouterError, match="thread_id"):
        validate_message_route(thread, message)

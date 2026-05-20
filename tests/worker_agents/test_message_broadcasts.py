import pytest

from worker_agents.message_broadcasts import (
    BroadcastDeliveryStatus,
    BroadcastDeliveryUpdate,
    BroadcastImportance,
    BroadcastTarget,
    BroadcastTargetKind,
)
from worker_agents.message_router import (
    ChatMessageType,
    ChatParticipantKind,
    ChatParticipantRef,
    MessageRouter,
    MessageRouterError,
    WorkerMessageEnvelope,
)
from worker_agents.organization import (
    OrgLeaderKind,
    OrgLeaderRef,
    OrgLifecycleState,
    OrgNode,
    OrgNodeType,
    OrgTree,
)


def _organization_tree() -> OrgTree:
    return OrgTree(
        tree_id="company",
        root_node_id="root",
        nodes={
            "root": OrgNode(
                org_node_id="root",
                name="Root",
                node_type=OrgNodeType.ROOT,
                child_ids=("engineering", "platform"),
                leader=OrgLeaderRef(OrgLeaderKind.MAIN_AGENT),
                lifecycle=OrgLifecycleState.ACTIVE,
            ),
            "engineering": OrgNode(
                org_node_id="engineering",
                name="Engineering",
                node_type=OrgNodeType.DEPARTMENT,
                parent_id="root",
                leader=OrgLeaderRef(OrgLeaderKind.WORKER, "eng_lead"),
                lifecycle=OrgLifecycleState.ACTIVE,
            ),
            "platform": OrgNode(
                org_node_id="platform",
                name="Platform",
                node_type=OrgNodeType.TEAM,
                parent_id="root",
                leader=OrgLeaderRef(OrgLeaderKind.WORKER, "platform_lead"),
                lifecycle=OrgLifecycleState.ACTIVE,
            ),
        },
    )


def _router() -> MessageRouter:
    router = MessageRouter()
    router.create_group_thread(
        thread_id="thread-1",
        user_id="user",
        worker_ids=("eng_lead", "platform_lead"),
    )
    return router


def _broadcast_message(message_id: str = "message-1") -> WorkerMessageEnvelope:
    return WorkerMessageEnvelope(
        message_id=message_id,
        thread_id="thread-1",
        sender=ChatParticipantRef(ChatParticipantKind.USER, "user"),
        message_type=ChatMessageType.BROADCAST,
        created_at="2026-05-20T00:00:00Z",
        body_preview="Decision summary for the team.",
        audit_summary="User broadcast a low-sensitivity decision summary.",
    )


def test_broadcast_to_thread_delivers_to_worker_participants():
    records = _router().append_broadcast_message(
        message=_broadcast_message(),
        target=BroadcastTarget(BroadcastTargetKind.THREAD, "thread-1"),
        importance=BroadcastImportance.INFORMATIONAL,
    )

    assert [record.recipient.participant_id for record in records if record.recipient] == [
        "eng_lead",
        "platform_lead",
    ]
    assert all(record.status == BroadcastDeliveryStatus.DELIVERED for record in records)


def test_broadcast_to_department_delivers_to_thread_participant_leader():
    records = _router().append_broadcast_message(
        message=_broadcast_message(),
        target=BroadcastTarget(BroadcastTargetKind.DEPARTMENT, "engineering"),
        importance=BroadcastImportance.IMPORTANT,
        organization_tree=_organization_tree(),
    )

    assert len(records) == 1
    assert records[0].recipient is not None
    assert records[0].recipient.participant_id == "eng_lead"
    assert records[0].importance == BroadcastImportance.IMPORTANT


def test_broadcast_to_team_delivers_to_team_leader():
    records = _router().append_broadcast_message(
        message=_broadcast_message(),
        target=BroadcastTarget(BroadcastTargetKind.TEAM, "platform"),
        importance=BroadcastImportance.INFORMATIONAL,
        organization_tree=_organization_tree(),
    )

    assert records[0].recipient is not None
    assert records[0].recipient.participant_id == "platform_lead"


def test_broadcast_to_non_participant_worker_is_rejected():
    with pytest.raises(MessageRouterError, match="thread participant"):
        _router().append_broadcast_message(
            message=_broadcast_message(),
            target=BroadcastTarget(BroadcastTargetKind.EXPLICIT_WORKERS, "manual"),
            importance=BroadcastImportance.INFORMATIONAL,
            explicit_worker_ids=("backend",),
        )


def test_broadcast_without_routable_recipient_records_failed_delivery():
    records = _router().append_broadcast_message(
        message=_broadcast_message(),
        target=BroadcastTarget(BroadcastTargetKind.DEPARTMENT, "missing"),
        importance=BroadcastImportance.IMPORTANT,
        organization_tree=_organization_tree(),
    )

    assert len(records) == 1
    assert records[0].status == BroadcastDeliveryStatus.FAILED
    assert records[0].recipient is None


def test_recipient_can_mark_broadcast_seen_without_public_reply():
    router = _router()
    records = router.append_broadcast_message(
        message=_broadcast_message(),
        target=BroadcastTarget(BroadcastTargetKind.DEPARTMENT, "engineering"),
        importance=BroadcastImportance.IMPORTANT,
        organization_tree=_organization_tree(),
    )

    updated = router.update_broadcast_delivery_status(
        thread_id="thread-1",
        delivery_id=records[0].delivery_id,
        update=BroadcastDeliveryUpdate(
            status=BroadcastDeliveryStatus.SEEN,
            actor=ChatParticipantRef(ChatParticipantKind.WORKER, "eng_lead"),
            updated_at="2026-05-20T00:01:00Z",
            status_summary="Seen by department lead.",
        ),
    )

    assert updated.status == BroadcastDeliveryStatus.SEEN
    assert updated.status_summary == "Seen by department lead."


def test_other_worker_cannot_update_broadcast_delivery():
    router = _router()
    records = router.append_broadcast_message(
        message=_broadcast_message(),
        target=BroadcastTarget(BroadcastTargetKind.DEPARTMENT, "engineering"),
        importance=BroadcastImportance.INFORMATIONAL,
        organization_tree=_organization_tree(),
    )

    with pytest.raises(MessageRouterError, match="actor cannot update"):
        router.update_broadcast_delivery_status(
            thread_id="thread-1",
            delivery_id=records[0].delivery_id,
            update=BroadcastDeliveryUpdate(
                status=BroadcastDeliveryStatus.HANDLED,
                actor=ChatParticipantRef(ChatParticipantKind.WORKER, "platform_lead"),
            ),
        )

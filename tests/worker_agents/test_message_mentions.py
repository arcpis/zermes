from worker_agents.message_mentions import (
    MentionDeliveryStatus,
    MentionDeliveryUpdate,
    MentionResolutionStatus,
    MentionTarget,
    MentionTargetKind,
    resolve_mention_targets,
)
from worker_agents.message_router import (
    ChatMessageType,
    ChatParticipantKind,
    ChatParticipantRef,
    ChatRecipientScope,
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
from worker_agents.registry import WorkerLifecycleStatus


def _organization_tree(*, duplicate_team_name: bool = False) -> OrgTree:
    team_name = "Platform"
    nodes = {
        "root": OrgNode(
            org_node_id="root",
            name="Root",
            node_type=OrgNodeType.ROOT,
            child_ids=("engineering", "ops"),
            leader=OrgLeaderRef(OrgLeaderKind.MAIN_AGENT),
            lifecycle=OrgLifecycleState.ACTIVE,
        ),
        "engineering": OrgNode(
            org_node_id="engineering",
            name="Engineering",
            node_type=OrgNodeType.DEPARTMENT,
            parent_id="root",
            child_ids=("platform",),
            leader=OrgLeaderRef(OrgLeaderKind.WORKER, "eng_lead"),
            lifecycle=OrgLifecycleState.ACTIVE,
        ),
        "platform": OrgNode(
            org_node_id="platform",
            name=team_name,
            node_type=OrgNodeType.TEAM,
            parent_id="engineering",
            leader=OrgLeaderRef(OrgLeaderKind.WORKER, "platform_lead"),
            lifecycle=OrgLifecycleState.ACTIVE,
        ),
        "ops": OrgNode(
            org_node_id="ops",
            name=team_name if duplicate_team_name else "Operations",
            node_type=OrgNodeType.DEPARTMENT,
            parent_id="root",
            leader=OrgLeaderRef(),
            lifecycle=OrgLifecycleState.ACTIVE,
        ),
    }
    return OrgTree(tree_id="company", root_node_id="root", nodes=nodes)


def test_resolves_worker_target_with_enabled_registry_record():
    resolved = resolve_mention_targets(
        ("@frontend",),
        worker_lookup={"frontend": {"status": WorkerLifecycleStatus.ENABLED.value}},
    )

    assert resolved[0].status == MentionResolutionStatus.RESOLVED
    assert resolved[0].recipient_ref is not None
    assert resolved[0].recipient_ref.kind == ChatParticipantKind.WORKER
    assert resolved[0].recipient_ref.participant_id == "frontend"


def test_archived_worker_target_is_inactive():
    resolved = resolve_mention_targets(
        ("frontend",),
        worker_lookup={"frontend": WorkerLifecycleStatus.ARCHIVED},
    )

    assert resolved[0].status == MentionResolutionStatus.INACTIVE
    assert resolved[0].failure_reason == "worker is archived or deleted"


def test_resolves_department_to_worker_leader():
    resolved = resolve_mention_targets(
        (MentionTarget("Engineering", MentionTargetKind.DEPARTMENT),),
        organization_tree=_organization_tree(),
    )

    assert resolved[0].status == MentionResolutionStatus.RESOLVED
    assert resolved[0].mentioned_ref is not None
    assert resolved[0].mentioned_ref.participant_id == "engineering"
    assert resolved[0].recipient_ref is not None
    assert resolved[0].recipient_ref.participant_id == "eng_lead"
    assert resolved[0].routed_via_org_node_id == "engineering"


def test_resolves_team_to_worker_leader_by_name():
    resolved = resolve_mention_targets(
        (MentionTarget("@Platform", MentionTargetKind.TEAM),),
        organization_tree=_organization_tree(),
    )

    assert resolved[0].status == MentionResolutionStatus.RESOLVED
    assert resolved[0].recipient_ref is not None
    assert resolved[0].recipient_ref.participant_id == "platform_lead"


def test_org_node_without_worker_leader_reports_missing_owner():
    resolved = resolve_mention_targets(
        (MentionTarget("@Operations", MentionTargetKind.DEPARTMENT),),
        organization_tree=_organization_tree(),
    )

    assert resolved[0].status == MentionResolutionStatus.MISSING_OWNER
    assert "worker leader" in resolved[0].failure_reason


def test_duplicate_org_labels_report_ambiguous_result():
    resolved = resolve_mention_targets(
        ("@Platform",),
        organization_tree=_organization_tree(duplicate_team_name=True),
        worker_lookup=set(),
    )

    assert resolved[0].status == MentionResolutionStatus.AMBIGUOUS


def test_multi_target_resolution_keeps_successes_and_failures():
    resolved = resolve_mention_targets(
        ("@frontend", "@missing", MentionTarget("Engineering")),
        organization_tree=_organization_tree(),
        worker_lookup={"frontend": WorkerLifecycleStatus.ENABLED},
    )

    assert [item.status for item in resolved] == [
        MentionResolutionStatus.RESOLVED,
        MentionResolutionStatus.NOT_FOUND,
        MentionResolutionStatus.RESOLVED,
    ]


def test_invalid_target_is_reported_without_raising():
    resolved = resolve_mention_targets(("@bad/path",))

    assert resolved[0].status == MentionResolutionStatus.INVALID
    assert "path separators" in resolved[0].failure_reason


def test_mention_message_creates_delivery_per_resolved_target():
    router = MessageRouter()
    router.create_group_thread(
        thread_id="thread-1",
        user_id="user",
        worker_ids=("frontend", "eng_lead"),
    )
    resolved = resolve_mention_targets(
        ("@frontend", "@missing"),
        worker_lookup={"frontend": WorkerLifecycleStatus.ENABLED},
    )

    records = router.append_mention_message(
        message=WorkerMessageEnvelope(
            message_id="message-1",
            thread_id="thread-1",
            sender=ChatParticipantRef(ChatParticipantKind.USER, "user"),
            recipient_scope=ChatRecipientScope(
                participant_refs=(
                    ChatParticipantRef(ChatParticipantKind.WORKER, "frontend"),
                ),
                include_entire_thread=False,
            ),
            message_type=ChatMessageType.MENTION,
            created_at="2026-05-20T00:00:00Z",
            body_preview="@frontend please inspect this.",
            audit_summary="User mentioned frontend worker.",
        ),
        resolved_targets=resolved,
        deadline_at="2026-05-20T01:00:00Z",
    )

    assert [record.status for record in records] == [
        MentionDeliveryStatus.PENDING,
        MentionDeliveryStatus.FAILED,
    ]
    assert records[0].resolved_recipient is not None
    assert records[0].resolved_recipient.participant_id == "frontend"
    assert records[1].status_summary == "organization mention target was not found"


def test_recipient_can_update_own_mention_delivery_state():
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
        ),
        resolved_targets=resolve_mention_targets(
            ("frontend",), worker_lookup={"frontend": WorkerLifecycleStatus.ENABLED}
        ),
    )

    updated = router.update_mention_delivery_status(
        thread_id="thread-1",
        delivery_id=records[0].delivery_id,
        update=MentionDeliveryUpdate(
            status=MentionDeliveryStatus.SILENT_ACK,
            actor=ChatParticipantRef(ChatParticipantKind.WORKER, "frontend"),
            updated_at="2026-05-20T00:01:00Z",
            status_summary="Acknowledged without public reply.",
            audit_summary="Frontend worker silently acknowledged the mention.",
        ),
    )

    assert updated.status == MentionDeliveryStatus.SILENT_ACK
    assert updated.status_summary == "Acknowledged without public reply."


def test_main_agent_can_mark_mention_as_delegated():
    router = MessageRouter()
    router.create_group_thread(
        thread_id="thread-1",
        user_id="user",
        worker_ids=("frontend", "backend"),
    )
    records = router.append_mention_message(
        message=WorkerMessageEnvelope(
            message_id="message-1",
            thread_id="thread-1",
            sender=ChatParticipantRef(ChatParticipantKind.USER, "user"),
            message_type=ChatMessageType.MENTION,
        ),
        resolved_targets=resolve_mention_targets(
            ("frontend",), worker_lookup={"frontend": WorkerLifecycleStatus.ENABLED}
        ),
    )

    updated = router.update_mention_delivery_status(
        thread_id="thread-1",
        delivery_id=records[0].delivery_id,
        update=MentionDeliveryUpdate(
            status=MentionDeliveryStatus.DELEGATED,
            actor=ChatParticipantRef(
                ChatParticipantKind.MAIN_AGENT, "zermes_main_agent"
            ),
            delegated_to=ChatParticipantRef(ChatParticipantKind.WORKER, "backend"),
            status_summary="Delegated to backend for API details.",
        ),
    )

    assert updated.status == MentionDeliveryStatus.DELEGATED
    assert updated.delegated_to is not None
    assert updated.delegated_to.participant_id == "backend"


def test_other_worker_cannot_update_mention_delivery():
    router = MessageRouter()
    router.create_group_thread(
        thread_id="thread-1",
        user_id="user",
        worker_ids=("frontend", "backend"),
    )
    records = router.append_mention_message(
        message=WorkerMessageEnvelope(
            message_id="message-1",
            thread_id="thread-1",
            sender=ChatParticipantRef(ChatParticipantKind.USER, "user"),
            message_type=ChatMessageType.MENTION,
        ),
        resolved_targets=resolve_mention_targets(
            ("frontend",), worker_lookup={"frontend": WorkerLifecycleStatus.ENABLED}
        ),
    )

    try:
        router.update_mention_delivery_status(
            thread_id="thread-1",
            delivery_id=records[0].delivery_id,
            update=MentionDeliveryUpdate(
                status=MentionDeliveryStatus.SEEN,
                actor=ChatParticipantRef(ChatParticipantKind.WORKER, "backend"),
            ),
        )
    except MessageRouterError as exc:
        assert "actor cannot update" in str(exc)
    else:
        raise AssertionError("other worker should not update mention delivery")

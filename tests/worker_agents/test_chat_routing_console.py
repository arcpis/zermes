from worker_agents.management import (
    at_message_tracking_item_to_dict,
    broadcast_tracking_item_to_dict,
    build_at_message_tracking_item,
    build_broadcast_tracking_item,
    build_managed_chat_thread_summary,
    build_thread_archive_summary_view,
    filter_at_message_tracking_items,
    managed_chat_thread_summary_to_dict,
    thread_archive_summary_view_to_dict,
)
from worker_agents.message_router import (
    ChatParticipantKind,
    ChatParticipantRef,
    ChatThreadType,
    WorkerChatThread,
)
from worker_agents.organization import MAIN_AGENT_ID


def test_chat_thread_summary_maps_private_department_and_project_threads():
    private = WorkerChatThread(
        thread_id="private-thread",
        thread_type=ChatThreadType.DIRECT,
        participants=(
            ChatParticipantRef(ChatParticipantKind.USER, "user-1"),
            ChatParticipantRef(ChatParticipantKind.WORKER, "worker-a"),
        ),
        main_agent_visible=True,
        audit_summary="latest generated summary",
    )
    department = {
        "thread_id": "department-thread",
        "thread_type": "organization_group",
        "participants": [
            {"kind": "user", "participant_id": "user-1"},
            {"kind": "main_agent", "participant_id": MAIN_AGENT_ID},
            {"kind": "organization_node", "participant_id": "engineering"},
        ],
        "main_agent_visible": True,
        "audit_summary": "department summary",
    }
    project = {
        "thread_id": "project-thread",
        "thread_type": "project_group",
        "participants": [
            {"kind": "user", "participant_id": "user-1"},
            {"kind": "main_agent", "participant_id": MAIN_AGENT_ID},
            {"kind": "worker", "participant_id": "worker-a"},
        ],
        "main_agent_visible": True,
    }

    summaries = [
        build_managed_chat_thread_summary(private),
        build_managed_chat_thread_summary(department),
        build_managed_chat_thread_summary(project),
    ]

    assert [summary.thread_type for summary in summaries] == [
        "private",
        "department",
        "project",
    ]
    assert summaries[0].last_summary == "latest generated summary"


def test_chat_thread_without_user_is_invalid_and_archived_is_read_only():
    summary = build_managed_chat_thread_summary(
        {
            "thread_id": "invalid-thread",
            "thread_type": "organization_group",
            "participants": [
                {"kind": "main_agent", "participant_id": MAIN_AGENT_ID},
                {"kind": "worker", "participant_id": "worker-a"},
            ],
            "main_agent_visible": True,
        },
        status="archived",
        last_summary="raw transcript should be redacted",
    )
    data = managed_chat_thread_summary_to_dict(summary)

    assert data["valid_management_boundary"] is False
    assert data["read_only"] is True
    assert data["last_summary"] == "[redacted summary]"
    assert data["risk_badges"][0]["code"] == "invalid_management_boundary"


def test_at_tracking_marks_timed_out_and_delegated_items():
    item = build_at_message_tracking_item(
        {
            "tracking_id": "mention-1",
            "thread_id": "thread-1",
            "message_id": "message-1",
            "status": "timed_out",
            "target_id": "worker-a",
            "delegated_to": "worker-b",
            "overdue": True,
        }
    )

    data = at_message_tracking_item_to_dict(item)

    assert data["delegated_to"] == "worker-b"
    assert {badge["code"] for badge in data["risk_badges"]} == {
        "delivery_overdue",
        "delivery_delegated",
    }
    assert filter_at_message_tracking_items([item], status="timed_out") == (item,)


def test_broadcast_tracking_does_not_require_all_replies_by_default():
    item = build_broadcast_tracking_item(
        {
            "tracking_id": "broadcast-1",
            "thread_id": "thread-1",
            "message_id": "message-1",
            "status": "completed",
            "target_scope": "department:engineering",
            "recipient_count": 3,
            "acknowledged_count": 1,
        }
    )

    data = broadcast_tracking_item_to_dict(item)

    assert data["status"] == "completed"
    assert data["acknowledged_count"] == 1
    assert data["requires_all_acknowledgement"] is False


def test_thread_archive_summary_blocks_new_tasks_and_keeps_audit_refs():
    frozen = build_thread_archive_summary_view(
        {
            "thread_id": "thread-1",
            "status": "frozen",
            "summary": "safe generated summary",
            "manifest_refs": ["manifests/thread-1.json"],
            "evolution_audit_refs": ["evolution/proposal-1"],
        }
    )
    archived = build_thread_archive_summary_view(
        {
            "thread_id": "thread-2",
            "status": "archived",
            "summary": "raw transcript secret content",
            "archive_actor": "main-agent",
            "archive_reason": "Completed project.",
        }
    )

    frozen_data = thread_archive_summary_view_to_dict(frozen)
    archived_data = thread_archive_summary_view_to_dict(archived)

    assert frozen_data["new_task_entry_enabled"] is False
    assert frozen_data["evolution_audit_refs"] == ["evolution/proposal-1"]
    assert archived_data["read_only"] is True
    assert archived_data["summary"] == "[redacted summary]"

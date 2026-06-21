import json

from zermes.hermes_cli import worker_agents_product as product
from zermes.tools import worker_messaging_tool as messaging
from zermes.tools import worker_task_state as task_state
from zermes.worker_agents.message_router import (
    ChatMessageType,
    ChatParticipantKind,
    ChatParticipantRef,
    ChatRecipientScope,
    MessageDeliveryStatus,
    MessageVisibility,
    WorkerMessageEnvelope,
)
from zermes.worker_agents.runtime_contract import RuntimeResult, RuntimeState, RuntimeType


def _worker(worker_id: str, *, status: str = "enabled") -> dict:
    return {
        "worker_id": worker_id,
        "display_name": worker_id.replace("-", " ").title(),
        "runtime_type": "internal",
        "status": status,
    }


def _state() -> dict:
    return {
        "worker_records": {
            "worker-a": _worker("worker-a"),
            "worker-b": _worker("worker-b"),
            "disabled-worker": _worker("disabled-worker", status="disabled"),
        },
        "organization_tree": {
            "revision": "1",
            "root_node_id": "root",
            "nodes": {
                "root": {
                    "org_node_id": "root",
                    "name": "Root",
                    "node_type": "root",
                    "lifecycle": "active",
                    "child_ids": ["engineering", "research"],
                    "leader": {"kind": "main_agent"},
                },
                "engineering": {
                    "org_node_id": "engineering",
                    "name": "Engineering",
                    "node_type": "department",
                    "lifecycle": "active",
                    "parent_id": "root",
                    "leader": {"kind": "worker", "worker_id": "worker-a"},
                    "member_worker_ids": [
                        "worker-a",
                        "disabled-worker",
                    ],
                },
                "research": {
                    "org_node_id": "research",
                    "name": "Research",
                    "node_type": "department",
                    "lifecycle": "active",
                    "parent_id": "root",
                    "leader": {"kind": "worker", "worker_id": "worker-b"},
                    "member_worker_ids": [
                        "worker-b",
                    ],
                },
            },
        },
        "threads": [],
        "department_summaries": [],
        "mentions": [],
        "broadcasts": [],
    }


def _append_worker_reply(thread_id: str, worker_id: str, text: str, message_id: str):
    messaging._append_thread_message(
        WorkerMessageEnvelope(
            message_id=message_id,
            thread_id=thread_id,
            sender=ChatParticipantRef(ChatParticipantKind.WORKER, worker_id),
            recipient_scope=ChatRecipientScope(
                participant_refs=(
                    ChatParticipantRef(
                        ChatParticipantKind.MAIN_AGENT,
                        "zermes_main_agent",
                    ),
                ),
                include_entire_thread=False,
            ),
            message_type=ChatMessageType.MENTION,
            created_at="2026-05-31T00:00:00Z",
            delivery_status=MessageDeliveryStatus.CREATED,
            visibility=MessageVisibility.TARGETED,
            body_preview=text,
        )
    )


def _runtime_reply(request):
    return RuntimeResult(
        request_id=request.request_id,
        task_id=request.task_id,
        worker_id=request.worker_id,
        runtime_type=RuntimeType.INTERNAL_WORKER,
        final_state=RuntimeState.SUCCEEDED,
        started_at=request.created_at,
        completed_at="2026-05-31T00:00:01Z",
        public_message=f"{request.worker_id} accepted the task.",
    )


def test_send_worker_message_routes_through_default_group_and_records_task(monkeypatch):
    product.write_management_state_for_tests(_state())
    monkeypatch.setattr(
        product,
        "build_worker_runtime_reply_handler",
        lambda: _runtime_reply,
    )

    result = json.loads(
        messaging._handle_send_worker_message(
            {
                "text": "Please implement the login page.",
                "mention_worker_ids": ["worker-a"],
            }
        )
    )

    assert result["status"] == "dispatched"
    assert result["dispatched_to"] == ["worker-a"]
    assert result["message_id"].startswith("msg-")

    management = product.load_management_state()
    assert any(
        thread.get("thread_id") == product.DEFAULT_GROUP_THREAD_ID
        for thread in management["threads"]
    )
    assert management["mentions"][0]["message_id"] == result["message_id"]
    assert (
        management["mentions"][0]["resolved_recipient"]["participant_id"]
        == "worker-a"
    )
    assert result["route"]["audit"]["runtime_dispatches"][0]["target_worker_id"] == "worker-a"

    messages = messaging._read_thread_messages(product.DEFAULT_GROUP_THREAD_ID)
    assert messages[0].sender.kind == ChatParticipantKind.MAIN_AGENT
    assert messages[0].sender.participant_id == "zermes_main_agent"
    assert messages[0].body_preview == "Please implement the login page."
    assert messages[1].body_preview == "worker-a accepted the task."

    task = task_state.get_pending_tasks()[0]
    assert task.dispatch_message_id == result["message_id"]
    assert task.dispatched_to == ("worker-a",)


def test_send_worker_message_initializes_empty_default_group_for_normal_message():
    product.write_management_state_for_tests(
        {
            "worker_records": {},
            "organization_tree": None,
            "threads": [],
            "department_summaries": [],
            "mentions": [],
            "broadcasts": [],
        }
    )

    result = json.loads(
        messaging._handle_send_worker_message(
            {
                "text": "Record this task in the default group.",
            }
        )
    )

    assert result["status"] == "dispatched"

    management = product.load_management_state()
    assert any(
        thread.get("thread_id") == product.DEFAULT_GROUP_THREAD_ID
        for thread in management["threads"]
    )

    messages = messaging._read_thread_messages(product.DEFAULT_GROUP_THREAD_ID)
    assert messages[0].sender.kind == ChatParticipantKind.MAIN_AGENT
    assert messages[0].body_preview == "Record this task in the default group."


def test_send_worker_message_rejects_unknown_worker_without_pending_task():
    product.write_management_state_for_tests(_state())

    result = json.loads(
        messaging._handle_send_worker_message(
            {
                "text": "Please implement the login page.",
                "mention_worker_ids": ["missing-worker"],
            }
        )
    )

    assert result["status"] == "error"
    assert "missing-worker" in result["error"]
    assert task_state.get_pending_tasks() == ()


def test_check_worker_replies_completes_only_matching_worker_task(monkeypatch):
    product.write_management_state_for_tests(_state())
    monkeypatch.setattr(
        product,
        "build_worker_runtime_reply_handler",
        lambda: (lambda _request: None),
    )
    first = json.loads(
        messaging._handle_send_worker_message(
            {"text": "Task for A", "mention_worker_ids": ["worker-a"]}
        )
    )
    second = json.loads(
        messaging._handle_send_worker_message(
            {"text": "Task for B", "mention_worker_ids": ["worker-b"]}
        )
    )
    task_state.save_read_cursor(product.DEFAULT_GROUP_THREAD_ID, second["message_id"])

    _append_worker_reply(
        product.DEFAULT_GROUP_THREAD_ID,
        "worker-a",
        "Task for A is complete.",
        "msg-worker-a",
    )

    result = json.loads(
        messaging._handle_check_worker_replies(
            {"thread_id": product.DEFAULT_GROUP_THREAD_ID}
        )
    )

    assert result["completed_tasks"] == [first["task_id"]]
    assert [task["task_id"] for task in result["pending_tasks"]] == [second["task_id"]]


def test_check_worker_replies_does_not_complete_on_normal_worker_message(monkeypatch):
    product.write_management_state_for_tests(_state())
    monkeypatch.setattr(
        product,
        "build_worker_runtime_reply_handler",
        lambda: (lambda _request: None),
    )
    sent = json.loads(
        messaging._handle_send_worker_message(
            {"text": "Task for A", "mention_worker_ids": ["worker-a"]}
        )
    )
    task_state.save_read_cursor(product.DEFAULT_GROUP_THREAD_ID, sent["message_id"])

    messaging._append_thread_message(
        WorkerMessageEnvelope(
            message_id="msg-normal",
            thread_id=product.DEFAULT_GROUP_THREAD_ID,
            sender=ChatParticipantRef(ChatParticipantKind.WORKER, "worker-a"),
            message_type=ChatMessageType.NORMAL,
            created_at="2026-05-31T00:00:00Z",
            body_preview="I have a question before starting.",
        )
    )

    result = json.loads(
        messaging._handle_check_worker_replies(
            {"thread_id": product.DEFAULT_GROUP_THREAD_ID}
        )
    )

    assert result["new_replies"][0]["message_id"] == "msg-normal"
    assert result["completed_tasks"] == []
    assert result["pending_tasks"][0]["task_id"] == sent["task_id"]

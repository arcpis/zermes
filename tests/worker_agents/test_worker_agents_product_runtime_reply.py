import json

from hermes_cli import worker_agents_product as product
from worker_agents.runtime_contract import RuntimeResult, RuntimeState, RuntimeType


def _worker(worker_id: str) -> dict:
    return {
        "worker_id": worker_id,
        "display_name": worker_id.replace("-", " ").title(),
        "runtime_type": "internal",
        "status": "enabled",
    }


def _state() -> dict:
    return {
        "worker_records": {
            "worker-a": _worker("worker-a"),
            "worker-b": _worker("worker-b"),
        },
        "organization_tree": {
            "revision": "1",
            "nodes": {
                "root": {
                    "org_node_id": "root",
                    "name": "Root",
                    "node_type": "root",
                    "lifecycle": "active",
                    "child_ids": ["engineering"],
                    "leader": {"kind": "main_agent"},
                },
                "engineering": {
                    "org_node_id": "engineering",
                    "name": "Engineering",
                    "node_type": "department",
                    "lifecycle": "active",
                    "parent_id": "root",
                    "leader": {"kind": "worker", "worker_id": "worker-a"},
                    "member_worker_ids": ["worker-a", "worker-b"],
                },
            },
        },
        "threads": [],
        "department_summaries": [],
    }


def _runtime_reply(request):
    return RuntimeResult(
        request_id=request.request_id,
        task_id=request.task_id,
        worker_id=request.worker_id,
        runtime_type=RuntimeType.INTERNAL_WORKER,
        final_state=RuntimeState.SUCCEEDED,
        started_at=request.created_at,
        completed_at="2026-05-27T00:01:00Z",
        public_message=f"{request.worker_id} received it.",
        internal_summary="raw runtime transcript: hidden",
    )


def test_targeted_group_message_routes_runtime_reply_to_same_thread():
    product.write_management_state_for_tests(_state())

    result = product.send_chat_message(
        thread_id="dept-engineering",
        sender_id="user",
        text="Please check the build.",
        target_ids=("worker-a",),
        runtime_reply_handler=_runtime_reply,
    )

    history = product.get_thread_history(
        product.ChatHistoryQuery(thread_id="dept-engineering")
    )
    assert result["audit"]["runtime_dispatches"][0]["target_worker_id"] == "worker-a"
    assert [message["body_preview"] for message in history["messages"]] == [
        "Please check the build.",
        "worker-a received it.",
    ]
    assert "raw runtime transcript" not in json.dumps(history)


def test_direct_chat_runtime_reply_stays_out_of_department_thread():
    product.write_management_state_for_tests(_state())
    product.ensure_direct_worker_chat(worker_id="worker-a")

    product.send_chat_message(
        thread_id="direct-user-worker-a",
        sender_id="user",
        text="Private status?",
        runtime_reply_handler=_runtime_reply,
    )

    direct_history = product.get_thread_history(
        product.ChatHistoryQuery(thread_id="direct-user-worker-a")
    )
    department_history = product.get_thread_history(
        product.ChatHistoryQuery(thread_id="dept-engineering")
    )
    assert [message["body_preview"] for message in direct_history["messages"]] == [
        "Private status?",
        "worker-a received it.",
    ]
    assert department_history["messages"] == []


def test_runtime_reply_handler_failure_writes_safe_summary_to_thread():
    product.write_management_state_for_tests(_state())
    product.ensure_direct_worker_chat(worker_id="worker-a")

    def fail(_request):
        raise RuntimeError("raw failure details")

    product.send_chat_message(
        thread_id="direct-user-worker-a",
        sender_id="user",
        text="Private status?",
        runtime_reply_handler=fail,
    )

    history = product.get_thread_history(
        product.ChatHistoryQuery(thread_id="direct-user-worker-a")
    )
    assert history["messages"][-1]["body_preview"] == (
        "Worker runtime could not produce a reply for this message."
    )

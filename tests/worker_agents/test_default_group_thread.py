from hermes_cli import worker_agents_product as product
from worker_agents.message_router import ChatParticipantKind


def _worker(worker_id: str, status: str = "enabled") -> dict:
    return {
        "worker_id": worker_id,
        "display_name": worker_id,
        "runtime_type": "internal",
        "status": status,
    }


def _state() -> dict:
    return {
        "worker_records": {
            "worker-a": _worker("worker-a"),
            "worker-b": _worker("worker-b"),
            "disabled-worker": _worker("disabled-worker", "disabled"),
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
                    "child_ids": ["engineering"],
                    "member_worker_ids": ["worker-a"],
                    "leader": {"kind": "main_agent"},
                },
                "engineering": {
                    "org_node_id": "engineering",
                    "name": "Engineering",
                    "node_type": "department",
                    "lifecycle": "active",
                    "parent_id": "root",
                    "leader": {"kind": "worker", "worker_id": "worker-a"},
                    "member_worker_ids": ["worker-b", "disabled-worker"],
                },
            },
        },
        "threads": [],
        "department_summaries": [],
    }


def test_ensure_default_group_thread_collects_enabled_root_workers_once():
    product.write_management_state_for_tests(_state())

    result = product.ensure_default_group_thread(user_id="user")

    state = product.load_management_state()
    thread = next(
        item
        for item in state["threads"]
        if item["thread_id"] == product.DEFAULT_GROUP_THREAD_ID
    )
    participants = thread["participants"]
    workers = [
        item["participant_id"]
        for item in participants
        if item["kind"] == ChatParticipantKind.WORKER.value
    ]
    assert workers == ["worker-a", "worker-b"]
    assert result["thread"]["thread_id"] == product.DEFAULT_GROUP_THREAD_ID


def test_ensure_default_group_thread_refreshes_existing_participants():
    state = _state()
    product.write_management_state_for_tests(state)
    product.ensure_default_group_thread(user_id="user")

    state = product.load_management_state()
    state["worker_records"]["worker-c"] = _worker("worker-c")
    state["organization_tree"]["nodes"]["engineering"]["member_worker_ids"].append(
        "worker-c"
    )
    product.write_management_state(state)

    result = product.ensure_default_group_thread(user_id="user")

    state = product.load_management_state()
    thread = next(
        item
        for item in state["threads"]
        if item["thread_id"] == product.DEFAULT_GROUP_THREAD_ID
    )
    workers = [
        item["participant_id"]
        for item in thread["participants"]
        if item["kind"] == ChatParticipantKind.WORKER.value
    ]
    assert workers == ["worker-a", "worker-b", "worker-c"]

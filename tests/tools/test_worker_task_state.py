import json

from tools import worker_task_state as state_mod


def test_task_state_records_dispatch_and_completion():
    state_mod.add_pending_task(
        task_id="task-1",
        thread_id="thread-default-group",
        dispatched_to=("worker-a",),
        task_summary="Build the login page",
        dispatch_message_id="msg-1",
    )

    task = state_mod.get_pending_tasks()[0]
    assert task.dispatched_to == ("worker-a",)
    assert task.dispatch_message_id == "msg-1"
    assert task.status == "pending"

    state_mod.mark_task_completed(
        "task-1",
        completed_by="worker-a",
        completion_message_id="msg-2",
    )

    completed = state_mod.load_task_state().pending_tasks[0]
    assert completed.status == "completed"
    assert completed.completed_by == "worker-a"
    assert completed.completion_message_id == "msg-2"
    assert completed.completed_at


def test_task_state_loads_legacy_dispatched_to_string():
    state_mod._ensure_state_dir()
    state_mod._task_state_path().write_text(
        json.dumps(
            {
                "pending_tasks": [
                    {
                        "task_id": "task-legacy",
                        "thread_id": "thread-default-group",
                        "dispatched_to": "worker-a,worker-b",
                        "task_summary": "Legacy task",
                        "dispatched_at": "2026-05-31T00:00:00Z",
                        "status": "pending",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    task = state_mod.load_task_state().pending_tasks[0]
    assert task.dispatched_to == ("worker-a", "worker-b")
    assert task.dispatch_message_id is None


def test_read_cursor_round_trips():
    assert state_mod.load_read_cursor("thread-default-group").last_read_message_id is None

    state_mod.save_read_cursor("thread-default-group", "msg-1")

    assert (
        state_mod.load_read_cursor("thread-default-group").last_read_message_id
        == "msg-1"
    )
    raw = json.loads(state_mod._cursor_path().read_text(encoding="utf-8"))
    assert raw["schema_version"] == state_mod.TASK_DISPATCH_STATE_SCHEMA_VERSION
    assert raw["cursors"]["thread-default-group"]["last_read_message_id"] == "msg-1"

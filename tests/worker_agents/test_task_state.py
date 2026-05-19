import json

import pytest

from worker_agents.task_state import (
    WORKER_TASK_SCHEMA_VERSION,
    WorkerTaskError,
    WorkerTaskState,
    dump_worker_task_state_json,
    load_worker_task_state_json,
    worker_task_state_from_dict,
    worker_task_state_to_dict,
)


def _state(**overrides):
    data = {
        "task_id": "task-1",
        "worker_id": "researcher",
        "title": "Survey",
        "objective": "Summarize the current state.",
        "created_by": "user",
        "created_at": "2026-05-19T00:00:00Z",
        "updated_at": "2026-05-19T00:00:00Z",
        "profile_snapshot": {"runtime_type": "internal"},
        "budgets": {"max_task_tokens": 1000},
        "artifacts": ("notes.md",),
        "tags": ("research",),
    }
    data.update(overrides)
    return WorkerTaskState(**data)


def test_worker_task_state_round_trips_json():
    state = _state()

    loaded = load_worker_task_state_json(dump_worker_task_state_json(state))

    assert loaded == state
    assert worker_task_state_to_dict(loaded)["schema_version"] == (
        WORKER_TASK_SCHEMA_VERSION
    )


def test_worker_task_state_rejects_unknown_fields():
    data = worker_task_state_to_dict(_state())
    data["unexpected"] = True

    with pytest.raises(WorkerTaskError, match="unknown fields"):
        worker_task_state_from_dict(data)


def test_worker_task_state_rejects_path_like_ids():
    with pytest.raises(WorkerTaskError, match="task_id"):
        _state(task_id="../outside")

    data = worker_task_state_to_dict(_state())
    data["worker_id"] = "nested/worker"
    with pytest.raises(ValueError, match="worker_id"):
        worker_task_state_from_dict(data)


def test_worker_task_state_rejects_bad_json():
    with pytest.raises(WorkerTaskError, match="Invalid worker task state JSON"):
        load_worker_task_state_json("{")


def test_worker_task_state_json_is_stable():
    raw_json = dump_worker_task_state_json(_state())

    assert json.loads(raw_json)["task_id"] == "task-1"
    assert raw_json.endswith("\n")

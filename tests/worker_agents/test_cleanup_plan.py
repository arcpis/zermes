from datetime import datetime, timezone

from worker_agents.cleanup import CleanupPlanner, cleanup_plan_to_dict
from worker_agents.retention import RetentionDataCategory
from worker_agents.storage import WorkerAgentRuntimeDataStore
from worker_agents.storage.task_store import WorkerTaskStore
from worker_agents.task_records import WorkerTaskResult
from worker_agents.task_state import WorkerTaskState, WorkerTaskStatus


NOW = datetime(2026, 5, 19, tzinfo=timezone.utc)


def _task_store(tmp_path):
    runtime_store = WorkerAgentRuntimeDataStore(
        tmp_path / "install" / "data" / "worker_agents"
    )
    return WorkerTaskStore(runtime_store)


def _state(task_id, *, status=WorkerTaskStatus.QUEUED, updated_at="2026-05-19T00:00:00Z"):
    return WorkerTaskState(
        task_id=task_id,
        worker_id="researcher",
        title="Survey",
        objective="Summarize the current state.",
        created_by="user",
        created_at=updated_at,
        updated_at=updated_at,
        status=status,
    )


def _single_item(plan):
    assert len(plan.items) == 1
    return plan.items[0]


def test_cleanup_plan_keeps_active_tasks(tmp_path):
    store = _task_store(tmp_path)
    store.save_task_state(_state("task-1", status=WorkerTaskStatus.RUNNING))

    plan = CleanupPlanner(runtime_store=store.runtime_store, now=NOW).build_plan()
    item = _single_item(plan)

    assert item.category == RetentionDataCategory.RUNTIME_ACTIVE
    assert item.can_delete is False
    assert item.requires_review is False


def test_cleanup_plan_marks_old_terminal_tasks_deletable(tmp_path):
    store = _task_store(tmp_path)
    store.save_task_state(
        _state(
            "task-1",
            status=WorkerTaskStatus.SUCCEEDED,
            updated_at="2026-04-01T00:00:00Z",
        )
    )

    plan = CleanupPlanner(runtime_store=store.runtime_store, now=NOW).build_plan()
    item = _single_item(plan)

    assert item.category == RetentionDataCategory.RUNTIME_EXPIRED_TERMINAL
    assert item.relative_path == "tasks/task-1"
    assert item.can_delete is True


def test_cleanup_plan_keeps_recent_terminal_tasks(tmp_path):
    store = _task_store(tmp_path)
    store.save_task_state(
        _state(
            "task-1",
            status=WorkerTaskStatus.SUCCEEDED,
            updated_at="2026-05-10T00:00:00Z",
        )
    )

    plan = CleanupPlanner(runtime_store=store.runtime_store, now=NOW).build_plan()
    item = _single_item(plan)

    assert item.category == RetentionDataCategory.RUNTIME_RECENT_TERMINAL
    assert item.can_delete is False


def test_cleanup_plan_requires_review_for_unretained_candidates(tmp_path):
    store = _task_store(tmp_path)
    store.save_task_state(
        _state(
            "task-1",
            status=WorkerTaskStatus.SUCCEEDED,
            updated_at="2026-04-01T00:00:00Z",
        )
    )
    store.save_task_result(
        WorkerTaskResult(
            task_id="task-1",
            summary="done",
            manifest_candidates=({"manifest_id": "artifact-1"},),
        )
    )

    plan = CleanupPlanner(runtime_store=store.runtime_store, now=NOW).build_plan()
    item = _single_item(plan)

    assert item.category == RetentionDataCategory.RUNTIME_NEEDS_REVIEW
    assert item.requires_review is True
    assert item.can_delete is False


def test_cleanup_plan_requires_review_for_orphaned_task_dirs(tmp_path):
    store = _task_store(tmp_path)
    (store.runtime_store.tasks_dir / "task-1").mkdir(parents=True)

    plan = CleanupPlanner(runtime_store=store.runtime_store, now=NOW).build_plan()
    item = _single_item(plan)

    assert item.category == RetentionDataCategory.RUNTIME_ORPHANED
    assert item.requires_review is True
    assert item.can_delete is False
    assert plan.warnings


def test_cleanup_plan_serializes_relative_paths(tmp_path):
    store = _task_store(tmp_path)
    store.save_task_state(
        _state(
            "task-1",
            status=WorkerTaskStatus.SUCCEEDED,
            updated_at="2026-04-01T00:00:00Z",
        )
    )

    data = cleanup_plan_to_dict(
        CleanupPlanner(runtime_store=store.runtime_store, now=NOW).build_plan()
    )

    assert data["items"][0]["relative_path"] == "tasks/task-1"
    assert not data["items"][0]["relative_path"].startswith("/")
    assert data["summary"] == {
        "total": 1,
        "delete": 1,
        "review": 0,
        "keep": 0,
        "warnings": 0,
    }

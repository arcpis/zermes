from datetime import datetime, timezone

import pytest

from worker_agents.cleanup import (
    CleanupExecutor,
    CleanupPlan,
    CleanupPlanItem,
    CleanupPlanner,
    cleanup_execution_result_to_dict,
)
from worker_agents.retention import RetentionAction, RetentionDataCategory
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


def _state(task_id, *, status=WorkerTaskStatus.SUCCEEDED, updated_at="2026-04-01T00:00:00Z"):
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


def _plan_for(store):
    return CleanupPlanner(runtime_store=store.runtime_store, now=NOW).build_plan()


def test_cleanup_executor_deletes_expired_terminal_task_runtime(tmp_path):
    store = _task_store(tmp_path)
    store.save_task_state(_state("task-1"))
    task_dir = store.runtime_store.tasks_dir / "task-1"
    assert task_dir.exists()

    result = CleanupExecutor(runtime_store=store.runtime_store, now=NOW).execute_plan(
        _plan_for(store)
    )

    assert result.deleted == ("tasks/task-1",)
    assert not task_dir.exists()
    result_path = (
        store.runtime_store.root
        / "cleanup-runs"
        / result.cleanup_run_id
        / "result.json"
    )
    assert result_path.exists()


def test_cleanup_executor_skips_active_items(tmp_path):
    store = _task_store(tmp_path)
    store.save_task_state(_state("task-1", status=WorkerTaskStatus.RUNNING))
    task_dir = store.runtime_store.tasks_dir / "task-1"

    result = CleanupExecutor(runtime_store=store.runtime_store, now=NOW).execute_plan(
        _plan_for(store)
    )

    assert not result.deleted
    assert result.skipped == {"tasks/task-1": "plan item is not marked for deletion"}
    assert task_dir.exists()


def test_cleanup_executor_rechecks_task_before_delete(tmp_path):
    store = _task_store(tmp_path)
    store.save_task_state(_state("task-1"))
    plan = _plan_for(store)
    store.save_task_result(
        WorkerTaskResult(
            task_id="task-1",
            summary="done",
            manifest_candidates=({"manifest_id": "artifact-1"},),
        )
    )

    result = CleanupExecutor(runtime_store=store.runtime_store, now=NOW).execute_plan(plan)

    assert not result.deleted
    assert result.skipped == {
        "tasks/task-1": "task now has requests or unretained result candidates"
    }
    assert (store.runtime_store.tasks_dir / "task-1").exists()


def test_cleanup_executor_rejects_plan_for_other_runtime_root(tmp_path):
    store = _task_store(tmp_path)
    plan = CleanupPlan(
        cleanup_run_id="cleanup-1",
        created_at="2026-05-19T00:00:00Z",
        policy_version=1,
        scan_root=str(tmp_path / "other"),
        items=(),
    )

    with pytest.raises(ValueError, match="scan_root"):
        CleanupExecutor(runtime_store=store.runtime_store, now=NOW).execute_plan(plan)


def test_cleanup_executor_reports_escaped_relative_path_as_failure(tmp_path):
    store = _task_store(tmp_path)
    plan = CleanupPlan(
        cleanup_run_id="cleanup-1",
        created_at="2026-05-19T00:00:00Z",
        policy_version=1,
        scan_root=str(store.runtime_store.root.resolve(strict=False)),
        items=(
            CleanupPlanItem(
                relative_path="../outside",
                category=RetentionDataCategory.CACHE_REBUILDABLE,
                action=RetentionAction.DELETE_WHEN_EXPIRED,
                reason="bad path",
                can_delete=True,
            ),
        ),
    )

    result = CleanupExecutor(runtime_store=store.runtime_store, now=NOW).execute_plan(plan)

    assert "../outside" in result.failed
    assert not result.deleted


def test_cleanup_executor_result_serialization_has_summary(tmp_path):
    store = _task_store(tmp_path)
    store.save_task_state(_state("task-1"))

    result = CleanupExecutor(runtime_store=store.runtime_store, now=NOW).execute_plan(
        _plan_for(store)
    )
    data = cleanup_execution_result_to_dict(result)

    assert data["summary"] == {"deleted": 1, "skipped": 0, "failed": 0}
    assert data["deleted"] == ["tasks/task-1"]

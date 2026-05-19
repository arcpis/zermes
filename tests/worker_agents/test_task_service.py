import pytest

from worker_agents.profile import WorkerAgentProfile, WorkerBudgetPolicy
from worker_agents.registry import WorkerLifecycleStatus
from worker_agents.registry_service import WorkerRegistryService
from worker_agents.storage import WorkerAgentProfileStore, WorkerAgentRuntimeDataStore
from worker_agents.task_service import WorkerTaskService
from worker_agents.task_state import WorkerTaskError, WorkerTaskStatus


def _registry_service(tmp_path):
    return WorkerRegistryService(
        WorkerAgentProfileStore(tmp_path / "profile" / "worker_agents"),
        now=lambda: "2026-05-19T00:00:00Z",
    )


def _task_service(tmp_path):
    return WorkerTaskService.from_registry_service(
        _registry_service(tmp_path),
        runtime_store=WorkerAgentRuntimeDataStore(
            tmp_path / "install" / "data" / "worker_agents"
        ),
    )


def _register_worker(service, worker_id="researcher", *, enable=True):
    service.registry_service.register_worker(
        profile=WorkerAgentProfile(
            worker_id=worker_id,
            display_name=worker_id.title(),
            description="Does focused work.",
            role="research",
            budgets=WorkerBudgetPolicy(max_task_tokens=1000, max_turn_tokens=200),
        )
    )
    if enable:
        service.registry_service.enable_worker(worker_id)


def test_task_service_creates_task_for_enabled_worker(tmp_path):
    service = _task_service(tmp_path)
    _register_worker(service)

    state = service.create_task(
        task_id="task-1",
        worker_id="researcher",
        title="Survey",
        objective="Summarize the current state.",
        created_by="user",
        budgets={"max_task_tokens": 500},
        queue=True,
    )

    assert state.status == WorkerTaskStatus.QUEUED
    assert state.assigned_worker_status == WorkerLifecycleStatus.ENABLED.value
    assert state.profile_snapshot["runtime_type"] == "internal"
    assert service.get_task("task-1") == state


@pytest.mark.parametrize(
    "status",
    [
        WorkerLifecycleStatus.REGISTERED,
        WorkerLifecycleStatus.DISABLED,
        WorkerLifecycleStatus.ARCHIVED,
        WorkerLifecycleStatus.DELETED,
    ],
)
def test_task_service_rejects_workers_that_are_not_enabled(tmp_path, status):
    service = _task_service(tmp_path)
    _register_worker(service, enable=False)
    if status == WorkerLifecycleStatus.DISABLED:
        service.registry_service.disable_worker("researcher")
    elif status == WorkerLifecycleStatus.ARCHIVED:
        service.registry_service.archive_worker("researcher")
    elif status == WorkerLifecycleStatus.DELETED:
        service.registry_service.delete_worker("researcher")

    with pytest.raises(WorkerTaskError, match="not enabled"):
        service.create_task(
            task_id=f"task-{status.value}",
            worker_id="researcher",
            title="Survey",
            objective="Summarize the current state.",
        )


def test_task_service_lists_tasks_with_filters(tmp_path):
    service = _task_service(tmp_path)
    _register_worker(service, "researcher")
    _register_worker(service, "writer")
    service.create_task(
        task_id="task-1",
        worker_id="researcher",
        title="Survey",
        objective="Summarize the current state.",
        created_by="user",
        tags=("research",),
    )
    service.create_task(
        task_id="task-2",
        worker_id="writer",
        title="Draft",
        objective="Draft a summary.",
        created_by="system",
        queue=True,
        tags=("writing",),
    )

    assert [task.task_id for task in service.list_tasks()] == ["task-1", "task-2"]
    assert [task.task_id for task in service.list_tasks(worker_id="writer")] == [
        "task-2"
    ]
    assert [task.task_id for task in service.list_tasks(status="queued")] == ["task-2"]
    assert [task.task_id for task in service.list_tasks(created_by="user")] == [
        "task-1"
    ]
    assert [task.task_id for task in service.list_tasks(tags=("research",))] == [
        "task-1"
    ]


def test_task_service_reuses_lifecycle_rules(tmp_path):
    service = _task_service(tmp_path)
    _register_worker(service)
    service.create_task(
        task_id="task-1",
        worker_id="researcher",
        title="Survey",
        objective="Summarize the current state.",
        queue=True,
    )

    running = service.start_task("task-1", updated_by="adapter")
    done = service.complete_task(
        "task-1",
        updated_by="adapter",
        status_reason="done",
        result={"artifact_count": 1},
    )

    assert running.status == WorkerTaskStatus.RUNNING
    assert done.status == WorkerTaskStatus.SUCCEEDED
    assert done.result["artifact_count"] == 1
    with pytest.raises(WorkerTaskError, match="Cannot transition"):
        service.start_task("task-1")


def test_task_service_rejects_budget_above_worker_limit(tmp_path):
    service = _task_service(tmp_path)
    _register_worker(service)

    with pytest.raises(WorkerTaskError, match="exceeds worker profile limit"):
        service.create_task(
            task_id="task-1",
            worker_id="researcher",
            title="Survey",
            objective="Summarize the current state.",
            budgets={"max_task_tokens": 1001},
        )


def test_task_service_does_not_write_profile_data_for_task(tmp_path):
    service = _task_service(tmp_path)
    _register_worker(service)
    registry_before = service.registry_service.registry_store.load_records()

    service.create_task(
        task_id="task-1",
        worker_id="researcher",
        title="Survey",
        objective="Summarize the current state.",
    )

    assert service.registry_service.registry_store.load_records() == registry_before
    assert not (service.registry_service.profile_store.root / "tasks").exists()

import pytest

from worker_agents.storage import WorkerAgentProfileStore, WorkerAgentRuntimeDataStore
from worker_agents.storage.task_store import WorkerTaskStore
from worker_agents.task_state import WorkerTaskError, WorkerTaskState


def _state(task_id="task-1"):
    return WorkerTaskState(
        task_id=task_id,
        worker_id="researcher",
        title="Survey",
        objective="Summarize the current state.",
        created_by="user",
        created_at="2026-05-19T00:00:00Z",
        updated_at="2026-05-19T00:00:00Z",
    )


def test_task_store_saves_and_loads_state_under_runtime_data(tmp_path):
    runtime_store = WorkerAgentRuntimeDataStore(
        tmp_path / "install" / "data" / "worker_agents"
    )
    task_store = WorkerTaskStore(runtime_store)

    path = task_store.save_task_state(_state())
    loaded = task_store.load_task_state("task-1")

    assert path == runtime_store.tasks_dir / "task-1" / "state.json"
    assert loaded.task_id == "task-1"
    assert (runtime_store.tasks_dir / "task-1" / "artifacts").is_dir()
    path.resolve().relative_to(runtime_store.root.resolve())


def test_task_store_rejects_missing_state(tmp_path):
    task_store = WorkerTaskStore(
        WorkerAgentRuntimeDataStore(tmp_path / "install" / "data" / "worker_agents")
    )

    with pytest.raises(WorkerTaskError, match="does not exist"):
        task_store.load_task_state("missing")


def test_task_store_rejects_state_id_mismatch(tmp_path):
    task_store = WorkerTaskStore(
        WorkerAgentRuntimeDataStore(tmp_path / "install" / "data" / "worker_agents")
    )
    path = task_store.save_task_state(_state("task-1"))
    path.write_text(
        path.read_text(encoding="utf-8").replace('"task-1"', '"task-2"', 1),
        encoding="utf-8",
    )

    with pytest.raises(WorkerTaskError, match="does not match"):
        task_store.load_task_state("task-1")


def test_task_store_does_not_create_profile_assets(tmp_path):
    profile_store = WorkerAgentProfileStore(tmp_path / "profile" / "worker_agents")
    task_store = WorkerTaskStore(
        WorkerAgentRuntimeDataStore(tmp_path / "install" / "data" / "worker_agents")
    )

    task_store.save_task_state(_state())

    assert not profile_store.root.exists()

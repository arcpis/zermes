import json
import shutil
from pathlib import Path

import pytest

from worker_agents.storage import (
    TASK_RUNTIME_FILES,
    WorkerAgentProfileStore,
    WorkerAgentRuntimeDataStore,
    ensure_worker_agents_data_dir,
    ensure_worker_agents_home,
    get_worker_agents_data_dir,
    get_worker_agents_home,
)


def test_worker_agents_home_follows_profile_home(monkeypatch, tmp_path):
    profile_home = tmp_path / "profile"
    monkeypatch.setenv("HERMES_HOME", str(profile_home))

    assert get_worker_agents_home() == profile_home / "worker_agents"


def test_worker_agents_data_dir_is_install_scoped(monkeypatch, tmp_path):
    profile_home = tmp_path / "profile"
    install_root = tmp_path / "install"
    monkeypatch.setenv("HERMES_HOME", str(profile_home))

    data_dir = get_worker_agents_data_dir(install_root=install_root)

    assert data_dir == install_root / "data" / "worker_agents"
    assert profile_home not in data_dir.parents


def test_ensure_helpers_create_directories_and_are_idempotent(monkeypatch, tmp_path):
    profile_home = tmp_path / "profile"
    install_root = tmp_path / "install"
    monkeypatch.setenv("HERMES_HOME", str(profile_home))

    profile_dir = ensure_worker_agents_home()
    data_dir = ensure_worker_agents_data_dir(install_root=install_root)

    assert ensure_worker_agents_home() == profile_dir
    assert ensure_worker_agents_data_dir(install_root=install_root) == data_dir
    assert profile_dir.is_dir()
    assert data_dir.is_dir()


def test_profile_store_initializes_durable_skeleton_without_overwriting(tmp_path):
    store = WorkerAgentProfileStore(tmp_path / "profile" / "worker_agents")

    store.initialize()
    store.registry_path.write_text('{"existing": true}\n', encoding="utf-8")
    store.initialize()

    assert store.workers_dir.is_dir()
    assert store.threads_dir.is_dir()
    assert store.manifests_dir.is_dir()
    assert json.loads(store.registry_path.read_text(encoding="utf-8")) == {
        "existing": True
    }


def test_profile_store_creates_empty_registry_in_empty_environment(tmp_path):
    store = WorkerAgentProfileStore(tmp_path / "profile" / "worker_agents")

    store.initialize()

    assert json.loads(store.registry_path.read_text(encoding="utf-8")) == {}


def test_create_worker_directory_preserves_existing_data(tmp_path):
    store = WorkerAgentProfileStore(tmp_path / "profile" / "worker_agents")

    worker_dir = store.create_worker_directory("researcher")
    marker = worker_dir / "memory.json"
    marker.write_text('{"keep": true}\n', encoding="utf-8")

    assert store.create_worker_directory("researcher") == worker_dir
    assert marker.read_text(encoding="utf-8") == '{"keep": true}\n'


def test_create_worker_directory_rejects_nested_worker_ids(tmp_path):
    store = WorkerAgentProfileStore(tmp_path / "profile" / "worker_agents")

    with pytest.raises(ValueError):
        store.create_worker_directory("../outside")


def test_runtime_store_initializes_clearable_skeleton(tmp_path):
    store = WorkerAgentRuntimeDataStore(tmp_path / "install" / "data" / "worker_agents")

    store.initialize()

    assert store.tasks_dir.is_dir()
    assert store.cache_dir.is_dir()
    assert store.logs_dir.is_dir()


def test_runtime_store_creates_task_directory_and_artifacts(tmp_path):
    store = WorkerAgentRuntimeDataStore(tmp_path / "install" / "data" / "worker_agents")

    task_dir = store.create_task_directory("task-1")

    assert task_dir == store.tasks_dir / "task-1"
    assert (task_dir / "artifacts").is_dir()


def test_runtime_paths_stay_under_data_root(tmp_path):
    store = WorkerAgentRuntimeDataStore(tmp_path / "install" / "data" / "worker_agents")

    for filename in TASK_RUNTIME_FILES:
        path = store.task_runtime_path("task-1", filename)
        path.write_text("", encoding="utf-8")
        path.resolve().relative_to(store.root.resolve())

    artifact_path = store.task_runtime_path("task-1", Path("artifacts") / "output.txt")
    artifact_path.write_text("ok\n", encoding="utf-8")
    artifact_path.resolve().relative_to(store.root.resolve())

    with pytest.raises(ValueError):
        store.task_runtime_path("task-1", "../registry.json")


def test_removing_runtime_data_does_not_remove_profile_assets(tmp_path):
    profile_store = WorkerAgentProfileStore(tmp_path / "profile" / "worker_agents")
    runtime_store = WorkerAgentRuntimeDataStore(
        tmp_path / "install" / "data" / "worker_agents"
    )

    worker_dir = profile_store.create_worker_directory("researcher")
    (worker_dir / "skill-bindings.json").write_text(
        '{"skills": []}\n', encoding="utf-8"
    )
    runtime_store.task_runtime_path("task-1", "transcript.jsonl").write_text(
        "", encoding="utf-8"
    )

    shutil.rmtree(runtime_store.root)

    assert (worker_dir / "skill-bindings.json").read_text(
        encoding="utf-8"
    ) == '{"skills": []}\n'
    assert profile_store.registry_path.exists()

import json
import shutil
from pathlib import Path

import pytest

from worker_agents.storage import (
    ORGANIZATION_ACTIVE_FILE_NAME,
    TASK_RUNTIME_FILES,
    WorkerAgentProfileStore,
    WorkerAgentRuntimeDataStore,
    ensure_worker_agents_organization_dir,
    ensure_worker_agents_data_dir,
    ensure_worker_agents_home,
    get_active_organization_path,
    get_organization_history_dir,
    get_organization_proposals_dir,
    get_worker_agents_organization_dir,
    get_worker_agents_runtime_organization_dir,
    get_worker_agents_data_dir,
    get_worker_agents_home,
)
from worker_agents.storage.safe_paths import validate_single_path_segment


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


def test_organization_paths_are_profile_scoped(monkeypatch, tmp_path):
    profile_home = tmp_path / "profile"
    monkeypatch.setenv("HERMES_HOME", str(profile_home))

    organization_dir = get_worker_agents_organization_dir()

    assert organization_dir == profile_home / "worker_agents" / "organization"
    assert get_active_organization_path() == organization_dir / "active.json"
    assert get_organization_proposals_dir() == organization_dir / "proposals"
    assert get_organization_history_dir() == organization_dir / "history"


def test_organization_path_initialization_does_not_create_active_tree(
    monkeypatch, tmp_path
):
    profile_home = tmp_path / "profile"
    monkeypatch.setenv("HERMES_HOME", str(profile_home))

    organization_dir = ensure_worker_agents_organization_dir()

    assert organization_dir.is_dir()
    assert get_organization_proposals_dir().is_dir()
    assert get_organization_history_dir().is_dir()
    assert not (organization_dir / ORGANIZATION_ACTIVE_FILE_NAME).exists()


def test_runtime_organization_path_is_separate_from_profile_home(monkeypatch, tmp_path):
    profile_home = tmp_path / "profile"
    install_root = tmp_path / "install"
    monkeypatch.setenv("HERMES_HOME", str(profile_home))

    runtime_organization_dir = get_worker_agents_runtime_organization_dir(
        install_root=install_root
    )

    assert runtime_organization_dir == install_root / "data" / "worker_agents" / "organization"
    assert profile_home not in runtime_organization_dir.parents


def test_single_segment_path_guard_rejects_unsafe_summary_ids():
    assert validate_single_path_segment("proposal-1", "summary id") == "proposal-1"

    for unsafe_id in ("", ".", "..", "../outside", "nested/id", "nested\\id"):
        with pytest.raises(ValueError, match="single summary id"):
            validate_single_path_segment(unsafe_id, "summary id")


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

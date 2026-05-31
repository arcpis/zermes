import json

import pytest

from worker_agents.registry import (
    WORKER_REGISTRY_SCHEMA_VERSION,
    WorkerLifecycleStatus,
    WorkerRegistryError,
    WorkerRegistryRecord,
    WorkerRegistryStore,
    default_profile_path_for_worker,
    worker_registry_record_from_dict,
    worker_registry_record_to_dict,
)


def test_registry_store_loads_missing_file_as_empty(tmp_path):
    store = WorkerRegistryStore(tmp_path / "profile" / "worker_agents")

    assert store.load_records() == {}


def test_registry_store_loads_legacy_empty_object_as_empty(tmp_path):
    store = WorkerRegistryStore(tmp_path / "profile" / "worker_agents")
    store.registry_path.parent.mkdir(parents=True)
    store.registry_path.write_text("{}\n", encoding="utf-8")

    assert store.load_records() == {}


def test_registry_record_round_trips_through_json_mapping(tmp_path):
    record = WorkerRegistryRecord(
        worker_id="researcher",
        display_name="Researcher",
        role="research",
        runtime_type="internal",
        tags=("analysis",),
        metadata={"owner": "main"},
    )

    data = worker_registry_record_to_dict(record)
    loaded = worker_registry_record_from_dict(
        json.loads(json.dumps(data)), root=tmp_path / "worker_agents"
    )

    assert loaded == record
    assert data["profile_path"] == "workers/researcher/worker.json"
    assert data["status"] == "registered"


@pytest.mark.parametrize("worker_id", ["", ".", "..", "team/researcher", r"team\researcher"])
def test_registry_record_rejects_path_like_worker_ids(worker_id):
    with pytest.raises((WorkerRegistryError, ValueError)):
        WorkerRegistryRecord(
            worker_id=worker_id,
            display_name="Researcher",
            role="research",
            runtime_type="internal",
        )


@pytest.mark.parametrize("profile_path", ["/tmp/worker.json", "../worker.json"])
def test_registry_record_from_dict_rejects_profile_paths_outside_root(
    tmp_path, profile_path
):
    with pytest.raises(WorkerRegistryError):
        worker_registry_record_from_dict(
            {
                "worker_id": "researcher",
                "display_name": "Researcher",
                "role": "research",
                "runtime_type": "internal",
                "status": "registered",
                "profile_path": profile_path,
            },
            root=tmp_path / "profile" / "worker_agents",
        )


def test_registry_store_saves_and_loads_records(tmp_path):
    store = WorkerRegistryStore(tmp_path / "profile" / "worker_agents")
    records = {
        "researcher": WorkerRegistryRecord(
            worker_id="researcher",
            display_name="Researcher",
            role="research",
            runtime_type="internal",
            status=WorkerLifecycleStatus.DISABLED,
        )
    }

    store.save_records(records)

    assert store.load_records() == records
    data = json.loads(store.registry_path.read_text(encoding="utf-8"))
    assert data["schema_version"] == WORKER_REGISTRY_SCHEMA_VERSION
    assert data["workers"][0]["profile_path"] == default_profile_path_for_worker(
        "researcher"
    )


def test_registry_store_rejects_mismatched_keys(tmp_path):
    store = WorkerRegistryStore(tmp_path / "profile" / "worker_agents")

    with pytest.raises(WorkerRegistryError, match="key"):
        store.save_records(
            {
                "writer": WorkerRegistryRecord(
                    worker_id="researcher",
                    display_name="Researcher",
                    role="research",
                    runtime_type="internal",
                )
            }
        )

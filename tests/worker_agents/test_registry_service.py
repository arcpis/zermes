import pytest

from worker_agents.profile import WorkerAgentProfile, WorkerRuntimeSettings
from worker_agents.registry import WorkerLifecycleStatus, WorkerRegistryError
from worker_agents.registry_service import WorkerRegistryService
from worker_agents.storage import WorkerAgentProfileStore


def _service(tmp_path):
    return WorkerRegistryService(
        WorkerAgentProfileStore(tmp_path / "profile" / "worker_agents"),
        now=lambda: "2026-05-19T00:00:00Z",
    )


def _register(
    service,
    worker_id,
    *,
    role="research",
    runtime_type="internal",
    tags=(),
):
    record = service.register_worker(
        profile=WorkerAgentProfile(
            worker_id=worker_id,
            display_name=worker_id.title(),
            description="Does focused work.",
            role=role,
            runtime=WorkerRuntimeSettings(runtime_type=runtime_type),
        )
    )
    records = service.registry_store.load_records()
    records[worker_id] = record.__class__(**{**record.__dict__, "tags": tags})
    service.registry_store.save_records(records)
    return records[worker_id]


def test_registry_service_get_worker(tmp_path):
    service = _service(tmp_path)
    record = _register(service, "researcher")

    assert service.get_worker("researcher") == record


def test_registry_service_get_missing_worker_returns_clear_error(tmp_path):
    service = _service(tmp_path)

    with pytest.raises(WorkerRegistryError, match="does not exist"):
        service.get_worker("missing")


def test_registry_service_lists_workers_with_filters(tmp_path):
    service = _service(tmp_path)
    _register(service, "researcher", runtime_type="internal", tags=("analysis",))
    _register(service, "writer", role="writing", runtime_type="external", tags=("docs",))
    service.enable_worker("researcher")
    service.disable_worker("writer")

    assert [record.worker_id for record in service.list_workers()] == [
        "researcher",
        "writer",
    ]
    assert [record.worker_id for record in service.list_workers(status="enabled")] == [
        "researcher"
    ]
    assert [
        record.worker_id for record in service.list_workers(runtime_type="external")
    ] == ["writer"]
    assert [record.worker_id for record in service.list_workers(tags=("analysis",))] == [
        "researcher"
    ]


def test_registry_service_hides_deleted_workers_by_default(tmp_path):
    service = _service(tmp_path)
    _register(service, "researcher")
    service.delete_worker("researcher", status_reason="retired")

    assert service.list_workers() == []
    assert [record.worker_id for record in service.list_workers(include_deleted=True)] == [
        "researcher"
    ]


def test_registry_service_lifecycle_operations_keep_profile_assets(tmp_path):
    service = _service(tmp_path)
    _register(service, "researcher")
    _register(service, "writer")
    profile_path = service.profile_store.worker_profile_path("researcher")
    writer_profile_path = service.profile_store.worker_profile_path("writer")

    disabled = service.disable_worker("researcher", status_reason="paused")
    archived = service.archive_worker("researcher", status_reason="old")
    deleted = service.delete_worker("writer", status_reason="retired")

    assert disabled.status == WorkerLifecycleStatus.DISABLED
    assert archived.status == WorkerLifecycleStatus.ARCHIVED
    assert deleted.status == WorkerLifecycleStatus.DELETED
    assert deleted.delete_mode == "soft_delete"
    assert profile_path.exists()
    assert writer_profile_path.exists()


def test_registry_service_refresh_worker_index_from_profile(tmp_path):
    service = _service(tmp_path)
    _register(service, "researcher")
    service.profile_store.save_worker_profile(
        WorkerAgentProfile(
            worker_id="researcher",
            display_name="Deep Researcher",
            description="Does focused work.",
            role="deep-research",
            runtime=WorkerRuntimeSettings(runtime_type="external"),
        )
    )

    refreshed = service.refresh_worker_index("researcher")

    assert refreshed.display_name == "Deep Researcher"
    assert refreshed.role == "deep-research"
    assert refreshed.runtime_type == "external"


def test_registry_service_rejects_duplicate_create(tmp_path):
    service = _service(tmp_path)
    _register(service, "researcher")

    with pytest.raises(WorkerRegistryError, match="already exists"):
        service.register_worker(
            worker_id="researcher",
            display_name="Researcher",
            description="Finds and summarizes information.",
            role="research",
        )

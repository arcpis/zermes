import json

import pytest

from worker_agents.profile import (
    WORKER_PROFILE_FILE_NAME,
    WorkerAgentProfile,
    WorkerProfileError,
    WorkerRuntimeSettings,
    dump_worker_profile_json,
)
from worker_agents.registry import WorkerLifecycleStatus, WorkerRegistryError
from worker_agents.registry_service import WorkerRegistryService
from worker_agents.storage import WorkerAgentProfileStore


def _service(tmp_path):
    return WorkerRegistryService(
        WorkerAgentProfileStore(tmp_path / "profile" / "worker_agents"),
        now=lambda: "2026-05-19T00:00:00Z",
    )


def test_register_worker_creates_profile_and_registry_record(tmp_path):
    service = _service(tmp_path)

    record = service.register_worker(
        worker_id="researcher",
        display_name="Researcher",
        description="Finds and summarizes information.",
        role="research",
        created_by="main-agent",
    )

    profile_path = (
        service.profile_store.workers_dir / "researcher" / WORKER_PROFILE_FILE_NAME
    )
    assert profile_path.exists()
    assert record.status == WorkerLifecycleStatus.REGISTERED
    assert record.display_name == "Researcher"
    assert record.created_by == "main-agent"
    assert record.profile_path == "workers/researcher/worker.json"


def test_register_worker_indexes_lightweight_fields_from_profile(tmp_path):
    service = _service(tmp_path)
    profile = WorkerAgentProfile(
        worker_id="researcher",
        display_name="Researcher",
        description="Finds and summarizes information.",
        role="research",
        runtime=WorkerRuntimeSettings(runtime_type="external", adapter_name="codex"),
    )

    record = service.register_worker(profile=profile)

    assert record.display_name == profile.display_name
    assert record.role == profile.role
    assert record.runtime_type == "external"
    data = json.loads(service.profile_store.registry_path.read_text(encoding="utf-8"))
    assert "description" not in data["workers"][0]
    assert "tools" not in data["workers"][0]


def test_enable_worker_requires_existing_profile(tmp_path):
    service = _service(tmp_path)
    service.register_worker(
        worker_id="researcher",
        display_name="Researcher",
        description="Finds and summarizes information.",
        role="research",
    )
    service.profile_store.worker_profile_path("researcher").unlink()

    with pytest.raises(WorkerRegistryError, match="profile is invalid"):
        service.enable_worker("researcher")


def test_enable_worker_requires_profile_directory_id_match(tmp_path):
    service = _service(tmp_path)
    service.register_worker(
        worker_id="researcher",
        display_name="Researcher",
        description="Finds and summarizes information.",
        role="research",
    )
    service.profile_store.worker_profile_path("researcher").write_text(
        dump_worker_profile_json(
            WorkerAgentProfile(
                worker_id="writer",
                display_name="Writer",
                description="Writes concise reports.",
                role="writing",
            )
        ),
        encoding="utf-8",
    )

    with pytest.raises(WorkerRegistryError, match="profile is invalid"):
        service.enable_worker("researcher")


def test_enable_worker_keeps_registry_unchanged_when_profile_is_invalid(tmp_path):
    service = _service(tmp_path)
    original = service.register_worker(
        worker_id="researcher",
        display_name="Researcher",
        description="Finds and summarizes information.",
        role="research",
    )
    service.profile_store.worker_profile_path("researcher").write_text(
        '{"worker_id": "researcher"}\n',
        encoding="utf-8",
    )

    with pytest.raises(WorkerRegistryError):
        service.enable_worker("researcher")

    assert service.registry_store.load_records()["researcher"] == original


def test_register_worker_rejects_invalid_profile_without_registry_write(tmp_path):
    service = _service(tmp_path)

    with pytest.raises(WorkerProfileError):
        service.register_worker(
            profile=WorkerAgentProfile(
                worker_id="team/researcher",
                display_name="Researcher",
                description="Finds and summarizes information.",
                role="research",
            )
        )

    assert service.registry_store.load_records() == {}

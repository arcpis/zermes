import pytest

from worker_agents.profile import (
    WORKER_PROFILE_FILE_NAME,
    WorkerAgentProfile,
    WorkerProfileError,
    dump_worker_profile_json,
)
from worker_agents.storage import WorkerAgentProfileStore


def test_profile_store_saves_and_loads_worker_profile(tmp_path):
    store = WorkerAgentProfileStore(tmp_path / "profile" / "worker_agents")
    profile = WorkerAgentProfile(
        worker_id="researcher",
        display_name="Researcher",
        description="Finds and summarizes information.",
        role="research",
    )

    path = store.save_worker_profile(profile)

    assert path == store.workers_dir / "researcher" / WORKER_PROFILE_FILE_NAME
    assert store.load_worker_profile("researcher") == profile


def test_profile_store_rejects_path_like_worker_ids(tmp_path):
    store = WorkerAgentProfileStore(tmp_path / "profile" / "worker_agents")

    with pytest.raises(WorkerProfileError):
        store.worker_profile_path("../outside")


def test_profile_store_reports_missing_profile(tmp_path):
    store = WorkerAgentProfileStore(tmp_path / "profile" / "worker_agents")

    with pytest.raises(WorkerProfileError, match="does not exist"):
        store.load_worker_profile("researcher")


def test_profile_store_preserves_sibling_worker_assets(tmp_path):
    store = WorkerAgentProfileStore(tmp_path / "profile" / "worker_agents")
    worker_dir = store.create_worker_directory("researcher")
    memory_dir = worker_dir / "memory"
    memory_dir.mkdir()
    memory_file = memory_dir / "notes.json"
    memory_file.write_text('{"keep": true}\n', encoding="utf-8")

    store.save_worker_profile(
        WorkerAgentProfile(
            worker_id="researcher",
            display_name="Researcher",
            description="Finds and summarizes information.",
            role="research",
        )
    )

    assert memory_file.read_text(encoding="utf-8") == '{"keep": true}\n'


def test_profile_store_rejects_directory_mismatches(tmp_path):
    store = WorkerAgentProfileStore(tmp_path / "profile" / "worker_agents")
    path = store.create_worker_directory("researcher") / WORKER_PROFILE_FILE_NAME
    path.write_text(
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

    with pytest.raises(WorkerProfileError, match="does not match"):
        store.load_worker_profile("researcher")


def test_profile_store_creates_default_profile_without_saving(tmp_path):
    store = WorkerAgentProfileStore(tmp_path / "profile" / "worker_agents")

    profile = store.create_default_worker_profile(
        "researcher",
        display_name="Researcher",
        description="Finds and summarizes information.",
        role="research",
    )

    assert profile.worker_id == "researcher"
    assert profile.tools.allowed_tools == ()
    assert not store.worker_profile_path("researcher").exists()

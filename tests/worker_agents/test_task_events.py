import pytest

from worker_agents.storage import WorkerAgentProfileStore, WorkerAgentRuntimeDataStore
from worker_agents.storage.task_store import WorkerTaskStore
from worker_agents.task_records import (
    WorkerTaskEvent,
    WorkerTaskRequest,
    WorkerTaskResult,
)
from worker_agents.task_state import WorkerTaskError


def _store(tmp_path):
    return WorkerTaskStore(
        WorkerAgentRuntimeDataStore(tmp_path / "install" / "data" / "worker_agents")
    )


def test_task_store_appends_events_and_requests(tmp_path):
    store = _store(tmp_path)

    store.append_event(
        WorkerTaskEvent(
            event_id="event-1",
            task_id="task-1",
            event_type="started",
            created_at="2026-05-19T00:00:00Z",
            source="adapter",
            summary="Started work.",
        )
    )
    store.append_request(
        WorkerTaskRequest(
            request_id="request-1",
            task_id="task-1",
            request_type="approval",
            status="pending",
            created_at="2026-05-19T00:01:00Z",
            summary="Approve external call.",
        )
    )

    assert store.load_events("task-1")[0].event_type == "started"
    assert store.load_requests("task-1")[0].request_type == "approval"


def test_task_store_reads_and_writes_rolling_summary(tmp_path):
    store = _store(tmp_path)

    store.save_rolling_summary("task-1", "Progress so far.")

    assert store.load_rolling_summary("task-1") == "Progress so far."
    assert store.load_rolling_summary("missing") == ""


def test_task_store_saves_result_without_writing_profile_home(tmp_path):
    profile_store = WorkerAgentProfileStore(tmp_path / "profile" / "worker_agents")
    store = _store(tmp_path)

    store.save_task_result(
        WorkerTaskResult(
            task_id="task-1",
            summary="Done.",
            artifact_paths=("artifacts/output.md",),
            manifest_candidates=({"path": "artifacts/output.md"},),
            memory_candidates=({"summary": "Useful preference"},),
            audit_summary_candidates=({"summary": "No external tools"},),
        )
    )
    result = store.load_task_result("task-1")

    assert result.summary == "Done."
    assert result.manifest_candidates[0]["path"] == "artifacts/output.md"
    assert not profile_store.root.exists()


@pytest.mark.parametrize("artifact_path", ["../outside.txt", "/tmp/outside.txt"])
def test_task_store_rejects_artifact_paths_outside_task(tmp_path, artifact_path):
    store = _store(tmp_path)

    with pytest.raises(WorkerTaskError, match="artifact paths|escapes"):
        store.save_task_result(
            WorkerTaskResult(
                task_id="task-1",
                summary="Done.",
                artifact_paths=(artifact_path,),
            )
        )


def test_task_store_rejects_bad_event_jsonl(tmp_path):
    store = _store(tmp_path)
    path = store.append_event(
        WorkerTaskEvent(
            event_id="event-1",
            task_id="task-1",
            event_type="started",
            created_at="2026-05-19T00:00:00Z",
            source="adapter",
            summary="Started work.",
        )
    )
    path.write_text("{\n", encoding="utf-8")

    with pytest.raises(WorkerTaskError, match="Invalid JSONL"):
        store.load_events("task-1")

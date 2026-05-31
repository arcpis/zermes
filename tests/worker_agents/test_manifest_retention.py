import json
from datetime import datetime, timezone

import pytest

from worker_agents.cleanup import CleanupPlanner
from worker_agents.manifests import TaskResultRetentionService
from worker_agents.retention import RetentionDataCategory
from worker_agents.storage import WorkerAgentProfileStore, WorkerAgentRuntimeDataStore
from worker_agents.storage.task_store import WorkerTaskStore
from worker_agents.task_records import WorkerTaskResult
from worker_agents.task_state import WorkerTaskError, WorkerTaskState, WorkerTaskStatus


NOW = datetime(2026, 5, 19, tzinfo=timezone.utc)


def _stores(tmp_path):
    profile_store = WorkerAgentProfileStore(tmp_path / "profile" / "worker_agents")
    task_store = WorkerTaskStore(
        WorkerAgentRuntimeDataStore(tmp_path / "install" / "data" / "worker_agents")
    )
    return profile_store, task_store


def _state(task_id="task-1"):
    return WorkerTaskState(
        task_id=task_id,
        worker_id="researcher",
        title="Survey",
        objective="Summarize the current state.",
        created_by="user",
        created_at="2026-04-01T00:00:00Z",
        updated_at="2026-04-01T00:00:00Z",
        status=WorkerTaskStatus.SUCCEEDED,
    )


def test_manifest_candidate_is_promoted_to_durable_manifest(tmp_path):
    profile_store, task_store = _stores(tmp_path)
    task_store.save_task_state(_state())
    task_store.save_task_result(
        WorkerTaskResult(
            task_id="task-1",
            summary="done",
            artifact_paths=("artifacts/report.md",),
            manifest_candidates=(
                {
                    "manifest_id": "report-1",
                    "artifact_path": "artifacts/report.md",
                    "summary": "Report",
                    "content_type": "text/markdown",
                    "size_bytes": 20,
                    "sha256": "abc123",
                },
            ),
            audit_summary_candidates=(
                {
                    "audit_summary_id": "audit-1",
                    "summary": "Approved for retention.",
                    "decision": "retain",
                    "risk": "low",
                },
            ),
        )
    )

    retained = TaskResultRetentionService(
        profile_store=profile_store, task_store=task_store
    ).promote_task_result_candidates("task-1")

    manifest_path = profile_store.manifests_dir / "report-1.json"
    audit_path = profile_store.root / "shared" / "audit-summaries" / "audit-1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert manifest["artifact_path"] == "artifacts/report.md"
    assert manifest["worker_id"] == "researcher"
    assert audit["summary"] == "Approved for retention."
    assert retained.manifest_candidates == ()
    assert retained.audit_summary_candidates == ()
    assert retained.metadata["retained_manifest_ids"] == ["report-1"]
    assert retained.metadata["retained_audit_summary_ids"] == ["audit-1"]


def test_manifest_retention_does_not_promote_memory_candidates(tmp_path):
    profile_store, task_store = _stores(tmp_path)
    task_store.save_task_state(_state())
    task_store.save_task_result(
        WorkerTaskResult(
            task_id="task-1",
            summary="done",
            memory_candidates=({"summary": "Remember this later."},),
        )
    )

    retained = TaskResultRetentionService(
        profile_store=profile_store, task_store=task_store
    ).promote_task_result_candidates("task-1")

    assert retained.memory_candidates == ({"summary": "Remember this later."},)
    assert not (profile_store.root / "workers" / "researcher" / "memory").exists()


def test_manifest_retention_rejects_invalid_manifest_id(tmp_path):
    profile_store, task_store = _stores(tmp_path)
    task_store.save_task_state(_state())
    task_store.save_task_result(
        WorkerTaskResult(
            task_id="task-1",
            summary="done",
            manifest_candidates=({"manifest_id": "../bad"},),
        )
    )

    with pytest.raises(WorkerTaskError, match="path separators"):
        TaskResultRetentionService(
            profile_store=profile_store, task_store=task_store
        ).promote_task_result_candidates("task-1")


def test_manifest_retention_rejects_escaped_artifact_reference(tmp_path):
    profile_store, task_store = _stores(tmp_path)
    task_store.save_task_state(_state())
    task_store.save_task_result(
        WorkerTaskResult(
            task_id="task-1",
            summary="done",
            manifest_candidates=(
                {"manifest_id": "report-1", "artifact_path": "../outside.txt"},
            ),
        )
    )

    with pytest.raises(WorkerTaskError, match="escapes"):
        TaskResultRetentionService(
            profile_store=profile_store, task_store=task_store
        ).promote_task_result_candidates("task-1")


def test_manifest_retention_rejects_sensitive_audit_content(tmp_path):
    profile_store, task_store = _stores(tmp_path)
    task_store.save_task_state(_state())
    task_store.save_task_result(
        WorkerTaskResult(
            task_id="task-1",
            summary="done",
            audit_summary_candidates=(
                {"summary": "bad", "stdout": "raw process output"},
            ),
        )
    )

    with pytest.raises(WorkerTaskError, match="sensitive fields"):
        TaskResultRetentionService(
            profile_store=profile_store, task_store=task_store
        ).promote_task_result_candidates("task-1")


def test_cleanup_plan_allows_delete_after_manifest_promotion(tmp_path):
    profile_store, task_store = _stores(tmp_path)
    task_store.save_task_state(_state())
    task_store.save_task_result(
        WorkerTaskResult(
            task_id="task-1",
            summary="done",
            manifest_candidates=({"manifest_id": "report-1"},),
        )
    )

    before = CleanupPlanner(runtime_store=task_store.runtime_store, now=NOW).build_plan()
    TaskResultRetentionService(
        profile_store=profile_store, task_store=task_store
    ).promote_task_result_candidates("task-1")
    after = CleanupPlanner(runtime_store=task_store.runtime_store, now=NOW).build_plan()

    assert before.items[0].category == RetentionDataCategory.RUNTIME_NEEDS_REVIEW
    assert after.items[0].category == RetentionDataCategory.RUNTIME_EXPIRED_TERMINAL
    assert after.items[0].can_delete is True

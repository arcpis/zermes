"""Durable manifest retention for completed worker-agent tasks."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from utils import atomic_json_write

from .storage.profile_store import WorkerAgentProfileStore
from .storage.safe_paths import path_under_root
from .storage.task_store import WorkerTaskStore
from .task_records import WorkerTaskResult
from .task_state import WorkerTaskError, validate_task_id


RETAINED_MANIFEST_SCHEMA_VERSION = 1
AUDIT_SUMMARY_SCHEMA_VERSION = 1

_SENSITIVE_AUDIT_KEYS = frozenset(
    {
        "transcript",
        "raw_transcript",
        "stdout",
        "stderr",
        "credential",
        "credentials",
        "secret",
        "token",
        "api_key",
    }
)


@dataclass
class TaskResultRetentionService:
    """Promote selected task result candidates into durable profile storage."""

    profile_store: WorkerAgentProfileStore = field(
        default_factory=WorkerAgentProfileStore
    )
    task_store: WorkerTaskStore = field(default_factory=WorkerTaskStore)

    @property
    def audit_summaries_dir(self) -> Path:
        return self.profile_store.root / "shared" / "audit-summaries"

    def promote_task_result_candidates(self, task_id: str) -> WorkerTaskResult:
        """Persist manifest/audit candidates and clear only those candidate lists."""
        validate_task_id(task_id)
        state = self.task_store.load_task_state(task_id)
        result = self.task_store.load_task_result(task_id)

        retained_manifest_ids = [
            self._save_manifest(task_id, state.worker_id, index, candidate)
            for index, candidate in enumerate(result.manifest_candidates, start=1)
        ]
        retained_audit_ids = [
            self._save_audit_summary(task_id, state.worker_id, index, candidate)
            for index, candidate in enumerate(
                result.audit_summary_candidates, start=1
            )
        ]
        retained_metadata = dict(result.metadata)
        retained_metadata["retained_manifest_ids"] = retained_manifest_ids
        retained_metadata["retained_audit_summary_ids"] = retained_audit_ids
        retained = WorkerTaskResult(
            task_id=result.task_id,
            summary=result.summary,
            artifact_paths=result.artifact_paths,
            manifest_candidates=(),
            memory_candidates=result.memory_candidates,
            audit_summary_candidates=(),
            metadata=retained_metadata,
        )
        self.task_store.save_task_result(retained)
        return retained

    def _save_manifest(
        self,
        task_id: str,
        worker_id: str,
        index: int,
        candidate: Mapping[str, Any],
    ) -> str:
        candidate = _require_mapping(candidate, "manifest candidate")
        manifest_id = _candidate_id(candidate, "manifest_id", task_id, "manifest", index)
        artifact_path = candidate.get("artifact_path")
        if artifact_path is not None:
            _validate_task_artifact_reference(self.task_store, task_id, artifact_path)
        payload = {
            "schema_version": RETAINED_MANIFEST_SCHEMA_VERSION,
            "manifest_id": manifest_id,
            "task_id": task_id,
            "worker_id": worker_id,
            "summary": _optional_string(candidate.get("summary"), "summary"),
            "artifact_path": artifact_path,
            "content_type": _optional_string(
                candidate.get("content_type"), "content_type"
            ),
            "size_bytes": _optional_non_negative_int(
                candidate.get("size_bytes"), "size_bytes"
            ),
            "sha256": _optional_string(candidate.get("sha256"), "sha256"),
            "metadata": _optional_mapping(candidate.get("metadata"), "metadata"),
        }
        self.profile_store.initialize()
        atomic_json_write(self.profile_store.manifests_dir / f"{manifest_id}.json", payload)
        return manifest_id

    def _save_audit_summary(
        self,
        task_id: str,
        worker_id: str,
        index: int,
        candidate: Mapping[str, Any],
    ) -> str:
        candidate = _require_mapping(candidate, "audit summary candidate")
        _reject_sensitive_audit_fields(candidate)
        audit_summary_id = _candidate_id(
            candidate, "audit_summary_id", task_id, "audit", index
        )
        payload = {
            "schema_version": AUDIT_SUMMARY_SCHEMA_VERSION,
            "audit_summary_id": audit_summary_id,
            "task_id": task_id,
            "worker_id": worker_id,
            "summary": _require_string(candidate.get("summary"), "summary"),
            "decision": _optional_string(candidate.get("decision"), "decision"),
            "risk": _optional_string(candidate.get("risk"), "risk"),
            "metadata": _optional_mapping(candidate.get("metadata"), "metadata"),
        }
        self.audit_summaries_dir.mkdir(parents=True, exist_ok=True)
        atomic_json_write(self.audit_summaries_dir / f"{audit_summary_id}.json", payload)
        return audit_summary_id


def _candidate_id(
    candidate: Mapping[str, Any],
    field_name: str,
    task_id: str,
    prefix: str,
    index: int,
) -> str:
    value = candidate.get(field_name) or f"{task_id}-{prefix}-{index}"
    return _validate_single_segment_id(_require_string(value, field_name))


def _validate_single_segment_id(value: str) -> str:
    if not value or value in {".", ".."}:
        raise WorkerTaskError("retained manifest ids must be a path segment")
    if "/" in value or "\\" in value:
        raise WorkerTaskError("retained manifest ids must not contain path separators")
    return value


def _validate_task_artifact_reference(
    task_store: WorkerTaskStore, task_id: str, artifact_path: Any
) -> None:
    artifact_path = _require_string(artifact_path, "artifact_path")
    if Path(artifact_path).is_absolute():
        raise WorkerTaskError("artifact_path must be relative to the task directory")
    task_dir = task_store.task_dir(task_id)
    try:
        path_under_root(task_dir, artifact_path)
    except ValueError as exc:
        raise WorkerTaskError(str(exc)) from exc


def _reject_sensitive_audit_fields(candidate: Mapping[str, Any]) -> None:
    present = sorted(set(candidate).intersection(_SENSITIVE_AUDIT_KEYS))
    if present:
        joined = ", ".join(present)
        raise WorkerTaskError(f"audit summary contains sensitive fields: {joined}")
    metadata = candidate.get("metadata")
    if isinstance(metadata, Mapping):
        present = sorted(set(metadata).intersection(_SENSITIVE_AUDIT_KEYS))
        if present:
            joined = ", ".join(present)
            raise WorkerTaskError(f"audit summary metadata contains sensitive fields: {joined}")


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise WorkerTaskError(f"{field_name} must be an object")
    return value


def _optional_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    return dict(_require_mapping(value, field_name))


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise WorkerTaskError(f"{field_name} must be a non-empty string")
    return value


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, field_name)


def _optional_non_negative_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise WorkerTaskError(f"{field_name} must be a non-negative integer")
    return value

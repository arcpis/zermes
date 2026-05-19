"""Clearable runtime storage for managed worker task state."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from utils import atomic_json_write

from ..task_records import (
    WorkerTaskEvent,
    WorkerTaskRequest,
    WorkerTaskResult,
    task_event_from_dict,
    task_event_to_dict,
    task_request_from_dict,
    task_request_to_dict,
    task_result_from_dict,
    task_result_to_dict,
)
from ..task_state import (
    WorkerTaskError,
    WorkerTaskState,
    load_worker_task_state_json,
    validate_task_id,
    worker_task_state_to_dict,
)
from .runtime_data_store import WorkerAgentRuntimeDataStore
from .safe_paths import path_under_root


WORKER_TASK_STATE_FILE_NAME = "state.json"
WORKER_TASK_EVENTS_FILE_NAME = "events.jsonl"
WORKER_TASK_REQUESTS_FILE_NAME = "requests.jsonl"
WORKER_TASK_SUMMARY_FILE_NAME = "rolling-summary.md"
WORKER_TASK_RESULT_FILE_NAME = "result.json"


@dataclass
class WorkerTaskStore:
    """Read and write task snapshots under clearable runtime storage."""

    runtime_store: WorkerAgentRuntimeDataStore = field(
        default_factory=WorkerAgentRuntimeDataStore
    )

    def task_dir(self, task_id: str) -> Path:
        """Return an existing task directory path without creating task state."""
        validate_task_id(task_id)
        return self.runtime_store.tasks_dir / task_id

    def task_state_path(self, task_id: str) -> Path:
        """Return the `state.json` path for one task."""
        validate_task_id(task_id)
        return self.task_dir(task_id) / WORKER_TASK_STATE_FILE_NAME

    def save_task_state(self, state: WorkerTaskState) -> Path:
        """Validate and persist one task snapshot without touching profile data."""
        task_dir = self.runtime_store.create_task_directory(state.task_id)
        path = task_dir / WORKER_TASK_STATE_FILE_NAME
        atomic_json_write(path, worker_task_state_to_dict(state))
        return path

    def load_task_state(self, task_id: str) -> WorkerTaskState:
        """Load one task snapshot from clearable runtime storage."""
        path = self.task_state_path(task_id)
        if not path.exists():
            raise WorkerTaskError(f"Worker task state does not exist: {task_id!r}")
        state = load_worker_task_state_json(path.read_text(encoding="utf-8"))
        if state.task_id != task_id:
            raise WorkerTaskError("Worker task id does not match its runtime directory")
        return state

    def append_event(self, event: WorkerTaskEvent) -> Path:
        """Append one event record to a task-local JSONL timeline."""
        path = self._task_file_path(event.task_id, WORKER_TASK_EVENTS_FILE_NAME)
        _append_jsonl(path, task_event_to_dict(event))
        return path

    def load_events(self, task_id: str) -> list[WorkerTaskEvent]:
        """Load task-local events from JSONL in append order."""
        path = self.task_state_path(task_id).with_name(WORKER_TASK_EVENTS_FILE_NAME)
        return [
            task_event_from_dict(data)
            for data in _load_jsonl(path, missing_ok=True)
        ]

    def append_request(self, request: WorkerTaskRequest) -> Path:
        """Append one task-local approval or input request record."""
        path = self._task_file_path(request.task_id, WORKER_TASK_REQUESTS_FILE_NAME)
        _append_jsonl(path, task_request_to_dict(request))
        return path

    def load_requests(self, task_id: str) -> list[WorkerTaskRequest]:
        """Load task-local requests from JSONL in append order."""
        path = self.task_state_path(task_id).with_name(WORKER_TASK_REQUESTS_FILE_NAME)
        return [
            task_request_from_dict(data)
            for data in _load_jsonl(path, missing_ok=True)
        ]

    def save_rolling_summary(self, task_id: str, summary: str) -> Path:
        """Save a clearable, regenerable task summary."""
        if not isinstance(summary, str):
            raise WorkerTaskError("rolling summary must be a string")
        path = self._task_file_path(task_id, WORKER_TASK_SUMMARY_FILE_NAME)
        path.write_text(summary, encoding="utf-8")
        return path

    def load_rolling_summary(self, task_id: str) -> str:
        """Load a task rolling summary, returning an empty string if absent."""
        path = self.task_state_path(task_id).with_name(WORKER_TASK_SUMMARY_FILE_NAME)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def save_task_result(self, result: WorkerTaskResult) -> Path:
        """Save a compact task result without writing durable manifests."""
        self._validate_artifact_paths(result.task_id, result.artifact_paths)
        path = self._task_file_path(result.task_id, WORKER_TASK_RESULT_FILE_NAME)
        atomic_json_write(path, task_result_to_dict(result))
        return path

    def load_task_result(self, task_id: str) -> WorkerTaskResult:
        """Load a compact task result from runtime storage."""
        path = self.task_state_path(task_id).with_name(WORKER_TASK_RESULT_FILE_NAME)
        if not path.exists():
            raise WorkerTaskError(f"Worker task result does not exist: {task_id!r}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise WorkerTaskError(f"Invalid worker task result JSON: {exc.msg}") from exc
        result = task_result_from_dict(data)
        if result.task_id != task_id:
            raise WorkerTaskError("Worker task result id does not match its directory")
        self._validate_artifact_paths(task_id, result.artifact_paths)
        return result

    def _task_file_path(self, task_id: str, filename: str) -> Path:
        validate_task_id(task_id)
        task_dir = self.runtime_store.create_task_directory(task_id)
        return task_dir / filename

    def _validate_artifact_paths(
        self, task_id: str, artifact_paths: Iterable[str]
    ) -> None:
        task_dir = self.runtime_store.create_task_directory(task_id)
        for artifact_path in artifact_paths:
            if Path(artifact_path).is_absolute():
                raise WorkerTaskError("artifact paths must be relative to the task")
            try:
                path_under_root(task_dir, artifact_path)
            except ValueError as exc:
                raise WorkerTaskError(str(exc)) from exc


def _append_jsonl(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, sort_keys=True) + "\n")


def _load_jsonl(path: Path, *, missing_ok: bool = False) -> list[dict[str, object]]:
    if not path.exists():
        if missing_ok:
            return []
        raise WorkerTaskError(f"JSONL file does not exist: {path.name}")
    records = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise WorkerTaskError(
                f"Invalid JSONL record in {path.name} at line {line_number}: {exc.msg}"
            ) from exc
        if not isinstance(data, dict):
            raise WorkerTaskError(
                f"JSONL record in {path.name} at line {line_number} must be an object"
            )
        records.append(data)
    return records

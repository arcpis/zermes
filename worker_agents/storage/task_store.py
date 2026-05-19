"""Clearable runtime storage for managed worker task state."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from utils import atomic_json_write

from ..task_state import (
    WorkerTaskError,
    WorkerTaskState,
    load_worker_task_state_json,
    validate_task_id,
    worker_task_state_to_dict,
)
from .runtime_data_store import WorkerAgentRuntimeDataStore


WORKER_TASK_STATE_FILE_NAME = "state.json"


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

"""Clearable install-data storage for managed worker-agent task runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .paths import get_worker_agents_data_dir
from .safe_paths import ensure_single_segment_dir, path_under_root


RUNTIME_DATA_DIRS = ("tasks", "cache", "logs")
TASK_RUNTIME_FILES = frozenset({
    "state.json",
    "events.jsonl",
    "messages.jsonl",
    "requests.jsonl",
    "transcript.jsonl",
    "rolling-summary.md",
    "result.json",
})


@dataclass
class WorkerAgentRuntimeDataStore:
    """Minimal clearable storage entry point for worker-agent task runs."""

    root: Path = field(default_factory=get_worker_agents_data_dir)

    @property
    def tasks_dir(self) -> Path:
        return self.root / "tasks"

    @property
    def cache_dir(self) -> Path:
        return self.root / "cache"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    def initialize(self) -> Path:
        """Create the clearable runtime store skeleton."""
        self.root.mkdir(parents=True, exist_ok=True)
        for dirname in RUNTIME_DATA_DIRS:
            (self.root / dirname).mkdir(exist_ok=True)
        return self.root

    def create_task_directory(self, task_id: str) -> Path:
        """Create and return a task runtime directory with an artifacts folder."""
        self.initialize()
        task_dir = ensure_single_segment_dir(self.tasks_dir, task_id)
        (task_dir / "artifacts").mkdir(exist_ok=True)
        return task_dir

    def task_runtime_path(self, task_id: str, relative_path: str | Path) -> Path:
        """Return a path for task-local runtime data, rejecting escapes."""
        task_dir = self.create_task_directory(task_id)
        return path_under_root(task_dir, relative_path)

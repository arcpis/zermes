"""Durable profile-home storage for managed worker agents."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .paths import get_worker_agents_home
from .safe_paths import ensure_single_segment_dir


WORKER_REGISTRY_FILE_NAME = "registry.json"
PROFILE_STORE_DIRS = ("workers", "threads", "manifests")


@dataclass
class WorkerAgentProfileStore:
    """Minimal durable storage entry point for worker-agent assets."""

    root: Path = field(default_factory=get_worker_agents_home)

    @property
    def registry_path(self) -> Path:
        return self.root / WORKER_REGISTRY_FILE_NAME

    @property
    def workers_dir(self) -> Path:
        return self.root / "workers"

    @property
    def threads_dir(self) -> Path:
        return self.root / "threads"

    @property
    def manifests_dir(self) -> Path:
        return self.root / "manifests"

    def initialize(self) -> Path:
        """Create the durable store skeleton without overwriting registry data."""
        self.root.mkdir(parents=True, exist_ok=True)
        for dirname in PROFILE_STORE_DIRS:
            (self.root / dirname).mkdir(exist_ok=True)
        if not self.registry_path.exists():
            self.registry_path.write_text(
                json.dumps({}, indent=2) + "\n", encoding="utf-8"
            )
        return self.root

    def create_worker_directory(self, worker_id: str) -> Path:
        """Create and return one durable worker directory without modifying it."""
        self.initialize()
        return ensure_single_segment_dir(self.workers_dir, worker_id)

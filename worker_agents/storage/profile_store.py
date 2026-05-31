"""Durable profile-home storage for managed worker agents."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..profile import (
    WORKER_PROFILE_FILE_NAME,
    WorkerAgentProfile,
    WorkerProfileError,
    dump_worker_profile_json,
    load_worker_profile_json,
    validate_worker_id,
)

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

    def worker_profile_path(self, worker_id: str) -> Path:
        """Return the durable profile path for one worker without creating it."""
        validate_worker_id(worker_id)
        return self.workers_dir / worker_id / WORKER_PROFILE_FILE_NAME

    def load_worker_profile(self, worker_id: str) -> WorkerAgentProfile:
        """Load and validate one worker profile from durable storage."""
        path = self.worker_profile_path(worker_id)
        if not path.exists():
            raise WorkerProfileError(f"Worker profile does not exist: {worker_id!r}")
        profile = load_worker_profile_json(path.read_text(encoding="utf-8"))
        if profile.worker_id != worker_id:
            raise WorkerProfileError(
                "Worker profile id does not match its durable directory"
            )
        return profile

    def save_worker_profile(self, profile: WorkerAgentProfile) -> Path:
        """Validate and save one worker profile without touching sibling assets."""
        validate_worker_id(profile.worker_id)
        worker_dir = self.create_worker_directory(profile.worker_id)
        path = worker_dir / WORKER_PROFILE_FILE_NAME
        path.write_text(dump_worker_profile_json(profile), encoding="utf-8")
        return path

    def create_default_worker_profile(
        self,
        worker_id: str,
        *,
        display_name: str,
        description: str,
        role: str,
    ) -> WorkerAgentProfile:
        """Create a minimum-permission profile object without registering it."""
        validate_worker_id(worker_id)
        return WorkerAgentProfile(
            worker_id=worker_id,
            display_name=display_name,
            description=description,
            role=role,
        )

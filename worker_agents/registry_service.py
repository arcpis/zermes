"""Profile-aware lifecycle operations for managed worker registration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from .profile import WorkerAgentProfile, WorkerProfileError
from .registry import (
    WorkerLifecycleStatus,
    WorkerRegistryError,
    WorkerRegistryRecord,
    WorkerRegistryStore,
    default_profile_path_for_worker,
    transition_worker_status,
    utc_timestamp,
)
from .storage import WorkerAgentProfileStore


def registry_record_from_profile(
    profile: WorkerAgentProfile,
    *,
    status: WorkerLifecycleStatus = WorkerLifecycleStatus.REGISTERED,
    created_at: str | None = None,
    updated_at: str | None = None,
    created_by: str | None = None,
    updated_by: str | None = None,
) -> WorkerRegistryRecord:
    """Create the registry index fields that are intentionally duplicated."""
    return WorkerRegistryRecord(
        worker_id=profile.worker_id,
        display_name=profile.display_name,
        role=profile.role,
        runtime_type=profile.runtime.runtime_type,
        status=status,
        profile_path=default_profile_path_for_worker(profile.worker_id),
        created_at=created_at,
        updated_at=updated_at,
        created_by=created_by,
        updated_by=updated_by,
    )


@dataclass
class WorkerRegistryService:
    """Coordinate worker profiles with their durable registry records."""

    profile_store: WorkerAgentProfileStore
    now: Callable[[], str] = utc_timestamp

    @property
    def registry_store(self) -> WorkerRegistryStore:
        return WorkerRegistryStore(self.profile_store.root)

    def register_worker(
        self,
        *,
        profile: WorkerAgentProfile | None = None,
        worker_id: str | None = None,
        display_name: str | None = None,
        description: str | None = None,
        role: str | None = None,
        created_by: str = "system",
    ) -> WorkerRegistryRecord:
        """Create a durable profile and registry record in registered state."""
        if profile is None:
            missing = [
                name
                for name, value in (
                    ("worker_id", worker_id),
                    ("display_name", display_name),
                    ("description", description),
                    ("role", role),
                )
                if not value
            ]
            if missing:
                raise WorkerRegistryError(
                    "register_worker is missing fields: " + ", ".join(missing)
                )
            profile = self.profile_store.create_default_worker_profile(
                worker_id or "",
                display_name=display_name or "",
                description=description or "",
                role=role or "",
            )

        records = self.registry_store.load_records()
        if profile.worker_id in records:
            raise WorkerRegistryError(f"Worker already exists: {profile.worker_id!r}")

        saved_path = self.profile_store.save_worker_profile(profile)
        expected_path = self.profile_store.worker_profile_path(profile.worker_id)
        if saved_path != expected_path:
            raise WorkerRegistryError("Saved worker profile path is inconsistent")

        timestamp = self.now()
        record = registry_record_from_profile(
            profile,
            created_at=timestamp,
            updated_at=timestamp,
            created_by=created_by,
            updated_by=created_by,
        )
        records[profile.worker_id] = record
        self.registry_store.save_records(records)
        return record

    def enable_worker(
        self,
        worker_id: str,
        *,
        updated_by: str = "system",
        status_reason: str | None = None,
    ) -> WorkerRegistryRecord:
        """Enable a worker only after its durable profile still validates."""
        records = self.registry_store.load_records()
        record = records.get(worker_id)
        if record is None:
            raise WorkerRegistryError(f"Worker does not exist: {worker_id!r}")
        try:
            profile = self.profile_store.load_worker_profile(worker_id)
        except WorkerProfileError as exc:
            raise WorkerRegistryError(f"Worker profile is invalid: {exc}") from exc

        updated = transition_worker_status(
            record,
            WorkerLifecycleStatus.ENABLED,
            updated_by=updated_by,
            status_reason=status_reason,
            now=self.now(),
        )
        # Refresh list-index fields after validation; policy remains in worker.json.
        updated = replace(
            updated,
            display_name=profile.display_name,
            role=profile.role,
            runtime_type=profile.runtime.runtime_type,
            profile_path=default_profile_path_for_worker(profile.worker_id),
        )
        records[worker_id] = updated
        self.registry_store.save_records(records)
        return updated

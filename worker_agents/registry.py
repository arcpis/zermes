"""Durable registry records for managed worker agents."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping

from utils import atomic_json_write

from .profile import validate_worker_id
from .storage.profile_store import WORKER_REGISTRY_FILE_NAME
from .storage.safe_paths import path_under_root


WORKER_REGISTRY_SCHEMA_VERSION = 1
WORKER_PROFILE_RELATIVE_PATH = "workers/{worker_id}/worker.json"


class WorkerRegistryError(ValueError):
    """Raised when a worker registry file or record is invalid."""


class WorkerLifecycleStatus(StrEnum):
    """Long-lived worker availability state, separate from task runtime state."""

    REGISTERED = "registered"
    ENABLED = "enabled"
    DISABLED = "disabled"
    ARCHIVED = "archived"
    DELETED = "deleted"


class WorkerDeleteMode(StrEnum):
    """How a delete request is represented in durable registry metadata."""

    SOFT_DELETE = "soft_delete"


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise WorkerRegistryError(f"{field_name} must be an object")
    return value


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise WorkerRegistryError(f"{field_name} must be a non-empty string")
    return value


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, field_name)


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise WorkerRegistryError(f"{field_name} must be a list of strings")
    result = tuple(value)
    if any(not isinstance(item, str) or not item for item in result):
        raise WorkerRegistryError(f"{field_name} must be a list of non-empty strings")
    return result


def _optional_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    return dict(_require_mapping(value, field_name))


def _reject_unknown_fields(
    data: Mapping[str, Any], allowed_fields: set[str], field_name: str
) -> None:
    unknown_fields = sorted(set(data) - allowed_fields)
    if unknown_fields:
        joined = ", ".join(unknown_fields)
        raise WorkerRegistryError(f"{field_name} has unknown fields: {joined}")


def _coerce_status(value: Any) -> WorkerLifecycleStatus:
    raw_status = _require_string(value, "status")
    try:
        return WorkerLifecycleStatus(raw_status)
    except ValueError as exc:
        raise WorkerRegistryError(f"Unknown worker lifecycle status: {raw_status!r}") from exc


def _validate_profile_path(root: Path, profile_path: str) -> str:
    if not profile_path:
        raise WorkerRegistryError("profile_path must be a non-empty relative path")
    try:
        path_under_root(root, profile_path)
    except ValueError as exc:
        raise WorkerRegistryError(str(exc)) from exc
    if Path(profile_path).is_absolute():
        raise WorkerRegistryError("profile_path must be relative")
    return profile_path.replace("\\", "/")


def default_profile_path_for_worker(worker_id: str) -> str:
    """Return the durable profile path stored in registry records."""
    return WORKER_PROFILE_RELATIVE_PATH.format(worker_id=validate_worker_id(worker_id))


def utc_timestamp() -> str:
    """Return a stable UTC timestamp for registry audit fields."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class WorkerRegistryRecord:
    """Lightweight durable index entry for one managed worker."""

    worker_id: str
    display_name: str
    role: str
    runtime_type: str
    status: WorkerLifecycleStatus = WorkerLifecycleStatus.REGISTERED
    profile_path: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    created_by: str | None = None
    updated_by: str | None = None
    archived_at: str | None = None
    deleted_at: str | None = None
    delete_mode: str | None = None
    status_reason: str | None = None
    tags: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_worker_id(self.worker_id)
        if self.profile_path is None:
            object.__setattr__(
                self, "profile_path", default_profile_path_for_worker(self.worker_id)
            )


_ALLOWED_STATUS_TRANSITIONS = {
    WorkerLifecycleStatus.REGISTERED: {
        WorkerLifecycleStatus.ENABLED,
        WorkerLifecycleStatus.DISABLED,
        WorkerLifecycleStatus.ARCHIVED,
        WorkerLifecycleStatus.DELETED,
    },
    WorkerLifecycleStatus.ENABLED: {
        WorkerLifecycleStatus.DISABLED,
        WorkerLifecycleStatus.ARCHIVED,
        WorkerLifecycleStatus.DELETED,
    },
    WorkerLifecycleStatus.DISABLED: {
        WorkerLifecycleStatus.ENABLED,
        WorkerLifecycleStatus.ARCHIVED,
        WorkerLifecycleStatus.DELETED,
    },
    WorkerLifecycleStatus.ARCHIVED: {WorkerLifecycleStatus.DISABLED},
    WorkerLifecycleStatus.DELETED: set(),
}


def transition_worker_status(
    record: WorkerRegistryRecord,
    target_status: WorkerLifecycleStatus,
    *,
    updated_by: str,
    status_reason: str | None = None,
    now: str | None = None,
    delete_mode: WorkerDeleteMode | None = None,
) -> WorkerRegistryRecord:
    """Return a record with an allowed lifecycle transition applied."""
    if record.status == target_status:
        return replace(
            record,
            updated_at=now or utc_timestamp(),
            updated_by=updated_by,
            status_reason=status_reason,
        )
    allowed_targets = _ALLOWED_STATUS_TRANSITIONS[record.status]
    if target_status not in allowed_targets:
        raise WorkerRegistryError(
            f"Cannot transition worker {record.worker_id!r} "
            f"from {record.status.value!r} to {target_status.value!r}"
        )

    changed_at = now or utc_timestamp()
    return replace(
        record,
        status=target_status,
        updated_at=changed_at,
        updated_by=updated_by,
        archived_at=changed_at
        if target_status == WorkerLifecycleStatus.ARCHIVED
        else record.archived_at,
        deleted_at=changed_at
        if target_status == WorkerLifecycleStatus.DELETED
        else record.deleted_at,
        delete_mode=(delete_mode or WorkerDeleteMode.SOFT_DELETE).value
        if target_status == WorkerLifecycleStatus.DELETED
        else record.delete_mode,
        status_reason=status_reason,
    )


def enable_worker_record(
    record: WorkerRegistryRecord, *, updated_by: str, status_reason: str | None = None
) -> WorkerRegistryRecord:
    """Mark a registered or disabled worker available for future scheduling."""
    return transition_worker_status(
        record,
        WorkerLifecycleStatus.ENABLED,
        updated_by=updated_by,
        status_reason=status_reason,
    )


def disable_worker_record(
    record: WorkerRegistryRecord, *, updated_by: str, status_reason: str | None = None
) -> WorkerRegistryRecord:
    """Mark a worker unavailable while keeping its durable assets."""
    return transition_worker_status(
        record,
        WorkerLifecycleStatus.DISABLED,
        updated_by=updated_by,
        status_reason=status_reason,
    )


def archive_worker_record(
    record: WorkerRegistryRecord, *, updated_by: str, status_reason: str | None = None
) -> WorkerRegistryRecord:
    """Hide a worker from normal lists without deleting durable assets."""
    return transition_worker_status(
        record,
        WorkerLifecycleStatus.ARCHIVED,
        updated_by=updated_by,
        status_reason=status_reason,
    )


def delete_worker_record(
    record: WorkerRegistryRecord, *, updated_by: str, status_reason: str | None = None
) -> WorkerRegistryRecord:
    """Soft-delete a worker registry record while preserving its asset directory."""
    return transition_worker_status(
        record,
        WorkerLifecycleStatus.DELETED,
        updated_by=updated_by,
        status_reason=status_reason,
        delete_mode=WorkerDeleteMode.SOFT_DELETE,
    )


_RECORD_FIELDS = {
    "worker_id",
    "display_name",
    "role",
    "runtime_type",
    "status",
    "profile_path",
    "created_at",
    "updated_at",
    "created_by",
    "updated_by",
    "archived_at",
    "deleted_at",
    "delete_mode",
    "status_reason",
    "tags",
    "metadata",
}


def worker_registry_record_from_dict(
    data: Mapping[str, Any], *, root: Path
) -> WorkerRegistryRecord:
    """Build one registry record from a strict JSON mapping."""
    data = _require_mapping(data, "worker registry record")
    _reject_unknown_fields(data, _RECORD_FIELDS, "worker registry record")

    missing_fields = [
        field_name
        for field_name in ("worker_id", "display_name", "role", "runtime_type", "status")
        if field_name not in data
    ]
    if missing_fields:
        joined = ", ".join(missing_fields)
        raise WorkerRegistryError(f"worker registry record is missing fields: {joined}")

    worker_id = validate_worker_id(_require_string(data["worker_id"], "worker_id"))
    profile_path = _validate_profile_path(
        root,
        _require_string(
            data.get("profile_path", default_profile_path_for_worker(worker_id)),
            "profile_path",
        ),
    )
    return WorkerRegistryRecord(
        worker_id=worker_id,
        display_name=_require_string(data["display_name"], "display_name"),
        role=_require_string(data["role"], "role"),
        runtime_type=_require_string(data["runtime_type"], "runtime_type"),
        status=_coerce_status(data["status"]),
        profile_path=profile_path,
        created_at=_optional_string(data.get("created_at"), "created_at"),
        updated_at=_optional_string(data.get("updated_at"), "updated_at"),
        created_by=_optional_string(data.get("created_by"), "created_by"),
        updated_by=_optional_string(data.get("updated_by"), "updated_by"),
        archived_at=_optional_string(data.get("archived_at"), "archived_at"),
        deleted_at=_optional_string(data.get("deleted_at"), "deleted_at"),
        delete_mode=_optional_string(data.get("delete_mode"), "delete_mode"),
        status_reason=_optional_string(data.get("status_reason"), "status_reason"),
        tags=_string_tuple(data.get("tags", ()), "tags"),
        metadata=_optional_mapping(data.get("metadata"), "metadata"),
    )


def worker_registry_record_to_dict(record: WorkerRegistryRecord) -> dict[str, Any]:
    """Convert one registry record to deterministic JSON-ready data."""
    return {
        "worker_id": record.worker_id,
        "display_name": record.display_name,
        "role": record.role,
        "runtime_type": record.runtime_type,
        "status": record.status.value,
        "profile_path": record.profile_path,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "created_by": record.created_by,
        "updated_by": record.updated_by,
        "archived_at": record.archived_at,
        "deleted_at": record.deleted_at,
        "delete_mode": record.delete_mode,
        "status_reason": record.status_reason,
        "tags": list(record.tags),
        "metadata": dict(record.metadata),
    }


@dataclass
class WorkerRegistryStore:
    """Read and write the durable worker registry under profile home."""

    root: Path

    @property
    def registry_path(self) -> Path:
        return self.root / WORKER_REGISTRY_FILE_NAME

    def load_records(self) -> dict[str, WorkerRegistryRecord]:
        """Load registry records keyed by worker id.

        A missing file or legacy empty object means no workers are registered.
        """
        if not self.registry_path.exists():
            return {}
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise WorkerRegistryError(f"Invalid worker registry JSON: {exc.msg}") from exc
        data = _require_mapping(data, "worker registry")
        if not data:
            return {}
        schema_version = data.get("schema_version")
        if schema_version != WORKER_REGISTRY_SCHEMA_VERSION:
            raise WorkerRegistryError(
                f"Unsupported worker registry schema_version: {schema_version!r}"
            )
        workers = data.get("workers", [])
        if not isinstance(workers, list):
            raise WorkerRegistryError("worker registry workers must be a list")
        records = [
            worker_registry_record_from_dict(record_data, root=self.root)
            for record_data in workers
        ]
        result = {record.worker_id: record for record in records}
        if len(result) != len(records):
            raise WorkerRegistryError("worker registry contains duplicate worker ids")
        return result

    def save_records(self, records: Mapping[str, WorkerRegistryRecord]) -> None:
        """Persist registry records without storing full worker profiles."""
        normalized_records = []
        for worker_id, record in sorted(records.items()):
            validate_worker_id(worker_id)
            if worker_id != record.worker_id:
                raise WorkerRegistryError("registry key does not match worker_id")
            if record.profile_path is None:
                raise WorkerRegistryError("profile_path must be set")
            _validate_profile_path(self.root, record.profile_path)
            normalized_records.append(worker_registry_record_to_dict(record))

        atomic_json_write(
            self.registry_path,
            {
                "schema_version": WORKER_REGISTRY_SCHEMA_VERSION,
                "workers": normalized_records,
            },
        )

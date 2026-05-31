"""Clearable task-state contract for managed worker agents."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping

from .profile import validate_worker_id


WORKER_TASK_SCHEMA_VERSION = 1


class WorkerTaskError(ValueError):
    """Raised when a worker task state file violates its runtime contract."""


class WorkerTaskStatus(StrEnum):
    """Runtime status for one clearable worker task."""

    DRAFT = "draft"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_INPUT = "waiting_for_input"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    FAILED = "failed"
    SUCCEEDED = "succeeded"
    EXPIRED = "expired"


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise WorkerTaskError(f"{field_name} must be an object")
    return value


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise WorkerTaskError(f"{field_name} must be a non-empty string")
    return value


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, field_name)


def _non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise WorkerTaskError(f"{field_name} must be a non-negative integer")
    return value


def _optional_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    return dict(_require_mapping(value, field_name))


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise WorkerTaskError(f"{field_name} must be a list of strings")
    result = tuple(value)
    if any(not isinstance(item, str) or not item for item in result):
        raise WorkerTaskError(f"{field_name} must be a list of non-empty strings")
    return result


def _reject_unknown_fields(
    data: Mapping[str, Any], allowed_fields: set[str], field_name: str
) -> None:
    unknown_fields = sorted(set(data) - allowed_fields)
    if unknown_fields:
        joined = ", ".join(unknown_fields)
        raise WorkerTaskError(f"{field_name} has unknown fields: {joined}")


def validate_task_id(task_id: str) -> str:
    """Return a task id after rejecting values that could escape its directory."""
    if not task_id or task_id in {".", ".."}:
        raise WorkerTaskError("task_id must be a non-empty path segment")
    if "/" in task_id or "\\" in task_id:
        raise WorkerTaskError("task_id must not contain path separators")
    return task_id


def utc_timestamp() -> str:
    """Return a stable UTC timestamp for task audit fields."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _coerce_status(value: WorkerTaskStatus | str) -> WorkerTaskStatus:
    if isinstance(value, WorkerTaskStatus):
        return value
    raw_status = _require_string(value, "status")
    try:
        return WorkerTaskStatus(raw_status)
    except ValueError as exc:
        raise WorkerTaskError(f"Unknown worker task status: {raw_status!r}") from exc


@dataclass(frozen=True)
class WorkerTaskState:
    """Current runtime snapshot for one worker task.

    Task state is clearable runtime data. It intentionally stores only compact
    profile summaries and task-local references, never private memory or
    credentials from the durable worker profile.
    """

    task_id: str
    worker_id: str
    title: str
    objective: str
    created_by: str
    created_at: str
    updated_at: str
    status: WorkerTaskStatus = WorkerTaskStatus.DRAFT
    schema_version: int = WORKER_TASK_SCHEMA_VERSION
    updated_by: str | None = None
    input_summary: str | None = None
    origin_thread_id: str | None = None
    report_to_thread_id: str | None = None
    assigned_worker_status: str | None = None
    profile_snapshot: Mapping[str, Any] = field(default_factory=dict)
    budgets: Mapping[str, Any] = field(default_factory=dict)
    workspace: Mapping[str, Any] = field(default_factory=dict)
    runtime: Mapping[str, Any] = field(default_factory=dict)
    progress: Mapping[str, Any] = field(default_factory=dict)
    current_step: str | None = None
    cancellation: Mapping[str, Any] = field(default_factory=dict)
    failure: Mapping[str, Any] = field(default_factory=dict)
    result: Mapping[str, Any] = field(default_factory=dict)
    artifacts: tuple[str, ...] = ()
    requests: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_task_id(self.task_id)
        validate_worker_id(self.worker_id)
        object.__setattr__(self, "status", _coerce_status(self.status))
        if self.schema_version != WORKER_TASK_SCHEMA_VERSION:
            raise WorkerTaskError(
                f"Unsupported worker task schema_version: {self.schema_version!r}"
            )


TERMINAL_TASK_STATUSES = frozenset(
    {
        WorkerTaskStatus.CANCELLED,
        WorkerTaskStatus.FAILED,
        WorkerTaskStatus.SUCCEEDED,
        WorkerTaskStatus.EXPIRED,
    }
)

_ALLOWED_TASK_STATUS_TRANSITIONS = {
    WorkerTaskStatus.DRAFT: {
        WorkerTaskStatus.QUEUED,
        WorkerTaskStatus.CANCELLED,
        WorkerTaskStatus.EXPIRED,
    },
    WorkerTaskStatus.QUEUED: {
        WorkerTaskStatus.RUNNING,
        WorkerTaskStatus.WAITING_FOR_INPUT,
        WorkerTaskStatus.WAITING_FOR_APPROVAL,
        WorkerTaskStatus.CANCELLED,
        WorkerTaskStatus.EXPIRED,
    },
    WorkerTaskStatus.RUNNING: {
        WorkerTaskStatus.WAITING_FOR_INPUT,
        WorkerTaskStatus.WAITING_FOR_APPROVAL,
        WorkerTaskStatus.CANCELLING,
        WorkerTaskStatus.FAILED,
        WorkerTaskStatus.SUCCEEDED,
        WorkerTaskStatus.EXPIRED,
    },
    WorkerTaskStatus.WAITING_FOR_INPUT: {
        WorkerTaskStatus.QUEUED,
        WorkerTaskStatus.RUNNING,
        WorkerTaskStatus.CANCELLING,
        WorkerTaskStatus.FAILED,
        WorkerTaskStatus.EXPIRED,
    },
    WorkerTaskStatus.WAITING_FOR_APPROVAL: {
        WorkerTaskStatus.QUEUED,
        WorkerTaskStatus.RUNNING,
        WorkerTaskStatus.CANCELLING,
        WorkerTaskStatus.FAILED,
        WorkerTaskStatus.EXPIRED,
    },
    WorkerTaskStatus.CANCELLING: {
        WorkerTaskStatus.CANCELLED,
        WorkerTaskStatus.FAILED,
    },
    WorkerTaskStatus.CANCELLED: set(),
    WorkerTaskStatus.FAILED: set(),
    WorkerTaskStatus.SUCCEEDED: set(),
    WorkerTaskStatus.EXPIRED: set(),
}


def transition_task_status(
    state: WorkerTaskState,
    target_status: WorkerTaskStatus | str,
    *,
    updated_by: str,
    status_reason: str | None = None,
    now: str | None = None,
    result: Mapping[str, Any] | None = None,
) -> WorkerTaskState:
    """Return a task state with an allowed lifecycle transition applied."""
    target_status = _coerce_status(target_status)
    changed_at = now or utc_timestamp()
    if state.status == target_status:
        return _apply_status_metadata(
            state,
            target_status=target_status,
            changed_at=changed_at,
            updated_by=updated_by,
            status_reason=status_reason,
            result=result,
        )

    allowed_targets = _ALLOWED_TASK_STATUS_TRANSITIONS[state.status]
    if target_status not in allowed_targets:
        raise WorkerTaskError(
            f"Cannot transition task {state.task_id!r} "
            f"from {state.status.value!r} to {target_status.value!r}"
        )
    return _apply_status_metadata(
        state,
        target_status=target_status,
        changed_at=changed_at,
        updated_by=updated_by,
        status_reason=status_reason,
        result=result,
    )


def _apply_status_metadata(
    state: WorkerTaskState,
    *,
    target_status: WorkerTaskStatus,
    changed_at: str,
    updated_by: str,
    status_reason: str | None,
    result: Mapping[str, Any] | None,
) -> WorkerTaskState:
    failure = dict(state.failure)
    cancellation = dict(state.cancellation)
    result_data = dict(state.result)
    if result is not None:
        result_data.update(result)
    if target_status == WorkerTaskStatus.FAILED:
        failure.update({"failed_at": changed_at, "failed_by": updated_by})
        if status_reason is not None:
            failure["reason"] = status_reason
    if target_status == WorkerTaskStatus.CANCELLING:
        cancellation.update({"requested_at": changed_at, "requested_by": updated_by})
        if status_reason is not None:
            cancellation["reason"] = status_reason
    if target_status == WorkerTaskStatus.CANCELLED:
        cancellation.update({"cancelled_at": changed_at, "cancelled_by": updated_by})
        if status_reason is not None:
            cancellation["reason"] = status_reason
    if target_status == WorkerTaskStatus.SUCCEEDED:
        result_data.update({"completed_at": changed_at, "completed_by": updated_by})
        if status_reason is not None:
            result_data["summary"] = status_reason
    if target_status == WorkerTaskStatus.EXPIRED:
        failure.update({"expired_at": changed_at, "expired_by": updated_by})
        if status_reason is not None:
            failure["reason"] = status_reason
    return replace(
        state,
        status=target_status,
        updated_at=changed_at,
        updated_by=updated_by,
        failure=failure,
        cancellation=cancellation,
        result=result_data,
    )


_TASK_STATE_FIELDS = {
    "task_id",
    "schema_version",
    "worker_id",
    "created_by",
    "created_at",
    "updated_at",
    "updated_by",
    "status",
    "title",
    "objective",
    "input_summary",
    "origin_thread_id",
    "report_to_thread_id",
    "assigned_worker_status",
    "profile_snapshot",
    "budgets",
    "workspace",
    "runtime",
    "progress",
    "current_step",
    "cancellation",
    "failure",
    "result",
    "artifacts",
    "requests",
    "tags",
    "metadata",
}


def worker_task_state_from_dict(data: Mapping[str, Any]) -> WorkerTaskState:
    """Build a task state from a strict dictionary contract."""
    data = _require_mapping(data, "worker task state")
    _reject_unknown_fields(data, _TASK_STATE_FIELDS, "worker task state")

    missing_fields = [
        field_name
        for field_name in (
            "task_id",
            "schema_version",
            "worker_id",
            "created_by",
            "created_at",
            "updated_at",
            "status",
            "title",
            "objective",
        )
        if field_name not in data
    ]
    if missing_fields:
        joined = ", ".join(missing_fields)
        raise WorkerTaskError(f"worker task state is missing fields: {joined}")

    schema_version = _non_negative_int(data["schema_version"], "schema_version")
    if schema_version != WORKER_TASK_SCHEMA_VERSION:
        raise WorkerTaskError(
            f"Unsupported worker task schema_version: {schema_version!r}"
        )

    return WorkerTaskState(
        task_id=validate_task_id(_require_string(data["task_id"], "task_id")),
        schema_version=schema_version,
        worker_id=validate_worker_id(_require_string(data["worker_id"], "worker_id")),
        created_by=_require_string(data["created_by"], "created_by"),
        created_at=_require_string(data["created_at"], "created_at"),
        updated_at=_require_string(data["updated_at"], "updated_at"),
        updated_by=_optional_string(data.get("updated_by"), "updated_by"),
        status=_coerce_status(data["status"]),
        title=_require_string(data["title"], "title"),
        objective=_require_string(data["objective"], "objective"),
        input_summary=_optional_string(data.get("input_summary"), "input_summary"),
        origin_thread_id=_optional_string(
            data.get("origin_thread_id"), "origin_thread_id"
        ),
        report_to_thread_id=_optional_string(
            data.get("report_to_thread_id"), "report_to_thread_id"
        ),
        assigned_worker_status=_optional_string(
            data.get("assigned_worker_status"), "assigned_worker_status"
        ),
        profile_snapshot=_optional_mapping(
            data.get("profile_snapshot"), "profile_snapshot"
        ),
        budgets=_optional_mapping(data.get("budgets"), "budgets"),
        workspace=_optional_mapping(data.get("workspace"), "workspace"),
        runtime=_optional_mapping(data.get("runtime"), "runtime"),
        progress=_optional_mapping(data.get("progress"), "progress"),
        current_step=_optional_string(data.get("current_step"), "current_step"),
        cancellation=_optional_mapping(data.get("cancellation"), "cancellation"),
        failure=_optional_mapping(data.get("failure"), "failure"),
        result=_optional_mapping(data.get("result"), "result"),
        artifacts=_string_tuple(data.get("artifacts", ()), "artifacts"),
        requests=_string_tuple(data.get("requests", ()), "requests"),
        tags=_string_tuple(data.get("tags", ()), "tags"),
        metadata=_optional_mapping(data.get("metadata"), "metadata"),
    )


def worker_task_state_to_dict(state: WorkerTaskState) -> dict[str, Any]:
    """Convert a task state to deterministic JSON-ready data."""
    return {
        "task_id": state.task_id,
        "schema_version": state.schema_version,
        "worker_id": state.worker_id,
        "created_by": state.created_by,
        "created_at": state.created_at,
        "updated_at": state.updated_at,
        "updated_by": state.updated_by,
        "status": state.status.value,
        "title": state.title,
        "objective": state.objective,
        "input_summary": state.input_summary,
        "origin_thread_id": state.origin_thread_id,
        "report_to_thread_id": state.report_to_thread_id,
        "assigned_worker_status": state.assigned_worker_status,
        "profile_snapshot": dict(state.profile_snapshot),
        "budgets": dict(state.budgets),
        "workspace": dict(state.workspace),
        "runtime": dict(state.runtime),
        "progress": dict(state.progress),
        "current_step": state.current_step,
        "cancellation": dict(state.cancellation),
        "failure": dict(state.failure),
        "result": dict(state.result),
        "artifacts": list(state.artifacts),
        "requests": list(state.requests),
        "tags": list(state.tags),
        "metadata": dict(state.metadata),
    }


def dump_worker_task_state_json(state: WorkerTaskState) -> str:
    """Serialize a task state with stable formatting."""
    return json.dumps(worker_task_state_to_dict(state), indent=2, sort_keys=True) + "\n"


def load_worker_task_state_json(raw_json: str) -> WorkerTaskState:
    """Load and validate a task state from JSON text."""
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise WorkerTaskError(f"Invalid worker task state JSON: {exc.msg}") from exc
    return worker_task_state_from_dict(data)

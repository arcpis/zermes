"""Task-local event, request, and result records."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .task_state import WorkerTaskError, validate_task_id


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


def _mapping_tuple(value: Any, field_name: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        raise WorkerTaskError(f"{field_name} must be a list of objects")
    return tuple(_require_mapping(item, field_name) for item in value)


def _reject_unknown_fields(
    data: Mapping[str, Any], allowed_fields: set[str], field_name: str
) -> None:
    unknown_fields = sorted(set(data) - allowed_fields)
    if unknown_fields:
        joined = ", ".join(unknown_fields)
        raise WorkerTaskError(f"{field_name} has unknown fields: {joined}")


@dataclass(frozen=True)
class WorkerTaskEvent:
    """Append-only event record for a task-local timeline."""

    event_id: str
    task_id: str
    event_type: str
    created_at: str
    source: str
    summary: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_task_id(self.task_id)


@dataclass(frozen=True)
class WorkerTaskRequest:
    """Task-local request for approval, input, or other coordinator action."""

    request_id: str
    task_id: str
    request_type: str
    status: str
    created_at: str
    summary: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_task_id(self.task_id)


@dataclass(frozen=True)
class WorkerTaskResult:
    """Compact task result stored in clearable runtime data."""

    task_id: str
    summary: str
    artifact_paths: tuple[str, ...] = ()
    manifest_candidates: tuple[Mapping[str, Any], ...] = ()
    memory_candidates: tuple[Mapping[str, Any], ...] = ()
    audit_summary_candidates: tuple[Mapping[str, Any], ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_task_id(self.task_id)


_EVENT_FIELDS = {
    "event_id",
    "task_id",
    "event_type",
    "created_at",
    "source",
    "summary",
    "metadata",
}

_REQUEST_FIELDS = {
    "request_id",
    "task_id",
    "request_type",
    "status",
    "created_at",
    "summary",
    "metadata",
}

_RESULT_FIELDS = {
    "task_id",
    "summary",
    "artifact_paths",
    "manifest_candidates",
    "memory_candidates",
    "audit_summary_candidates",
    "metadata",
}


def task_event_from_dict(data: Mapping[str, Any]) -> WorkerTaskEvent:
    data = _require_mapping(data, "task event")
    _reject_unknown_fields(data, _EVENT_FIELDS, "task event")
    return WorkerTaskEvent(
        event_id=_require_string(data.get("event_id"), "event_id"),
        task_id=validate_task_id(_require_string(data.get("task_id"), "task_id")),
        event_type=_require_string(data.get("event_type"), "event_type"),
        created_at=_require_string(data.get("created_at"), "created_at"),
        source=_require_string(data.get("source"), "source"),
        summary=_require_string(data.get("summary"), "summary"),
        metadata=_optional_mapping(data.get("metadata"), "metadata"),
    )


def task_event_to_dict(event: WorkerTaskEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "task_id": event.task_id,
        "event_type": event.event_type,
        "created_at": event.created_at,
        "source": event.source,
        "summary": event.summary,
        "metadata": dict(event.metadata),
    }


def task_request_from_dict(data: Mapping[str, Any]) -> WorkerTaskRequest:
    data = _require_mapping(data, "task request")
    _reject_unknown_fields(data, _REQUEST_FIELDS, "task request")
    return WorkerTaskRequest(
        request_id=_require_string(data.get("request_id"), "request_id"),
        task_id=validate_task_id(_require_string(data.get("task_id"), "task_id")),
        request_type=_require_string(data.get("request_type"), "request_type"),
        status=_require_string(data.get("status"), "status"),
        created_at=_require_string(data.get("created_at"), "created_at"),
        summary=_require_string(data.get("summary"), "summary"),
        metadata=_optional_mapping(data.get("metadata"), "metadata"),
    )


def task_request_to_dict(request: WorkerTaskRequest) -> dict[str, Any]:
    return {
        "request_id": request.request_id,
        "task_id": request.task_id,
        "request_type": request.request_type,
        "status": request.status,
        "created_at": request.created_at,
        "summary": request.summary,
        "metadata": dict(request.metadata),
    }


def task_result_from_dict(data: Mapping[str, Any]) -> WorkerTaskResult:
    data = _require_mapping(data, "task result")
    _reject_unknown_fields(data, _RESULT_FIELDS, "task result")
    return WorkerTaskResult(
        task_id=validate_task_id(_require_string(data.get("task_id"), "task_id")),
        summary=_require_string(data.get("summary"), "summary"),
        artifact_paths=_string_tuple(data.get("artifact_paths", ()), "artifact_paths"),
        manifest_candidates=_mapping_tuple(
            data.get("manifest_candidates", ()), "manifest_candidates"
        ),
        memory_candidates=_mapping_tuple(
            data.get("memory_candidates", ()), "memory_candidates"
        ),
        audit_summary_candidates=_mapping_tuple(
            data.get("audit_summary_candidates", ()), "audit_summary_candidates"
        ),
        metadata=_optional_mapping(data.get("metadata"), "metadata"),
    )


def task_result_to_dict(result: WorkerTaskResult) -> dict[str, Any]:
    return {
        "task_id": result.task_id,
        "summary": result.summary,
        "artifact_paths": list(result.artifact_paths),
        "manifest_candidates": [dict(item) for item in result.manifest_candidates],
        "memory_candidates": [dict(item) for item in result.memory_candidates],
        "audit_summary_candidates": [
            dict(item) for item in result.audit_summary_candidates
        ],
        "metadata": dict(result.metadata),
    }

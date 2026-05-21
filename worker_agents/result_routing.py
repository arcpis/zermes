"""Classify managed runtime results before routing them to side effects."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from .message_router import (
    ChatMessageType,
    ChatParticipantKind,
    ChatParticipantRef,
    MessageRouter,
    MessageRouterError,
    WorkerMessageEnvelope,
)
from .runtime_contract import (
    RuntimeErrorInfo,
    RuntimeResult,
    RuntimeState,
    RuntimeType,
    runtime_artifact_ref_to_dict,
    runtime_error_to_dict,
    runtime_memory_proposal_to_dict,
    runtime_safety_request_to_dict,
)
from .task_state import validate_task_id


RESULT_ROUTING_SCHEMA_VERSION = 1


class ResultRoutingError(ValueError):
    """Raised when a runtime result cannot be safely prepared for routing."""


class ResultRouteItemKind(StrEnum):
    """Destinations implied by one classified runtime result item."""

    PUBLIC_MESSAGE = "public_message"
    SILENT_SUMMARY = "silent_summary"
    APPROVAL_REQUEST = "approval_request"
    SAFETY_REQUEST = "safety_request"
    ARTIFACT_MANIFEST = "artifact_manifest"
    MEMORY_PROPOSAL = "memory_proposal"
    DEPARTMENT_ASSET_PROPOSAL = "department_asset_proposal"
    LEARNING_PROPOSAL = "learning_proposal"
    FAILURE_REPORT = "failure_report"
    AUDIT_SUMMARY = "audit_summary"


class ResultRouteVisibility(StrEnum):
    """Visibility expected before the item is handed to a concrete router."""

    USER_VISIBLE = "user_visible"
    MAIN_AGENT_REVIEW = "main_agent_review"
    PENDING_REVIEW = "pending_review"
    TASK_AUDIT = "task_audit"


class ResultRouteSensitivity(StrEnum):
    """Low-cardinality sensitivity labels for route item consumers."""

    LOW = "low"
    REVIEW_REQUIRED = "review_required"


_SENSITIVE_FIELD_NAMES = frozenset(
    {
        "api_key",
        "complete_transcript",
        "credential",
        "credentials",
        "environment",
        "env",
        "full_transcript",
        "private_memory",
        "private_memory_text",
        "raw_output",
        "raw_stderr",
        "raw_stdout",
        "raw_transcript",
        "refresh_token",
        "secret",
        "stderr",
        "stdout",
        "token",
    }
)


@dataclass(frozen=True)
class ResultRouteItem:
    """One low-sensitivity item ready for a specific routing layer."""

    route_item_id: str
    source_runtime_session_id: str
    source_worker_id: str
    source_runtime_type: RuntimeType | str
    task_id: str
    kind: ResultRouteItemKind | str
    visibility: ResultRouteVisibility | str
    payload: Mapping[str, Any] = field(default_factory=dict)
    sensitivity: ResultRouteSensitivity | str = ResultRouteSensitivity.LOW
    requires_main_agent_review: bool = False
    audit_summary: str = ""
    schema_version: int = RESULT_ROUTING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        _require_string(self.route_item_id, "route_item_id")
        _require_string(self.source_runtime_session_id, "source_runtime_session_id")
        _require_string(self.source_worker_id, "source_worker_id")
        object.__setattr__(
            self, "source_runtime_type", _runtime_type(self.source_runtime_type)
        )
        validate_task_id(self.task_id)
        object.__setattr__(self, "kind", _route_kind(self.kind))
        object.__setattr__(self, "visibility", _visibility(self.visibility))
        object.__setattr__(self, "sensitivity", _sensitivity(self.sensitivity))
        payload = dict(_require_mapping(self.payload, "payload"))
        _reject_sensitive_payload(payload, "payload")
        object.__setattr__(self, "payload", payload)
        if not isinstance(self.requires_main_agent_review, bool):
            raise ResultRoutingError("requires_main_agent_review must be a boolean")
        _require_string(self.audit_summary, "audit_summary")


@dataclass(frozen=True)
class RuntimeResultClassification:
    """Classified result plus warnings before any side-effect routing occurs."""

    source_result_ref: str
    route_items: tuple[ResultRouteItem, ...]
    rejected_items: tuple[Mapping[str, Any], ...] = ()
    classification_warnings: tuple[str, ...] = ()
    audit_summary: str = ""
    schema_version: int = RESULT_ROUTING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        _require_string(self.source_result_ref, "source_result_ref")
        if not isinstance(self.route_items, tuple):
            raise ResultRoutingError("route_items must be a tuple")
        if any(not isinstance(item, ResultRouteItem) for item in self.route_items):
            raise ResultRoutingError("route_items must contain ResultRouteItem records")
        object.__setattr__(self, "rejected_items", tuple(self.rejected_items))
        object.__setattr__(
            self, "classification_warnings", tuple(self.classification_warnings)
        )
        _require_string(self.audit_summary, "audit_summary")
        for warning in self.classification_warnings:
            _require_string(warning, "classification_warnings")
        for item in self.rejected_items:
            _reject_sensitive_payload(dict(item), "rejected_items")


@dataclass(frozen=True)
class MessageRouterResultRoute:
    """Messages appended through the managed worker Message Router."""

    delivered_messages: tuple[WorkerMessageEnvelope, ...]
    skipped_route_item_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.delivered_messages, tuple):
            raise ResultRoutingError("delivered_messages must be a tuple")
        if any(
            not isinstance(message, WorkerMessageEnvelope)
            for message in self.delivered_messages
        ):
            raise ResultRoutingError(
                "delivered_messages must contain WorkerMessageEnvelope records"
            )
        object.__setattr__(
            self, "skipped_route_item_ids", tuple(self.skipped_route_item_ids)
        )
        for item_id in self.skipped_route_item_ids:
            _require_string(item_id, "skipped_route_item_ids")


def classify_runtime_result(
    result: RuntimeResult, *, source_result_ref: str | None = None
) -> RuntimeResultClassification:
    """Convert one terminal runtime result into low-sensitivity route items."""

    if not isinstance(result, RuntimeResult):
        raise ResultRoutingError("result must be a RuntimeResult")
    result_ref = source_result_ref or result.request_id
    _require_string(result_ref, "source_result_ref")
    items: list[ResultRouteItem] = []
    sequence = 1

    def add_item(
        kind: ResultRouteItemKind,
        visibility: ResultRouteVisibility,
        payload: Mapping[str, Any],
        *,
        sensitivity: ResultRouteSensitivity = ResultRouteSensitivity.LOW,
        review: bool = False,
        audit_summary: str = "",
    ) -> None:
        nonlocal sequence
        items.append(
            ResultRouteItem(
                route_item_id=f"{result.request_id}-{kind.value}-{sequence}",
                source_runtime_session_id=result.request_id,
                source_worker_id=result.worker_id,
                source_runtime_type=result.runtime_type,
                task_id=result.task_id,
                kind=kind,
                visibility=visibility,
                payload=payload,
                sensitivity=sensitivity,
                requires_main_agent_review=review,
                audit_summary=audit_summary or _default_audit_summary(result),
            )
        )
        sequence += 1

    if result.public_message:
        add_item(
            ResultRouteItemKind.PUBLIC_MESSAGE,
            ResultRouteVisibility.USER_VISIBLE,
            {"body_preview": result.public_message},
            audit_summary="Runtime produced a user-visible message.",
        )
    if result.internal_summary:
        add_item(
            ResultRouteItemKind.SILENT_SUMMARY,
            ResultRouteVisibility.TASK_AUDIT,
            {"summary": result.internal_summary},
            audit_summary="Runtime produced an internal summary.",
        )
    for artifact in result.artifact_refs:
        add_item(
            ResultRouteItemKind.ARTIFACT_MANIFEST,
            ResultRouteVisibility.PENDING_REVIEW,
            runtime_artifact_ref_to_dict(artifact),
            sensitivity=ResultRouteSensitivity.REVIEW_REQUIRED,
            review=True,
            audit_summary="Runtime produced an artifact manifest candidate.",
        )
    for proposal in result.memory_proposals:
        add_item(
            ResultRouteItemKind.MEMORY_PROPOSAL,
            ResultRouteVisibility.PENDING_REVIEW,
            runtime_memory_proposal_to_dict(proposal),
            sensitivity=ResultRouteSensitivity.REVIEW_REQUIRED,
            review=True,
            audit_summary="Runtime produced a memory proposal.",
        )
    for proposal in result.department_asset_proposals:
        add_item(
            ResultRouteItemKind.DEPARTMENT_ASSET_PROPOSAL,
            ResultRouteVisibility.PENDING_REVIEW,
            runtime_memory_proposal_to_dict(proposal),
            sensitivity=ResultRouteSensitivity.REVIEW_REQUIRED,
            review=True,
            audit_summary="Runtime produced a department asset proposal.",
        )
    for request in result.safety_requests:
        add_item(
            ResultRouteItemKind.SAFETY_REQUEST,
            ResultRouteVisibility.MAIN_AGENT_REVIEW,
            runtime_safety_request_to_dict(request),
            sensitivity=ResultRouteSensitivity.REVIEW_REQUIRED,
            review=True,
            audit_summary="Runtime produced a safety review request.",
        )
    if result.audit_summary:
        add_item(
            ResultRouteItemKind.AUDIT_SUMMARY,
            ResultRouteVisibility.TASK_AUDIT,
            {"summary": result.audit_summary},
            audit_summary="Runtime produced an audit summary.",
        )
    if _needs_failure_report(result):
        add_item(
            ResultRouteItemKind.FAILURE_REPORT,
            ResultRouteVisibility.USER_VISIBLE,
            _failure_payload(result),
            audit_summary="Runtime ended with a failure-like terminal state.",
        )
    return RuntimeResultClassification(
        source_result_ref=result_ref,
        route_items=tuple(items),
        audit_summary=_classification_audit_summary(result, len(items)),
    )


def route_user_visible_result_messages(
    *,
    router: MessageRouter,
    classification: RuntimeResultClassification,
    thread_id: str,
    created_at: str,
    parent_worker_id: str | None = None,
) -> MessageRouterResultRoute:
    """Append user-visible result items through the managed Message Router."""

    if not isinstance(router, MessageRouter):
        raise ResultRoutingError("router must be a MessageRouter")
    if not isinstance(classification, RuntimeResultClassification):
        raise ResultRoutingError("classification must be a RuntimeResultClassification")
    _require_string(thread_id, "thread_id")
    _require_string(created_at, "created_at")
    sender_worker_id = parent_worker_id or _single_source_worker(classification)
    if parent_worker_id is not None:
        _require_string(parent_worker_id, "parent_worker_id")

    delivered: list[WorkerMessageEnvelope] = []
    skipped: list[str] = []
    for item in classification.route_items:
        if item.kind not in {
            ResultRouteItemKind.PUBLIC_MESSAGE,
            ResultRouteItemKind.FAILURE_REPORT,
        }:
            skipped.append(item.route_item_id)
            continue
        if item.visibility != ResultRouteVisibility.USER_VISIBLE:
            skipped.append(item.route_item_id)
            continue
        message = _message_for_route_item(
            item,
            thread_id=thread_id,
            sender_worker_id=sender_worker_id,
            created_at=created_at,
        )
        try:
            delivered.append(router.append_message(message))
        except MessageRouterError as exc:
            raise ResultRoutingError(str(exc)) from exc
    return MessageRouterResultRoute(
        delivered_messages=tuple(delivered),
        skipped_route_item_ids=tuple(skipped),
    )


def route_item_to_dict(item: ResultRouteItem) -> dict[str, Any]:
    """Return a JSON-safe representation of one classified route item."""

    return {
        "schema_version": item.schema_version,
        "route_item_id": item.route_item_id,
        "source_runtime_session_id": item.source_runtime_session_id,
        "source_worker_id": item.source_worker_id,
        "source_runtime_type": item.source_runtime_type.value,
        "task_id": item.task_id,
        "kind": item.kind.value,
        "visibility": item.visibility.value,
        "payload": dict(item.payload),
        "sensitivity": item.sensitivity.value,
        "requires_main_agent_review": item.requires_main_agent_review,
        "audit_summary": item.audit_summary,
    }


def runtime_result_classification_to_dict(
    classification: RuntimeResultClassification,
) -> dict[str, Any]:
    """Return a JSON-safe representation of one classification result."""

    return {
        "schema_version": classification.schema_version,
        "source_result_ref": classification.source_result_ref,
        "route_items": [
            route_item_to_dict(item) for item in classification.route_items
        ],
        "rejected_items": [dict(item) for item in classification.rejected_items],
        "classification_warnings": list(classification.classification_warnings),
        "audit_summary": classification.audit_summary,
    }


def message_router_result_route_to_dict(
    result: MessageRouterResultRoute,
) -> dict[str, Any]:
    """Return an audit-safe summary of Message Router routing side effects."""

    return {
        "delivered_message_ids": [
            message.message_id for message in result.delivered_messages
        ],
        "skipped_route_item_ids": list(result.skipped_route_item_ids),
    }


def _needs_failure_report(result: RuntimeResult) -> bool:
    return bool(
        result.partial_success
        or result.final_state
        in {RuntimeState.FAILED, RuntimeState.TIMED_OUT, RuntimeState.CANCELLED}
    )


def _failure_payload(result: RuntimeResult) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "final_state": result.final_state.value,
        "partial_success": result.partial_success,
    }
    if result.error is not None:
        payload["error"] = _safe_error_payload(result.error)
    return payload


def _safe_error_payload(error: RuntimeErrorInfo) -> dict[str, Any]:
    data = runtime_error_to_dict(error)
    data.pop("raw_error_ref", None)
    return data


def _single_source_worker(classification: RuntimeResultClassification) -> str:
    worker_ids = {item.source_worker_id for item in classification.route_items}
    if not worker_ids:
        raise ResultRoutingError("classification has no route items to send")
    if len(worker_ids) > 1:
        raise ResultRoutingError("classification contains multiple source workers")
    return next(iter(worker_ids))


def _message_for_route_item(
    item: ResultRouteItem,
    *,
    thread_id: str,
    sender_worker_id: str,
    created_at: str,
) -> WorkerMessageEnvelope:
    if item.kind == ResultRouteItemKind.PUBLIC_MESSAGE:
        body_preview = _require_string(
            item.payload.get("body_preview"), "public message body_preview"
        )
        message_type = ChatMessageType.NORMAL
    elif item.kind == ResultRouteItemKind.FAILURE_REPORT:
        body_preview = _failure_body_preview(item.payload)
        message_type = ChatMessageType.SUMMARY
    else:
        raise ResultRoutingError(f"route item is not user-visible: {item.kind.value}")
    return WorkerMessageEnvelope(
        message_id=f"{item.route_item_id}-message",
        thread_id=thread_id,
        sender=ChatParticipantRef(ChatParticipantKind.WORKER, sender_worker_id),
        message_type=message_type,
        created_at=created_at,
        body_preview=body_preview,
        audit_summary=item.audit_summary,
    )


def _failure_body_preview(payload: Mapping[str, Any]) -> str:
    error = payload.get("error")
    if isinstance(error, Mapping) and error.get("safe_summary"):
        return _require_string(error.get("safe_summary"), "failure safe_summary")
    final_state = _require_string(payload.get("final_state"), "final_state")
    return f"Runtime finished with state: {final_state}."


def _default_audit_summary(result: RuntimeResult) -> str:
    return f"Runtime {result.request_id} ended as {result.final_state.value}."


def _classification_audit_summary(result: RuntimeResult, item_count: int) -> str:
    return (
        f"Classified runtime result {result.request_id} into "
        f"{item_count} route item(s)."
    )


def _reject_sensitive_payload(value: Any, field_name: str) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_text = str(key)
            if key_text.lower() in _SENSITIVE_FIELD_NAMES:
                raise ResultRoutingError(f"{field_name} contains sensitive field: {key_text}")
            _reject_sensitive_payload(nested, f"{field_name}.{key_text}")
        return
    if isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _reject_sensitive_payload(nested, f"{field_name}[{index}]")


def _route_kind(value: ResultRouteItemKind | str) -> ResultRouteItemKind:
    raw = value.value if isinstance(value, ResultRouteItemKind) else value
    try:
        return ResultRouteItemKind(_require_string(raw, "kind"))
    except ValueError as exc:
        raise ResultRoutingError(f"Unknown route item kind: {raw!r}") from exc


def _visibility(value: ResultRouteVisibility | str) -> ResultRouteVisibility:
    raw = value.value if isinstance(value, ResultRouteVisibility) else value
    try:
        return ResultRouteVisibility(_require_string(raw, "visibility"))
    except ValueError as exc:
        raise ResultRoutingError(f"Unknown route visibility: {raw!r}") from exc


def _sensitivity(value: ResultRouteSensitivity | str) -> ResultRouteSensitivity:
    raw = value.value if isinstance(value, ResultRouteSensitivity) else value
    try:
        return ResultRouteSensitivity(_require_string(raw, "sensitivity"))
    except ValueError as exc:
        raise ResultRoutingError(f"Unknown route sensitivity: {raw!r}") from exc


def _runtime_type(value: RuntimeType | str) -> RuntimeType:
    raw = value.value if isinstance(value, RuntimeType) else value
    try:
        return RuntimeType(_require_string(raw, "source_runtime_type"))
    except ValueError as exc:
        raise ResultRoutingError(f"Unknown source_runtime_type: {raw!r}") from exc


def _require_schema_version(value: Any) -> None:
    if value != RESULT_ROUTING_SCHEMA_VERSION:
        raise ResultRoutingError(f"Unsupported result routing schema_version: {value!r}")


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ResultRoutingError(f"{field_name} must be an object")
    return value


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ResultRoutingError(f"{field_name} must be a non-empty string")
    return value

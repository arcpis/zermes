"""Classify managed runtime results before routing them to side effects."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
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


class RoutedProposalKind(StrEnum):
    """Pending proposal families produced by result routing."""

    ARTIFACT_MANIFEST = "artifact_manifest"
    WORKER_MEMORY = "worker_memory"
    DEPARTMENT_ASSET = "department_asset"
    WORKER_LEARNING = "worker_learning"


class RoutedApprovalKind(StrEnum):
    """Approval request families handled by main-agent governance."""

    TOOL_PERMISSION = "tool_permission"
    WORKSPACE_PERMISSION = "workspace_permission"
    MODEL_OR_BUDGET_INCREASE = "model_or_budget_increase"
    EXTERNAL_SERVICE_ACCESS = "external_service_access"
    DESTRUCTIVE_OR_IRREVERSIBLE_ACTION = "destructive_or_irreversible_action"
    USER_DECISION = "user_decision"
    SAFETY_REVIEW = "safety_review"


class RoutedApprovalStatus(StrEnum):
    """Lifecycle states for routed approval and safety requests."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


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
        if not isinstance(self.audit_summary, str):
            raise ResultRoutingError("audit_summary must be a string")


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


@dataclass(frozen=True)
class RoutedProposalRecord:
    """Pending proposal record; it is not an accepted long-term asset."""

    proposal_id: str
    proposal_kind: RoutedProposalKind | str
    source_route_item_id: str
    source_runtime_session_id: str
    source_worker_id: str
    task_id: str
    target_scope: str
    summary: str
    payload_ref: str | None = None
    review_status: str = "pending"
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int = RESULT_ROUTING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        _require_string(self.proposal_id, "proposal_id")
        object.__setattr__(self, "proposal_kind", _proposal_kind(self.proposal_kind))
        _require_string(self.source_route_item_id, "source_route_item_id")
        _require_string(self.source_runtime_session_id, "source_runtime_session_id")
        _require_string(self.source_worker_id, "source_worker_id")
        validate_task_id(self.task_id)
        _require_string(self.target_scope, "target_scope")
        _require_string(self.summary, "summary")
        _optional_string(self.payload_ref, "payload_ref")
        _require_string(self.review_status, "review_status")
        metadata = dict(_require_mapping(self.metadata, "metadata"))
        _reject_sensitive_payload(metadata, "metadata")
        object.__setattr__(self, "metadata", metadata)


@dataclass(frozen=True)
class ProposalAndManifestRoute:
    """Pending proposal records derived from route items."""

    pending_proposals: tuple[RoutedProposalRecord, ...]
    skipped_route_item_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.pending_proposals, tuple):
            raise ResultRoutingError("pending_proposals must be a tuple")
        if any(
            not isinstance(proposal, RoutedProposalRecord)
            for proposal in self.pending_proposals
        ):
            raise ResultRoutingError(
                "pending_proposals must contain RoutedProposalRecord records"
            )
        object.__setattr__(
            self, "skipped_route_item_ids", tuple(self.skipped_route_item_ids)
        )
        for item_id in self.skipped_route_item_ids:
            _require_string(item_id, "skipped_route_item_ids")


@dataclass(frozen=True)
class RoutedApprovalRequest:
    """Pending governance request; it never grants access by itself."""

    approval_request_id: str
    approval_kind: RoutedApprovalKind | str
    source_route_item_id: str
    source_runtime_session_id: str
    source_worker_id: str
    task_id: str
    requested_capability: str
    reason: str
    risk_summary: str
    required_approver: str
    status: RoutedApprovalStatus | str = RoutedApprovalStatus.PENDING
    expires_at: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int = RESULT_ROUTING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        _require_string(self.approval_request_id, "approval_request_id")
        object.__setattr__(self, "approval_kind", _approval_kind(self.approval_kind))
        _require_string(self.source_route_item_id, "source_route_item_id")
        _require_string(self.source_runtime_session_id, "source_runtime_session_id")
        _require_string(self.source_worker_id, "source_worker_id")
        validate_task_id(self.task_id)
        _require_string(self.requested_capability, "requested_capability")
        _require_string(self.reason, "reason")
        _require_string(self.risk_summary, "risk_summary")
        _require_string(self.required_approver, "required_approver")
        object.__setattr__(self, "status", _approval_status(self.status))
        _optional_string(self.expires_at, "expires_at")
        metadata = dict(_require_mapping(self.metadata, "metadata"))
        _reject_sensitive_payload(metadata, "metadata")
        object.__setattr__(self, "metadata", metadata)
        if self.status == RoutedApprovalStatus.APPROVED:
            raise ResultRoutingError("approval routing cannot create approved requests")


@dataclass(frozen=True)
class ApprovalAndSafetyRoute:
    """Pending approval and safety requests derived from route items."""

    pending_requests: tuple[RoutedApprovalRequest, ...]
    skipped_route_item_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.pending_requests, tuple):
            raise ResultRoutingError("pending_requests must be a tuple")
        if any(
            not isinstance(request, RoutedApprovalRequest)
            for request in self.pending_requests
        ):
            raise ResultRoutingError(
                "pending_requests must contain RoutedApprovalRequest records"
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


def route_pending_proposals_and_manifests(
    classification: RuntimeResultClassification,
) -> ProposalAndManifestRoute:
    """Return pending proposal records without accepting long-term assets."""

    if not isinstance(classification, RuntimeResultClassification):
        raise ResultRoutingError("classification must be a RuntimeResultClassification")
    proposals: list[RoutedProposalRecord] = []
    skipped: list[str] = []
    for item in classification.route_items:
        if item.kind == ResultRouteItemKind.ARTIFACT_MANIFEST:
            proposals.append(_artifact_manifest_proposal(item))
        elif item.kind == ResultRouteItemKind.MEMORY_PROPOSAL:
            proposals.append(_memory_proposal(item))
        elif item.kind == ResultRouteItemKind.DEPARTMENT_ASSET_PROPOSAL:
            proposals.append(_department_asset_proposal(item))
        elif item.kind == ResultRouteItemKind.LEARNING_PROPOSAL:
            proposals.append(_learning_proposal(item))
        else:
            skipped.append(item.route_item_id)
    return ProposalAndManifestRoute(
        pending_proposals=tuple(proposals),
        skipped_route_item_ids=tuple(skipped),
    )


def route_approval_and_safety_requests(
    classification: RuntimeResultClassification,
) -> ApprovalAndSafetyRoute:
    """Return pending governance requests without granting new capability."""

    if not isinstance(classification, RuntimeResultClassification):
        raise ResultRoutingError("classification must be a RuntimeResultClassification")
    requests: list[RoutedApprovalRequest] = []
    skipped: list[str] = []
    for item in classification.route_items:
        if item.kind == ResultRouteItemKind.SAFETY_REQUEST:
            requests.append(_safety_approval_request(item))
        elif item.kind == ResultRouteItemKind.APPROVAL_REQUEST:
            requests.append(_approval_request(item))
        else:
            skipped.append(item.route_item_id)
    return ApprovalAndSafetyRoute(
        pending_requests=tuple(requests),
        skipped_route_item_ids=tuple(skipped),
    )


def approval_request_with_status(
    request: RoutedApprovalRequest,
    status: RoutedApprovalStatus | str,
    *,
    reason: str,
) -> RoutedApprovalRequest:
    """Return a status update record for a routed governance request."""

    if not isinstance(request, RoutedApprovalRequest):
        raise ResultRoutingError("request must be a RoutedApprovalRequest")
    status = _approval_status(status)
    if status == RoutedApprovalStatus.APPROVED:
        raise ResultRoutingError("approval status updates must come from governance")
    _require_string(reason, "reason")
    metadata = dict(request.metadata)
    metadata["status_reason"] = reason
    return RoutedApprovalRequest(
        approval_request_id=request.approval_request_id,
        approval_kind=request.approval_kind,
        source_route_item_id=request.source_route_item_id,
        source_runtime_session_id=request.source_runtime_session_id,
        source_worker_id=request.source_worker_id,
        task_id=request.task_id,
        requested_capability=request.requested_capability,
        reason=request.reason,
        risk_summary=request.risk_summary,
        required_approver=request.required_approver,
        status=status,
        expires_at=request.expires_at,
        metadata=metadata,
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


def routed_approval_request_to_dict(request: RoutedApprovalRequest) -> dict[str, Any]:
    """Return a JSON-safe pending governance request."""

    return {
        "schema_version": request.schema_version,
        "approval_request_id": request.approval_request_id,
        "approval_kind": request.approval_kind.value,
        "source_route_item_id": request.source_route_item_id,
        "source_runtime_session_id": request.source_runtime_session_id,
        "source_worker_id": request.source_worker_id,
        "task_id": request.task_id,
        "requested_capability": request.requested_capability,
        "reason": request.reason,
        "risk_summary": request.risk_summary,
        "required_approver": request.required_approver,
        "status": request.status.value,
        "expires_at": request.expires_at,
        "metadata": dict(request.metadata),
    }


def approval_and_safety_route_to_dict(result: ApprovalAndSafetyRoute) -> dict[str, Any]:
    """Return an audit-safe summary of governance request routing."""

    return {
        "pending_requests": [
            routed_approval_request_to_dict(request)
            for request in result.pending_requests
        ],
        "skipped_route_item_ids": list(result.skipped_route_item_ids),
    }


def routed_proposal_record_to_dict(proposal: RoutedProposalRecord) -> dict[str, Any]:
    """Return a JSON-safe pending proposal record."""

    return {
        "schema_version": proposal.schema_version,
        "proposal_id": proposal.proposal_id,
        "proposal_kind": proposal.proposal_kind.value,
        "source_route_item_id": proposal.source_route_item_id,
        "source_runtime_session_id": proposal.source_runtime_session_id,
        "source_worker_id": proposal.source_worker_id,
        "task_id": proposal.task_id,
        "target_scope": proposal.target_scope,
        "summary": proposal.summary,
        "payload_ref": proposal.payload_ref,
        "review_status": proposal.review_status,
        "metadata": dict(proposal.metadata),
    }


def proposal_and_manifest_route_to_dict(
    result: ProposalAndManifestRoute,
) -> dict[str, Any]:
    """Return an audit-safe summary of pending proposal routing."""

    return {
        "pending_proposals": [
            routed_proposal_record_to_dict(proposal)
            for proposal in result.pending_proposals
        ],
        "skipped_route_item_ids": list(result.skipped_route_item_ids),
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


def _safety_approval_request(item: ResultRouteItem) -> RoutedApprovalRequest:
    return RoutedApprovalRequest(
        approval_request_id=_require_string(item.payload.get("request_id"), "request_id"),
        approval_kind=RoutedApprovalKind.SAFETY_REVIEW,
        source_route_item_id=item.route_item_id,
        source_runtime_session_id=item.source_runtime_session_id,
        source_worker_id=item.source_worker_id,
        task_id=item.task_id,
        requested_capability=_require_string(
            item.payload.get("request_type"), "request_type"
        ),
        reason=_require_string(
            item.payload.get("user_visible_summary"), "user_visible_summary"
        ),
        risk_summary=_require_string(item.payload.get("risk_level"), "risk_level"),
        required_approver=_require_string(
            item.payload.get("required_approver"), "required_approver"
        ),
        metadata={"blocking": item.payload.get("blocking", True)},
    )


def _approval_request(item: ResultRouteItem) -> RoutedApprovalRequest:
    return RoutedApprovalRequest(
        approval_request_id=_require_string(item.payload.get("request_id"), "request_id"),
        approval_kind=_approval_kind(item.payload.get("approval_kind")),
        source_route_item_id=item.route_item_id,
        source_runtime_session_id=item.source_runtime_session_id,
        source_worker_id=item.source_worker_id,
        task_id=item.task_id,
        requested_capability=_require_string(
            item.payload.get("requested_capability"), "requested_capability"
        ),
        reason=_require_string(item.payload.get("reason"), "reason"),
        risk_summary=_require_string(item.payload.get("risk_summary"), "risk_summary"),
        required_approver=_require_string(
            item.payload.get("required_approver"), "required_approver"
        ),
        expires_at=_optional_string(item.payload.get("expires_at"), "expires_at"),
        metadata=dict(item.payload.get("metadata") or {}),
    )


def _artifact_manifest_proposal(item: ResultRouteItem) -> RoutedProposalRecord:
    manifest_ref = _require_string(item.payload.get("manifest_ref"), "manifest_ref")
    _validate_relative_payload_ref(manifest_ref, "manifest_ref")
    summary = _require_string(item.payload.get("summary"), "summary")
    return _proposal_record(
        item,
        proposal_id=f"{item.route_item_id}-proposal",
        proposal_kind=RoutedProposalKind.ARTIFACT_MANIFEST,
        target_scope=f"worker:{item.source_worker_id}:manifests",
        summary=summary,
        payload_ref=manifest_ref,
        metadata={
            "artifact_type": item.payload.get("artifact_type"),
            "retention_policy_ref": item.payload.get("retention_policy_ref"),
        },
    )


def _memory_proposal(item: ResultRouteItem) -> RoutedProposalRecord:
    return _proposal_record(
        item,
        proposal_id=_require_string(item.payload.get("proposal_id"), "proposal_id"),
        proposal_kind=RoutedProposalKind.WORKER_MEMORY,
        target_scope=_require_string(item.payload.get("target_scope"), "target_scope"),
        summary=_require_string(item.payload.get("redacted_summary"), "redacted_summary"),
        metadata={"review_reason": item.payload.get("review_reason")},
    )


def _department_asset_proposal(item: ResultRouteItem) -> RoutedProposalRecord:
    return _proposal_record(
        item,
        proposal_id=_require_string(item.payload.get("proposal_id"), "proposal_id"),
        proposal_kind=RoutedProposalKind.DEPARTMENT_ASSET,
        target_scope=_require_string(item.payload.get("target_scope"), "target_scope"),
        summary=_require_string(item.payload.get("redacted_summary"), "redacted_summary"),
        metadata={"review_reason": item.payload.get("review_reason")},
    )


def _learning_proposal(item: ResultRouteItem) -> RoutedProposalRecord:
    return _proposal_record(
        item,
        proposal_id=_require_string(item.payload.get("proposal_id"), "proposal_id"),
        proposal_kind=RoutedProposalKind.WORKER_LEARNING,
        target_scope=_require_string(item.payload.get("target_scope"), "target_scope"),
        summary=_require_string(item.payload.get("redacted_summary"), "redacted_summary"),
        metadata={"review_reason": item.payload.get("review_reason")},
    )


def _proposal_record(
    item: ResultRouteItem,
    *,
    proposal_id: str,
    proposal_kind: RoutedProposalKind,
    target_scope: str,
    summary: str,
    payload_ref: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> RoutedProposalRecord:
    return RoutedProposalRecord(
        proposal_id=proposal_id,
        proposal_kind=proposal_kind,
        source_route_item_id=item.route_item_id,
        source_runtime_session_id=item.source_runtime_session_id,
        source_worker_id=item.source_worker_id,
        task_id=item.task_id,
        target_scope=target_scope,
        summary=summary,
        payload_ref=payload_ref,
        metadata=dict(metadata or {}),
    )


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


def _validate_relative_payload_ref(value: str, field_name: str) -> None:
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if posix.is_absolute() or windows.is_absolute():
        raise ResultRoutingError(f"{field_name} must be a relative reference")
    if ".." in posix.parts or ".." in windows.parts:
        raise ResultRoutingError(f"{field_name} must not traverse parent directories")


def _proposal_kind(value: RoutedProposalKind | str) -> RoutedProposalKind:
    raw = value.value if isinstance(value, RoutedProposalKind) else value
    try:
        return RoutedProposalKind(_require_string(raw, "proposal_kind"))
    except ValueError as exc:
        raise ResultRoutingError(f"Unknown proposal kind: {raw!r}") from exc


def _approval_kind(value: RoutedApprovalKind | str) -> RoutedApprovalKind:
    raw = value.value if isinstance(value, RoutedApprovalKind) else value
    try:
        return RoutedApprovalKind(_require_string(raw, "approval_kind"))
    except ValueError as exc:
        raise ResultRoutingError(f"Unknown approval kind: {raw!r}") from exc


def _approval_status(value: RoutedApprovalStatus | str) -> RoutedApprovalStatus:
    raw = value.value if isinstance(value, RoutedApprovalStatus) else value
    try:
        return RoutedApprovalStatus(_require_string(raw, "status"))
    except ValueError as exc:
        raise ResultRoutingError(f"Unknown approval status: {raw!r}") from exc


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


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, field_name)

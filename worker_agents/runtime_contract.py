"""Serializable runtime adapter contracts for managed worker execution."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping

from .profile import validate_worker_id
from .task_state import validate_task_id


RUNTIME_CONTRACT_VERSION = 1


class RuntimeContractError(ValueError):
    """Raised when a runtime adapter contract is invalid."""


class RuntimeType(StrEnum):
    """Runtime adapter families that can execute managed worker tasks."""

    INTERNAL_WORKER = "internal_worker"
    EXTERNAL_ADAPTER = "external_adapter"
    TEMPORARY_SUBAGENT = "temporary_subagent"
    DELEGATE_TASK_ADAPTER = "delegate_task_adapter"


class RuntimeState(StrEnum):
    """Execution state for one runtime adapter invocation."""

    QUEUED = "queued"
    STARTING = "starting"
    RUNNING = "running"
    CANCELLING = "cancelling"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class RuntimeEventType(StrEnum):
    """Low-sensitive event types emitted by runtime adapters."""

    QUEUED = "queued"
    STARTED = "started"
    HEARTBEAT = "heartbeat"
    OUTPUT_CHUNK = "output_chunk"
    TOOL_CALL_SUMMARY = "tool_call_summary"
    RESOURCE_USAGE = "resource_usage"
    ERROR = "error"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class RuntimeErrorCode(StrEnum):
    """Structured error classes returned by runtime adapters."""

    RETRYABLE = "retryable"
    NON_RETRYABLE = "non_retryable"
    PERMISSION_DENIED = "permission_denied"
    BUDGET_EXCEEDED = "budget_exceeded"
    ADAPTER_UNHEALTHY = "adapter_unhealthy"
    OUTPUT_PARSE_ERROR = "output_parse_error"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


TERMINAL_RUNTIME_STATES = frozenset(
    {
        RuntimeState.SUCCEEDED,
        RuntimeState.FAILED,
        RuntimeState.TIMED_OUT,
        RuntimeState.CANCELLED,
    }
)

_ALLOWED_RUNTIME_STATE_TRANSITIONS = {
    RuntimeState.QUEUED: {RuntimeState.STARTING, RuntimeState.CANCELLED},
    RuntimeState.STARTING: {
        RuntimeState.RUNNING,
        RuntimeState.FAILED,
        RuntimeState.TIMED_OUT,
        RuntimeState.CANCELLED,
    },
    RuntimeState.RUNNING: {
        RuntimeState.CANCELLING,
        RuntimeState.SUCCEEDED,
        RuntimeState.FAILED,
        RuntimeState.TIMED_OUT,
    },
    RuntimeState.CANCELLING: {RuntimeState.CANCELLED, RuntimeState.FAILED},
    RuntimeState.SUCCEEDED: set(),
    RuntimeState.FAILED: set(),
    RuntimeState.TIMED_OUT: set(),
    RuntimeState.CANCELLED: set(),
}

_EVENT_STATES = {
    RuntimeEventType.QUEUED: {RuntimeState.QUEUED},
    RuntimeEventType.STARTED: {RuntimeState.STARTING},
    RuntimeEventType.HEARTBEAT: {RuntimeState.STARTING, RuntimeState.RUNNING},
    RuntimeEventType.OUTPUT_CHUNK: {RuntimeState.RUNNING},
    RuntimeEventType.TOOL_CALL_SUMMARY: {RuntimeState.RUNNING},
    RuntimeEventType.RESOURCE_USAGE: {
        RuntimeState.STARTING,
        RuntimeState.RUNNING,
        RuntimeState.CANCELLING,
    },
    RuntimeEventType.ERROR: {
        RuntimeState.FAILED,
        RuntimeState.TIMED_OUT,
        RuntimeState.CANCELLED,
    },
    RuntimeEventType.CANCEL_REQUESTED: {RuntimeState.CANCELLING},
    RuntimeEventType.CANCELLED: {RuntimeState.CANCELLED},
    RuntimeEventType.COMPLETED: TERMINAL_RUNTIME_STATES,
}


_SENSITIVE_FIELD_NAMES = frozenset(
    {
        "api_key",
        "complete_transcript",
        "credential",
        "credentials",
        "environment",
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
    }
)


def utc_timestamp() -> str:
    """Return a stable UTC timestamp for runtime contract records."""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeContractError(f"{field_name} must be an object")
    return value


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeContractError(f"{field_name} must be a non-empty string")
    return value


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, field_name)


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RuntimeContractError(f"{field_name} must be a positive integer")
    return value


def _non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimeContractError(f"{field_name} must be a non-negative integer")
    return value


def _optional_positive_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, field_name)


def _optional_non_negative_number(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise RuntimeContractError(f"{field_name} must be a non-negative number")
    return float(value)


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise RuntimeContractError(f"{field_name} must be a list of strings")
    result = tuple(value)
    if any(not isinstance(item, str) or not item for item in result):
        raise RuntimeContractError(f"{field_name} must be a list of non-empty strings")
    return result


def _reject_unknown_fields(
    data: Mapping[str, Any], allowed_fields: set[str], field_name: str
) -> None:
    unknown_fields = sorted(set(data) - allowed_fields)
    if unknown_fields:
        joined = ", ".join(unknown_fields)
        raise RuntimeContractError(f"{field_name} has unknown fields: {joined}")


def _validate_contract_version(version: Any) -> int:
    if version != RUNTIME_CONTRACT_VERSION:
        raise RuntimeContractError(f"Unsupported runtime contract_version: {version!r}")
    return version


def _coerce_runtime_type(value: RuntimeType | str) -> RuntimeType:
    raw_value = value.value if isinstance(value, RuntimeType) else value
    raw_value = _require_string(raw_value, "runtime_type")
    try:
        return RuntimeType(raw_value)
    except ValueError as exc:
        raise RuntimeContractError(f"Unknown runtime_type: {raw_value!r}") from exc


def _coerce_runtime_state(value: RuntimeState | str) -> RuntimeState:
    raw_value = value.value if isinstance(value, RuntimeState) else value
    raw_value = _require_string(raw_value, "state")
    try:
        return RuntimeState(raw_value)
    except ValueError as exc:
        raise RuntimeContractError(f"Unknown runtime state: {raw_value!r}") from exc


def _coerce_runtime_event_type(value: RuntimeEventType | str) -> RuntimeEventType:
    raw_value = value.value if isinstance(value, RuntimeEventType) else value
    raw_value = _require_string(raw_value, "event_type")
    try:
        return RuntimeEventType(raw_value)
    except ValueError as exc:
        raise RuntimeContractError(f"Unknown runtime event_type: {raw_value!r}") from exc


def _coerce_runtime_error_code(value: RuntimeErrorCode | str) -> RuntimeErrorCode:
    raw_value = value.value if isinstance(value, RuntimeErrorCode) else value
    raw_value = _require_string(raw_value, "error_code")
    try:
        return RuntimeErrorCode(raw_value)
    except ValueError as exc:
        raise RuntimeContractError(f"Unknown runtime error_code: {raw_value!r}") from exc


def _reject_sensitive_fields(value: Any, field_name: str) -> None:
    """Reject raw logs, credentials, and complete context by field name."""

    if isinstance(value, Mapping):
        for key, nested in value.items():
            if isinstance(key, str) and key.lower() in _SENSITIVE_FIELD_NAMES:
                raise RuntimeContractError(
                    f"{field_name} must not include sensitive field: {key}"
                )
            _reject_sensitive_fields(nested, f"{field_name}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _reject_sensitive_fields(nested, f"{field_name}[{index}]")


def validate_runtime_state_transition(
    previous_state: RuntimeState | str, next_state: RuntimeState | str
) -> tuple[RuntimeState, RuntimeState]:
    """Return normalized states after rejecting an invalid runtime transition."""

    previous = _coerce_runtime_state(previous_state)
    next_ = _coerce_runtime_state(next_state)
    if next_ not in _ALLOWED_RUNTIME_STATE_TRANSITIONS[previous]:
        raise RuntimeContractError(
            f"runtime state cannot transition from {previous.value} to {next_.value}"
        )
    return previous, next_


@dataclass(frozen=True)
class RuntimeExecutionBudget:
    """Immutable runtime limits inherited from managed worker policy."""

    budget_source: str
    model: str | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    max_cost_usd: float | None = None
    timeout_seconds: int | None = None
    max_output_bytes: int | None = None
    max_transcript_bytes: int | None = None

    def __post_init__(self) -> None:
        _require_string(self.budget_source, "budget_source")
        _optional_string(self.model, "model")
        for field_name in (
            "max_input_tokens",
            "max_output_tokens",
            "timeout_seconds",
            "max_output_bytes",
            "max_transcript_bytes",
        ):
            _optional_positive_int(getattr(self, field_name), field_name)
        _optional_non_negative_number(self.max_cost_usd, "max_cost_usd")
        if all(
            getattr(self, field_name) is None
            for field_name in (
                "max_input_tokens",
                "max_output_tokens",
                "max_cost_usd",
                "timeout_seconds",
                "max_output_bytes",
                "max_transcript_bytes",
            )
        ):
            raise RuntimeContractError("runtime budget requires at least one limit")


@dataclass(frozen=True)
class RuntimeRequestContext:
    """Minimal task context allowed to cross the adapter boundary."""

    input_message: str
    worker_prompt_summary: Mapping[str, Any] | None = None
    source_thread_id: str | None = None
    source_message_refs: tuple[str, ...] = ()
    source_sender_ref: str | None = None
    target_context_summary: str | None = None
    thread_summary_refs: tuple[str, ...] = ()
    organization_summary_refs: tuple[str, ...] = ()
    artifact_manifest_refs: tuple[str, ...] = ()
    allowed_tool_descriptions: tuple[str, ...] = ()
    workspace_policy_ref: str | None = None
    redaction_policy_ref: str | None = None
    relevant_excerpts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_string(self.input_message, "input_message")
        if self.worker_prompt_summary is not None:
            prompt_summary = dict(_require_mapping(
                self.worker_prompt_summary, "worker_prompt_summary"
            ))
            _reject_sensitive_fields(prompt_summary, "worker_prompt_summary")
            object.__setattr__(self, "worker_prompt_summary", prompt_summary)
        for field_name in (
            "source_message_refs",
            "thread_summary_refs",
            "organization_summary_refs",
            "artifact_manifest_refs",
            "allowed_tool_descriptions",
            "relevant_excerpts",
        ):
            _string_tuple(getattr(self, field_name), field_name)
        _optional_string(self.source_thread_id, "source_thread_id")
        _optional_string(self.source_sender_ref, "source_sender_ref")
        _optional_string(self.target_context_summary, "target_context_summary")
        _optional_string(self.workspace_policy_ref, "workspace_policy_ref")
        _optional_string(self.redaction_policy_ref, "redaction_policy_ref")
        _reject_sensitive_fields(runtime_request_context_to_dict(self), "context")


@dataclass(frozen=True)
class RuntimeRequest:
    """Adapter invocation input before any runtime execution starts."""

    request_id: str
    task_id: str
    worker_id: str
    runtime_type: RuntimeType | str
    requested_by: str
    created_at: str
    context: RuntimeRequestContext
    budget: RuntimeExecutionBudget
    session_ref: str | None = None
    parent_request_id: str | None = None
    contract_version: int = RUNTIME_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _validate_contract_version(self.contract_version)
        _require_string(self.request_id, "request_id")
        validate_task_id(self.task_id)
        validate_worker_id(self.worker_id)
        object.__setattr__(self, "runtime_type", _coerce_runtime_type(self.runtime_type))
        _require_string(self.requested_by, "requested_by")
        _require_string(self.created_at, "created_at")
        _optional_string(self.session_ref, "session_ref")
        _optional_string(self.parent_request_id, "parent_request_id")
        if not isinstance(self.context, RuntimeRequestContext):
            raise RuntimeContractError("context must be a RuntimeRequestContext")
        if not isinstance(self.budget, RuntimeExecutionBudget):
            raise RuntimeContractError("budget must be a RuntimeExecutionBudget")
        if (
            self.runtime_type
            in {RuntimeType.TEMPORARY_SUBAGENT, RuntimeType.DELEGATE_TASK_ADAPTER}
            and self.parent_request_id is None
        ):
            raise RuntimeContractError(
                f"{self.runtime_type.value} requires parent_request_id"
            )


@dataclass(frozen=True)
class RuntimeEvent:
    """Low-sensitive progress record emitted by a runtime adapter."""

    event_id: str
    request_id: str
    task_id: str
    worker_id: str
    runtime_type: RuntimeType | str
    state: RuntimeState | str
    event_type: RuntimeEventType | str
    created_at: str
    sequence: int
    payload: Mapping[str, Any] | None = None
    contract_version: int = RUNTIME_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _validate_contract_version(self.contract_version)
        _require_string(self.event_id, "event_id")
        _require_string(self.request_id, "request_id")
        validate_task_id(self.task_id)
        validate_worker_id(self.worker_id)
        object.__setattr__(self, "runtime_type", _coerce_runtime_type(self.runtime_type))
        state = _coerce_runtime_state(self.state)
        event_type = _coerce_runtime_event_type(self.event_type)
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "event_type", event_type)
        _require_string(self.created_at, "created_at")
        _non_negative_int(self.sequence, "sequence")
        if self.payload is not None:
            payload = dict(_require_mapping(self.payload, "payload"))
            _reject_sensitive_fields(payload, "payload")
            object.__setattr__(self, "payload", payload)
        else:
            object.__setattr__(self, "payload", {})
        if state not in _EVENT_STATES[event_type]:
            allowed = ", ".join(sorted(item.value for item in _EVENT_STATES[event_type]))
            raise RuntimeContractError(
                f"{event_type.value} event requires state in: {allowed}"
            )


@dataclass(frozen=True)
class RuntimeArtifactRef:
    """Reference to an artifact manifest without copying artifact content."""

    manifest_ref: str
    artifact_type: str
    summary: str
    retention_policy_ref: str | None = None

    def __post_init__(self) -> None:
        _require_string(self.manifest_ref, "manifest_ref")
        _require_string(self.artifact_type, "artifact_type")
        _require_string(self.summary, "summary")
        _optional_string(self.retention_policy_ref, "retention_policy_ref")


@dataclass(frozen=True)
class RuntimeMemoryProposal:
    """Redacted memory candidate that still requires later review."""

    proposal_id: str
    target_scope: str
    redacted_summary: str
    source_task_id: str
    review_reason: str

    def __post_init__(self) -> None:
        _require_string(self.proposal_id, "proposal_id")
        _require_string(self.target_scope, "target_scope")
        _require_string(self.redacted_summary, "redacted_summary")
        validate_task_id(self.source_task_id)
        _require_string(self.review_reason, "review_reason")
        _reject_sensitive_fields(runtime_memory_proposal_to_dict(self), "memory_proposal")


@dataclass(frozen=True)
class RuntimeSafetyRequest:
    """User or main-agent review request produced by a runtime result."""

    request_id: str
    request_type: str
    risk_level: str
    user_visible_summary: str
    required_approver: str
    blocking: bool = True

    def __post_init__(self) -> None:
        _require_string(self.request_id, "request_id")
        _require_string(self.request_type, "request_type")
        _require_string(self.risk_level, "risk_level")
        _require_string(self.user_visible_summary, "user_visible_summary")
        _require_string(self.required_approver, "required_approver")
        if not isinstance(self.blocking, bool):
            raise RuntimeContractError("blocking must be a boolean")


@dataclass(frozen=True)
class RuntimeErrorInfo:
    """Low-sensitive error summary with an optional middle-data log reference."""

    code: RuntimeErrorCode | str
    message: str
    safe_summary: str
    retryable: bool
    source: str
    created_at: str
    raw_error_ref: str | None = None

    def __post_init__(self) -> None:
        code = _coerce_runtime_error_code(self.code)
        object.__setattr__(self, "code", code)
        _require_string(self.message, "message")
        _require_string(self.safe_summary, "safe_summary")
        if not isinstance(self.retryable, bool):
            raise RuntimeContractError("retryable must be a boolean")
        _require_string(self.source, "source")
        _require_string(self.created_at, "created_at")
        _optional_string(self.raw_error_ref, "raw_error_ref")
        if code == RuntimeErrorCode.RETRYABLE and not self.retryable:
            raise RuntimeContractError("retryable error code must set retryable=true")
        if code in {
            RuntimeErrorCode.NON_RETRYABLE,
            RuntimeErrorCode.PERMISSION_DENIED,
            RuntimeErrorCode.BUDGET_EXCEEDED,
            RuntimeErrorCode.CANCELLED,
            RuntimeErrorCode.TIMED_OUT,
        } and self.retryable:
            raise RuntimeContractError(f"{code.value} errors must not be retryable")
        _reject_sensitive_fields(runtime_error_to_dict(self), "runtime_error")


@dataclass(frozen=True)
class RuntimeResult:
    """Terminal runtime output before result routing writes anywhere durable."""

    request_id: str
    task_id: str
    worker_id: str
    runtime_type: RuntimeType | str
    final_state: RuntimeState | str
    started_at: str
    completed_at: str
    public_message: str | None = None
    internal_summary: str | None = None
    artifact_refs: tuple[RuntimeArtifactRef, ...] = ()
    memory_proposals: tuple[RuntimeMemoryProposal, ...] = ()
    department_asset_proposals: tuple[RuntimeMemoryProposal, ...] = ()
    safety_requests: tuple[RuntimeSafetyRequest, ...] = ()
    audit_summary: str | None = None
    error: RuntimeErrorInfo | None = None
    partial_success: bool = False
    contract_version: int = RUNTIME_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _validate_contract_version(self.contract_version)
        _require_string(self.request_id, "request_id")
        validate_task_id(self.task_id)
        validate_worker_id(self.worker_id)
        object.__setattr__(self, "runtime_type", _coerce_runtime_type(self.runtime_type))
        final_state = _coerce_runtime_state(self.final_state)
        object.__setattr__(self, "final_state", final_state)
        if final_state not in TERMINAL_RUNTIME_STATES:
            raise RuntimeContractError("runtime result requires a terminal final_state")
        _require_string(self.started_at, "started_at")
        _require_string(self.completed_at, "completed_at")
        _optional_string(self.public_message, "public_message")
        _optional_string(self.internal_summary, "internal_summary")
        _optional_string(self.audit_summary, "audit_summary")
        if not isinstance(self.partial_success, bool):
            raise RuntimeContractError("partial_success must be a boolean")
        self._validate_tuple_records("artifact_refs", RuntimeArtifactRef)
        self._validate_tuple_records("memory_proposals", RuntimeMemoryProposal)
        self._validate_tuple_records(
            "department_asset_proposals", RuntimeMemoryProposal
        )
        self._validate_tuple_records("safety_requests", RuntimeSafetyRequest)
        if self.error is not None and not isinstance(self.error, RuntimeErrorInfo):
            raise RuntimeContractError("error must be a RuntimeErrorInfo")
        if final_state in {RuntimeState.FAILED, RuntimeState.TIMED_OUT} and self.error is None:
            raise RuntimeContractError(f"{final_state.value} result requires error")
        if final_state == RuntimeState.CANCELLED and self.error is None:
            raise RuntimeContractError("cancelled result requires cancellation error")
        if not self._has_any_output():
            raise RuntimeContractError("runtime result requires at least one output field")
        _reject_sensitive_fields(runtime_result_to_dict(self), "runtime_result")

    def _validate_tuple_records(self, field_name: str, record_type: type) -> None:
        values = getattr(self, field_name)
        if not isinstance(values, tuple):
            raise RuntimeContractError(f"{field_name} must be a tuple")
        if any(not isinstance(value, record_type) for value in values):
            raise RuntimeContractError(
                f"{field_name} must contain {record_type.__name__} records"
            )

    def _has_any_output(self) -> bool:
        return any(
            (
                self.public_message,
                self.internal_summary,
                self.artifact_refs,
                self.memory_proposals,
                self.department_asset_proposals,
                self.safety_requests,
                self.audit_summary,
                self.error,
            )
        )


def validate_runtime_event_sequence(events: tuple[RuntimeEvent, ...]) -> None:
    """Validate ordering and terminal-state boundaries for one event stream."""

    seen_sequences: set[int] = set()
    terminal_state: RuntimeState | None = None
    for event in events:
        if not isinstance(event, RuntimeEvent):
            raise RuntimeContractError("events must contain RuntimeEvent records")
        if event.sequence in seen_sequences:
            raise RuntimeContractError(f"duplicate runtime event sequence: {event.sequence}")
        seen_sequences.add(event.sequence)
        if terminal_state is not None:
            raise RuntimeContractError(
                f"runtime event cannot be appended after terminal state {terminal_state.value}"
            )
        if event.state in TERMINAL_RUNTIME_STATES:
            terminal_state = event.state


def runtime_budget_to_dict(budget: RuntimeExecutionBudget) -> dict[str, Any]:
    return {
        "budget_source": budget.budget_source,
        "model": budget.model,
        "max_input_tokens": budget.max_input_tokens,
        "max_output_tokens": budget.max_output_tokens,
        "max_cost_usd": budget.max_cost_usd,
        "timeout_seconds": budget.timeout_seconds,
        "max_output_bytes": budget.max_output_bytes,
        "max_transcript_bytes": budget.max_transcript_bytes,
    }


def runtime_budget_from_dict(data: Mapping[str, Any]) -> RuntimeExecutionBudget:
    data = _require_mapping(data, "budget")
    _reject_unknown_fields(
        data,
        {
            "budget_source",
            "model",
            "max_input_tokens",
            "max_output_tokens",
            "max_cost_usd",
            "timeout_seconds",
            "max_output_bytes",
            "max_transcript_bytes",
        },
        "budget",
    )
    _reject_sensitive_fields(data, "budget")
    return RuntimeExecutionBudget(
        budget_source=_require_string(data.get("budget_source"), "budget_source"),
        model=_optional_string(data.get("model"), "model"),
        max_input_tokens=_optional_positive_int(
            data.get("max_input_tokens"), "max_input_tokens"
        ),
        max_output_tokens=_optional_positive_int(
            data.get("max_output_tokens"), "max_output_tokens"
        ),
        max_cost_usd=_optional_non_negative_number(
            data.get("max_cost_usd"), "max_cost_usd"
        ),
        timeout_seconds=_optional_positive_int(
            data.get("timeout_seconds"), "timeout_seconds"
        ),
        max_output_bytes=_optional_positive_int(
            data.get("max_output_bytes"), "max_output_bytes"
        ),
        max_transcript_bytes=_optional_positive_int(
            data.get("max_transcript_bytes"), "max_transcript_bytes"
        ),
    )


def runtime_request_context_to_dict(
    context: RuntimeRequestContext,
) -> dict[str, Any]:
    return {
        "input_message": context.input_message,
        "worker_prompt_summary": context.worker_prompt_summary,
        "source_thread_id": context.source_thread_id,
        "source_message_refs": list(context.source_message_refs),
        "source_sender_ref": context.source_sender_ref,
        "target_context_summary": context.target_context_summary,
        "thread_summary_refs": list(context.thread_summary_refs),
        "organization_summary_refs": list(context.organization_summary_refs),
        "artifact_manifest_refs": list(context.artifact_manifest_refs),
        "allowed_tool_descriptions": list(context.allowed_tool_descriptions),
        "workspace_policy_ref": context.workspace_policy_ref,
        "redaction_policy_ref": context.redaction_policy_ref,
        "relevant_excerpts": list(context.relevant_excerpts),
    }


def runtime_request_context_from_dict(
    data: Mapping[str, Any],
) -> RuntimeRequestContext:
    data = _require_mapping(data, "context")
    _reject_unknown_fields(
        data,
        {
            "input_message",
            "worker_prompt_summary",
            "source_thread_id",
            "source_message_refs",
            "source_sender_ref",
            "target_context_summary",
            "thread_summary_refs",
            "organization_summary_refs",
            "artifact_manifest_refs",
            "allowed_tool_descriptions",
            "workspace_policy_ref",
            "redaction_policy_ref",
            "relevant_excerpts",
        },
        "context",
    )
    _reject_sensitive_fields(data, "context")
    return RuntimeRequestContext(
        input_message=_require_string(data.get("input_message"), "input_message"),
        worker_prompt_summary=dict(
            _require_mapping(data.get("worker_prompt_summary"), "worker_prompt_summary")
        )
        if data.get("worker_prompt_summary") is not None
        else None,
        source_thread_id=_optional_string(
            data.get("source_thread_id"), "source_thread_id"
        ),
        source_message_refs=_string_tuple(
            data.get("source_message_refs", ()), "source_message_refs"
        ),
        source_sender_ref=_optional_string(
            data.get("source_sender_ref"), "source_sender_ref"
        ),
        target_context_summary=_optional_string(
            data.get("target_context_summary"), "target_context_summary"
        ),
        thread_summary_refs=_string_tuple(
            data.get("thread_summary_refs", ()), "thread_summary_refs"
        ),
        organization_summary_refs=_string_tuple(
            data.get("organization_summary_refs", ()), "organization_summary_refs"
        ),
        artifact_manifest_refs=_string_tuple(
            data.get("artifact_manifest_refs", ()), "artifact_manifest_refs"
        ),
        allowed_tool_descriptions=_string_tuple(
            data.get("allowed_tool_descriptions", ()), "allowed_tool_descriptions"
        ),
        workspace_policy_ref=_optional_string(
            data.get("workspace_policy_ref"), "workspace_policy_ref"
        ),
        redaction_policy_ref=_optional_string(
            data.get("redaction_policy_ref"), "redaction_policy_ref"
        ),
        relevant_excerpts=_string_tuple(
            data.get("relevant_excerpts", ()), "relevant_excerpts"
        ),
    )


def runtime_request_to_dict(request: RuntimeRequest) -> dict[str, Any]:
    return {
        "contract_version": request.contract_version,
        "request_id": request.request_id,
        "task_id": request.task_id,
        "worker_id": request.worker_id,
        "runtime_type": request.runtime_type.value,
        "requested_by": request.requested_by,
        "created_at": request.created_at,
        "context": runtime_request_context_to_dict(request.context),
        "budget": runtime_budget_to_dict(request.budget),
        "session_ref": request.session_ref,
        "parent_request_id": request.parent_request_id,
    }


def runtime_request_from_dict(data: Mapping[str, Any]) -> RuntimeRequest:
    data = _require_mapping(data, "runtime_request")
    _reject_unknown_fields(
        data,
        {
            "contract_version",
            "request_id",
            "task_id",
            "worker_id",
            "runtime_type",
            "requested_by",
            "created_at",
            "context",
            "budget",
            "session_ref",
            "parent_request_id",
        },
        "runtime_request",
    )
    _reject_sensitive_fields(data, "runtime_request")
    return RuntimeRequest(
        contract_version=_validate_contract_version(data.get("contract_version")),
        request_id=_require_string(data.get("request_id"), "request_id"),
        task_id=_require_string(data.get("task_id"), "task_id"),
        worker_id=_require_string(data.get("worker_id"), "worker_id"),
        runtime_type=_coerce_runtime_type(data.get("runtime_type")),
        requested_by=_require_string(data.get("requested_by"), "requested_by"),
        created_at=_require_string(data.get("created_at"), "created_at"),
        context=runtime_request_context_from_dict(data.get("context")),
        budget=runtime_budget_from_dict(data.get("budget")),
        session_ref=_optional_string(data.get("session_ref"), "session_ref"),
        parent_request_id=_optional_string(
            data.get("parent_request_id"), "parent_request_id"
        ),
    )


def runtime_event_to_dict(event: RuntimeEvent) -> dict[str, Any]:
    return {
        "contract_version": event.contract_version,
        "event_id": event.event_id,
        "request_id": event.request_id,
        "task_id": event.task_id,
        "worker_id": event.worker_id,
        "runtime_type": event.runtime_type.value,
        "state": event.state.value,
        "event_type": event.event_type.value,
        "created_at": event.created_at,
        "sequence": event.sequence,
        "payload": dict(event.payload or {}),
    }


def runtime_event_from_dict(data: Mapping[str, Any]) -> RuntimeEvent:
    data = _require_mapping(data, "runtime_event")
    _reject_unknown_fields(
        data,
        {
            "contract_version",
            "event_id",
            "request_id",
            "task_id",
            "worker_id",
            "runtime_type",
            "state",
            "event_type",
            "created_at",
            "sequence",
            "payload",
        },
        "runtime_event",
    )
    _reject_sensitive_fields(data, "runtime_event")
    return RuntimeEvent(
        contract_version=_validate_contract_version(data.get("contract_version")),
        event_id=_require_string(data.get("event_id"), "event_id"),
        request_id=_require_string(data.get("request_id"), "request_id"),
        task_id=_require_string(data.get("task_id"), "task_id"),
        worker_id=_require_string(data.get("worker_id"), "worker_id"),
        runtime_type=_coerce_runtime_type(data.get("runtime_type")),
        state=_coerce_runtime_state(data.get("state")),
        event_type=_coerce_runtime_event_type(data.get("event_type")),
        created_at=_require_string(data.get("created_at"), "created_at"),
        sequence=_non_negative_int(data.get("sequence"), "sequence"),
        payload=dict(_require_mapping(data.get("payload", {}), "payload")),
    )


def dump_runtime_event_json(event: RuntimeEvent) -> str:
    return json.dumps(runtime_event_to_dict(event), ensure_ascii=False, sort_keys=True)


def load_runtime_event_json(payload: str) -> RuntimeEvent:
    return runtime_event_from_dict(json.loads(payload))


def runtime_artifact_ref_to_dict(ref: RuntimeArtifactRef) -> dict[str, Any]:
    return {
        "manifest_ref": ref.manifest_ref,
        "artifact_type": ref.artifact_type,
        "summary": ref.summary,
        "retention_policy_ref": ref.retention_policy_ref,
    }


def runtime_artifact_ref_from_dict(data: Mapping[str, Any]) -> RuntimeArtifactRef:
    data = _require_mapping(data, "artifact_ref")
    _reject_unknown_fields(
        data,
        {"manifest_ref", "artifact_type", "summary", "retention_policy_ref"},
        "artifact_ref",
    )
    _reject_sensitive_fields(data, "artifact_ref")
    return RuntimeArtifactRef(
        manifest_ref=_require_string(data.get("manifest_ref"), "manifest_ref"),
        artifact_type=_require_string(data.get("artifact_type"), "artifact_type"),
        summary=_require_string(data.get("summary"), "summary"),
        retention_policy_ref=_optional_string(
            data.get("retention_policy_ref"), "retention_policy_ref"
        ),
    )


def runtime_memory_proposal_to_dict(
    proposal: RuntimeMemoryProposal,
) -> dict[str, Any]:
    return {
        "proposal_id": proposal.proposal_id,
        "target_scope": proposal.target_scope,
        "redacted_summary": proposal.redacted_summary,
        "source_task_id": proposal.source_task_id,
        "review_reason": proposal.review_reason,
    }


def runtime_memory_proposal_from_dict(
    data: Mapping[str, Any],
) -> RuntimeMemoryProposal:
    data = _require_mapping(data, "memory_proposal")
    _reject_unknown_fields(
        data,
        {
            "proposal_id",
            "target_scope",
            "redacted_summary",
            "source_task_id",
            "review_reason",
        },
        "memory_proposal",
    )
    _reject_sensitive_fields(data, "memory_proposal")
    return RuntimeMemoryProposal(
        proposal_id=_require_string(data.get("proposal_id"), "proposal_id"),
        target_scope=_require_string(data.get("target_scope"), "target_scope"),
        redacted_summary=_require_string(
            data.get("redacted_summary"), "redacted_summary"
        ),
        source_task_id=_require_string(data.get("source_task_id"), "source_task_id"),
        review_reason=_require_string(data.get("review_reason"), "review_reason"),
    )


def runtime_safety_request_to_dict(
    request: RuntimeSafetyRequest,
) -> dict[str, Any]:
    return {
        "request_id": request.request_id,
        "request_type": request.request_type,
        "risk_level": request.risk_level,
        "user_visible_summary": request.user_visible_summary,
        "required_approver": request.required_approver,
        "blocking": request.blocking,
    }


def runtime_safety_request_from_dict(data: Mapping[str, Any]) -> RuntimeSafetyRequest:
    data = _require_mapping(data, "safety_request")
    _reject_unknown_fields(
        data,
        {
            "request_id",
            "request_type",
            "risk_level",
            "user_visible_summary",
            "required_approver",
            "blocking",
        },
        "safety_request",
    )
    _reject_sensitive_fields(data, "safety_request")
    blocking = data.get("blocking", True)
    if not isinstance(blocking, bool):
        raise RuntimeContractError("blocking must be a boolean")
    return RuntimeSafetyRequest(
        request_id=_require_string(data.get("request_id"), "request_id"),
        request_type=_require_string(data.get("request_type"), "request_type"),
        risk_level=_require_string(data.get("risk_level"), "risk_level"),
        user_visible_summary=_require_string(
            data.get("user_visible_summary"), "user_visible_summary"
        ),
        required_approver=_require_string(
            data.get("required_approver"), "required_approver"
        ),
        blocking=blocking,
    )


def runtime_error_to_dict(error: RuntimeErrorInfo) -> dict[str, Any]:
    return {
        "code": error.code.value,
        "message": error.message,
        "safe_summary": error.safe_summary,
        "retryable": error.retryable,
        "source": error.source,
        "created_at": error.created_at,
        "raw_error_ref": error.raw_error_ref,
    }


def runtime_error_from_dict(data: Mapping[str, Any]) -> RuntimeErrorInfo:
    data = _require_mapping(data, "runtime_error")
    _reject_unknown_fields(
        data,
        {
            "code",
            "message",
            "safe_summary",
            "retryable",
            "source",
            "created_at",
            "raw_error_ref",
        },
        "runtime_error",
    )
    _reject_sensitive_fields(data, "runtime_error")
    retryable = data.get("retryable")
    if not isinstance(retryable, bool):
        raise RuntimeContractError("retryable must be a boolean")
    return RuntimeErrorInfo(
        code=_coerce_runtime_error_code(data.get("code")),
        message=_require_string(data.get("message"), "message"),
        safe_summary=_require_string(data.get("safe_summary"), "safe_summary"),
        retryable=retryable,
        source=_require_string(data.get("source"), "source"),
        created_at=_require_string(data.get("created_at"), "created_at"),
        raw_error_ref=_optional_string(data.get("raw_error_ref"), "raw_error_ref"),
    )


def runtime_result_to_dict(result: RuntimeResult) -> dict[str, Any]:
    return {
        "contract_version": result.contract_version,
        "request_id": result.request_id,
        "task_id": result.task_id,
        "worker_id": result.worker_id,
        "runtime_type": result.runtime_type.value,
        "final_state": result.final_state.value,
        "started_at": result.started_at,
        "completed_at": result.completed_at,
        "public_message": result.public_message,
        "internal_summary": result.internal_summary,
        "artifact_refs": [
            runtime_artifact_ref_to_dict(ref) for ref in result.artifact_refs
        ],
        "memory_proposals": [
            runtime_memory_proposal_to_dict(proposal)
            for proposal in result.memory_proposals
        ],
        "department_asset_proposals": [
            runtime_memory_proposal_to_dict(proposal)
            for proposal in result.department_asset_proposals
        ],
        "safety_requests": [
            runtime_safety_request_to_dict(request)
            for request in result.safety_requests
        ],
        "audit_summary": result.audit_summary,
        "error": runtime_error_to_dict(result.error) if result.error else None,
        "partial_success": result.partial_success,
    }


def runtime_result_from_dict(data: Mapping[str, Any]) -> RuntimeResult:
    data = _require_mapping(data, "runtime_result")
    _reject_unknown_fields(
        data,
        {
            "contract_version",
            "request_id",
            "task_id",
            "worker_id",
            "runtime_type",
            "final_state",
            "started_at",
            "completed_at",
            "public_message",
            "internal_summary",
            "artifact_refs",
            "memory_proposals",
            "department_asset_proposals",
            "safety_requests",
            "audit_summary",
            "error",
            "partial_success",
        },
        "runtime_result",
    )
    _reject_sensitive_fields(data, "runtime_result")
    partial_success = data.get("partial_success", False)
    if not isinstance(partial_success, bool):
        raise RuntimeContractError("partial_success must be a boolean")
    return RuntimeResult(
        contract_version=_validate_contract_version(data.get("contract_version")),
        request_id=_require_string(data.get("request_id"), "request_id"),
        task_id=_require_string(data.get("task_id"), "task_id"),
        worker_id=_require_string(data.get("worker_id"), "worker_id"),
        runtime_type=_coerce_runtime_type(data.get("runtime_type")),
        final_state=_coerce_runtime_state(data.get("final_state")),
        started_at=_require_string(data.get("started_at"), "started_at"),
        completed_at=_require_string(data.get("completed_at"), "completed_at"),
        public_message=_optional_string(data.get("public_message"), "public_message"),
        internal_summary=_optional_string(
            data.get("internal_summary"), "internal_summary"
        ),
        artifact_refs=tuple(
            runtime_artifact_ref_from_dict(item)
            for item in data.get("artifact_refs", ())
        ),
        memory_proposals=tuple(
            runtime_memory_proposal_from_dict(item)
            for item in data.get("memory_proposals", ())
        ),
        department_asset_proposals=tuple(
            runtime_memory_proposal_from_dict(item)
            for item in data.get("department_asset_proposals", ())
        ),
        safety_requests=tuple(
            runtime_safety_request_from_dict(item)
            for item in data.get("safety_requests", ())
        ),
        audit_summary=_optional_string(data.get("audit_summary"), "audit_summary"),
        error=runtime_error_from_dict(data["error"]) if data.get("error") else None,
        partial_success=partial_success,
    )


def dump_runtime_result_json(result: RuntimeResult) -> str:
    return json.dumps(runtime_result_to_dict(result), ensure_ascii=False, sort_keys=True)


def load_runtime_result_json(payload: str) -> RuntimeResult:
    return runtime_result_from_dict(json.loads(payload))


def dump_runtime_request_json(request: RuntimeRequest) -> str:
    """Serialize a runtime request with stable key ordering for audit logs."""

    return json.dumps(runtime_request_to_dict(request), ensure_ascii=False, sort_keys=True)


def load_runtime_request_json(payload: str) -> RuntimeRequest:
    return runtime_request_from_dict(json.loads(payload))

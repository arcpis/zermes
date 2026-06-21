"""Normalize external adapter output into runtime contract results."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from .external_adapter_runner import ExternalAdapterBackendState
from .runtime_contract import (
    RuntimeArtifactRef,
    RuntimeErrorCode,
    RuntimeErrorInfo,
    RuntimeMemoryProposal,
    RuntimeResult,
    RuntimeSafetyRequest,
    RuntimeRequest,
    RuntimeState,
    RuntimeType,
    runtime_artifact_ref_from_dict,
    runtime_memory_proposal_from_dict,
    runtime_safety_request_from_dict,
    utc_timestamp,
)


class ExternalAdapterOutputError(ValueError):
    """Raised when external adapter output cannot be safely normalized."""


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
class ExternalAdapterRawOutput:
    """Backend output envelope using middle-data references for raw content."""

    invocation_id: str
    adapter_id: str
    state: ExternalAdapterBackendState
    safe_summary: str
    completed_at: str
    adapter_output_text: str | None = None
    raw_output_ref: str | None = None
    raw_error_ref: str | None = None
    metrics: Mapping[str, int | float | str] | None = None


@dataclass(frozen=True)
class ExternalAdapterAuditSummary:
    """Low-sensitive adapter audit record candidate."""

    adapter_id: str
    invocation_id: str
    task_id: str
    worker_id: str
    status: str
    low_sensitivity_summary: str
    raw_output_ref: str | None = None
    raw_error_ref: str | None = None
    metrics: Mapping[str, int | float | str] | None = None


def normalize_external_adapter_output(
    request: RuntimeRequest,
    output: ExternalAdapterRawOutput,
    *,
    started_at: str,
) -> RuntimeResult:
    """Convert one external adapter backend output into a runtime result."""

    if request.runtime_type != RuntimeType.EXTERNAL_ADAPTER:
        raise ExternalAdapterOutputError("request runtime_type must be external_adapter")
    _validate_raw_output(output)
    final_state = _runtime_state_from_backend_state(output.state)
    if final_state == RuntimeState.SUCCEEDED:
        return _success_result(request, output, started_at=started_at)
    error = _error_from_output(output, final_state)
    return RuntimeResult(
        request_id=request.request_id,
        task_id=request.task_id,
        worker_id=request.worker_id,
        runtime_type=RuntimeType.EXTERNAL_ADAPTER,
        final_state=final_state,
        started_at=started_at,
        completed_at=output.completed_at,
        internal_summary=output.safe_summary,
        audit_summary=_audit_text(request, output),
        error=error,
    )


def external_adapter_audit_summary(
    request: RuntimeRequest, output: ExternalAdapterRawOutput
) -> ExternalAdapterAuditSummary:
    """Return a low-sensitive audit summary for adapter operations."""

    return ExternalAdapterAuditSummary(
        adapter_id=output.adapter_id,
        invocation_id=output.invocation_id,
        task_id=request.task_id,
        worker_id=request.worker_id,
        status=_runtime_state_from_backend_state(output.state).value,
        low_sensitivity_summary=output.safe_summary,
        raw_output_ref=output.raw_output_ref,
        raw_error_ref=output.raw_error_ref,
        metrics=dict(output.metrics or {}),
    )


def external_adapter_audit_summary_to_dict(
    summary: ExternalAdapterAuditSummary,
) -> dict[str, Any]:
    """Return a JSON-safe low-sensitive adapter audit summary."""

    return {
        "adapter_id": summary.adapter_id,
        "invocation_id": summary.invocation_id,
        "task_id": summary.task_id,
        "worker_id": summary.worker_id,
        "status": summary.status,
        "low_sensitivity_summary": summary.low_sensitivity_summary,
        "raw_output_ref": summary.raw_output_ref,
        "raw_error_ref": summary.raw_error_ref,
        "metrics": dict(summary.metrics or {}),
    }


def _success_result(
    request: RuntimeRequest,
    output: ExternalAdapterRawOutput,
    *,
    started_at: str,
) -> RuntimeResult:
    parsed = _parse_adapter_output(output.adapter_output_text)
    return RuntimeResult(
        request_id=request.request_id,
        task_id=request.task_id,
        worker_id=request.worker_id,
        runtime_type=RuntimeType.EXTERNAL_ADAPTER,
        final_state=RuntimeState.SUCCEEDED,
        started_at=started_at,
        completed_at=output.completed_at,
        public_message=_optional_string(parsed.get("public_message")),
        internal_summary=_optional_string(parsed.get("internal_summary"))
        or output.safe_summary,
        artifact_refs=_artifact_refs(parsed.get("artifact_refs")),
        memory_proposals=_memory_proposals(parsed.get("memory_proposals")),
        department_asset_proposals=_memory_proposals(
            parsed.get("department_asset_proposals")
        ),
        safety_requests=_safety_requests(parsed.get("safety_requests")),
        audit_summary=_optional_string(parsed.get("audit_summary"))
        or _audit_text(request, output),
        partial_success=bool(parsed.get("partial_success", False)),
    )


def _parse_adapter_output(adapter_output_text: str | None) -> Mapping[str, Any]:
    if adapter_output_text is None:
        return {"internal_summary": "External adapter completed without inline output."}
    _reject_sensitive_text(adapter_output_text, "adapter_output_text")
    try:
        parsed = json.loads(adapter_output_text)
    except json.JSONDecodeError:
        return {"public_message": _short_summary(adapter_output_text)}
    if not isinstance(parsed, Mapping):
        raise ExternalAdapterOutputError("adapter output JSON must be an object")
    _reject_sensitive_fields(parsed, "adapter_output")
    return parsed


def _artifact_refs(value: Any) -> tuple[RuntimeArtifactRef, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ExternalAdapterOutputError("artifact_refs must be a list")
    return tuple(runtime_artifact_ref_from_dict(item) for item in value)


def _memory_proposals(value: Any) -> tuple[RuntimeMemoryProposal, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ExternalAdapterOutputError("memory proposals must be a list")
    return tuple(runtime_memory_proposal_from_dict(item) for item in value)


def _safety_requests(value: Any) -> tuple[RuntimeSafetyRequest, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ExternalAdapterOutputError("safety_requests must be a list")
    return tuple(runtime_safety_request_from_dict(item) for item in value)


def _error_from_output(
    output: ExternalAdapterRawOutput, final_state: RuntimeState
) -> RuntimeErrorInfo:
    code = _error_code_for_state(final_state)
    return RuntimeErrorInfo(
        code=code,
        message=output.safe_summary,
        safe_summary=output.safe_summary,
        retryable=code == RuntimeErrorCode.RETRYABLE,
        source=output.adapter_id,
        created_at=output.completed_at,
        raw_error_ref=output.raw_error_ref or output.raw_output_ref,
    )


def _error_code_for_state(final_state: RuntimeState) -> RuntimeErrorCode:
    if final_state == RuntimeState.TIMED_OUT:
        return RuntimeErrorCode.TIMED_OUT
    if final_state == RuntimeState.CANCELLED:
        return RuntimeErrorCode.CANCELLED
    return RuntimeErrorCode.NON_RETRYABLE


def _runtime_state_from_backend_state(state: ExternalAdapterBackendState) -> RuntimeState:
    if state == ExternalAdapterBackendState.SUCCEEDED:
        return RuntimeState.SUCCEEDED
    if state == ExternalAdapterBackendState.TIMED_OUT:
        return RuntimeState.TIMED_OUT
    if state == ExternalAdapterBackendState.CANCELLED:
        return RuntimeState.CANCELLED
    return RuntimeState.FAILED


def _validate_raw_output(output: ExternalAdapterRawOutput) -> None:
    if not output.invocation_id:
        raise ExternalAdapterOutputError("invocation_id must be non-empty")
    if not output.adapter_id:
        raise ExternalAdapterOutputError("adapter_id must be non-empty")
    if not output.safe_summary:
        raise ExternalAdapterOutputError("safe_summary must be non-empty")
    if not output.completed_at:
        raise ExternalAdapterOutputError("completed_at must be non-empty")
    _reject_sensitive_text(output.safe_summary, "safe_summary")
    _reject_sensitive_fields(dict(output.metrics or {}), "metrics")


def _audit_text(request: RuntimeRequest, output: ExternalAdapterRawOutput) -> str:
    return (
        f"External adapter {output.adapter_id} finished task {request.task_id} "
        f"with state {_runtime_state_from_backend_state(output.state).value}: "
        f"{output.safe_summary}"
    )


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ExternalAdapterOutputError("expected a non-empty string")
    _reject_sensitive_text(value, "output_string")
    return value


def _short_summary(text: str) -> str:
    return text.strip()[:500] or "External adapter returned empty text."


def _reject_sensitive_fields(value: Any, field_name: str) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if isinstance(key, str) and key.lower() in _SENSITIVE_FIELD_NAMES:
                raise ExternalAdapterOutputError(
                    f"{field_name} must not include sensitive field: {key}"
                )
            _reject_sensitive_fields(nested, f"{field_name}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _reject_sensitive_fields(nested, f"{field_name}[{index}]")
    elif isinstance(value, str):
        _reject_sensitive_text(value, field_name)


def _reject_sensitive_text(value: str, field_name: str) -> None:
    lowered = value.lower()
    for marker in ("api_key", "credential", "private_memory", "raw_transcript"):
        if marker in lowered:
            raise ExternalAdapterOutputError(
                f"{field_name} must not include sensitive marker: {marker}"
            )


def failed_external_adapter_parse_result(
    request: RuntimeRequest,
    output: ExternalAdapterRawOutput,
    *,
    started_at: str,
    message: str,
) -> RuntimeResult:
    """Build a failed result for callers that caught an output parse error."""

    error = RuntimeErrorInfo(
        code=RuntimeErrorCode.OUTPUT_PARSE_ERROR,
        message=message,
        safe_summary="External adapter output could not be parsed safely.",
        retryable=False,
        source=output.adapter_id,
        created_at=utc_timestamp(),
        raw_error_ref=output.raw_error_ref or output.raw_output_ref,
    )
    return RuntimeResult(
        request_id=request.request_id,
        task_id=request.task_id,
        worker_id=request.worker_id,
        runtime_type=RuntimeType.EXTERNAL_ADAPTER,
        final_state=RuntimeState.FAILED,
        started_at=started_at,
        completed_at=error.created_at,
        internal_summary=error.safe_summary,
        audit_summary=_audit_text(request, output),
        error=error,
    )

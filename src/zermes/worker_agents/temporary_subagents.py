"""Contracts for task-scoped temporary subagents created by workers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

from .profile import validate_worker_id
from .runtime_contract import (
    RuntimeContractError,
    RuntimeExecutionBudget,
    RuntimeRequest,
    RuntimeRequestContext,
    RuntimeResult,
    RuntimeState,
    RuntimeType,
    runtime_result_to_dict,
)
from .task_state import validate_task_id


class TemporarySubagentError(ValueError):
    """Raised when a temporary subagent contract is invalid."""


class TemporarySubagentTerminalState(StrEnum):
    """Terminal lifecycle states for one temporary subagent session."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    REJECTED = "rejected"
    CLEANED = "cleaned"


class TemporarySubagentResultReturnPolicy(StrEnum):
    """Where temporary subagent output is allowed to return."""

    PARENT_WORKER_ONLY = "parent_worker_only"
    PARENT_RUNTIME_RESULT = "parent_runtime_result"


class TemporarySubagentRuntimeKind(StrEnum):
    """Managed execution path requested for a temporary subagent."""

    SHARED_RUNTIME = "shared_runtime"
    EXTERNAL_ADAPTER = "external_adapter"
    DELEGATE_TASK_ADAPTER = "delegate_task_adapter"


_ALLOWED_RUNTIME_TYPES = {
    RuntimeType.TEMPORARY_SUBAGENT,
    RuntimeType.EXTERNAL_ADAPTER,
    RuntimeType.DELEGATE_TASK_ADAPTER,
}

_SENSITIVE_FIELD_NAMES = frozenset(
    {
        "api_key",
        "complete_transcript",
        "credential",
        "credentials",
        "default_chat",
        "department",
        "department_id",
        "durable_profile",
        "durable_profile_ref",
        "environment",
        "full_transcript",
        "memory",
        "persistent_skill_binding",
        "persistent_skill_bindings",
        "private_memory",
        "private_memory_path",
        "private_memory_text",
        "raw_output",
        "raw_stderr",
        "raw_stdout",
        "raw_transcript",
        "registry_lifecycle",
        "registry_status",
        "refresh_token",
        "secret",
        "stderr",
        "stdout",
        "token",
        "worker_id",
    }
)


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise TemporarySubagentError(f"{field_name} must be a non-empty string")
    return value


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, field_name)


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TemporarySubagentError(f"{field_name} must be a positive integer")
    return value


def _optional_positive_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, field_name)


def _optional_non_negative_number(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise TemporarySubagentError(f"{field_name} must be a non-negative number")
    return float(value)


def _string_tuple(value: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TemporarySubagentError(f"{field_name} must be a tuple of strings")
    if any(not isinstance(item, str) or not item for item in value):
        raise TemporarySubagentError(f"{field_name} must contain non-empty strings")
    return value


def _coerce_runtime_type(value: RuntimeType | str) -> RuntimeType:
    raw_value = value.value if isinstance(value, RuntimeType) else value
    _require_string(raw_value, "requested_runtime_type")
    try:
        runtime_type = RuntimeType(raw_value)
    except ValueError as exc:
        raise TemporarySubagentError(
            f"Unknown requested_runtime_type: {raw_value!r}"
        ) from exc
    if runtime_type not in _ALLOWED_RUNTIME_TYPES:
        raise TemporarySubagentError(
            "temporary subagent runtime must be temporary_subagent, "
            "external_adapter, or delegate_task_adapter"
        )
    return runtime_type


def _coerce_return_policy(
    value: TemporarySubagentResultReturnPolicy | str,
) -> TemporarySubagentResultReturnPolicy:
    raw_value = value.value if isinstance(value, TemporarySubagentResultReturnPolicy) else value
    _require_string(raw_value, "result_return_policy")
    try:
        return TemporarySubagentResultReturnPolicy(raw_value)
    except ValueError as exc:
        raise TemporarySubagentError(
            f"Unknown result_return_policy: {raw_value!r}"
        ) from exc


def _coerce_terminal_state(
    value: TemporarySubagentTerminalState | str,
) -> TemporarySubagentTerminalState:
    raw_value = value.value if isinstance(value, TemporarySubagentTerminalState) else value
    _require_string(raw_value, "terminal_state")
    try:
        return TemporarySubagentTerminalState(raw_value)
    except ValueError as exc:
        raise TemporarySubagentError(f"Unknown terminal_state: {raw_value!r}") from exc


def _reject_sensitive_fields(value: Any, field_name: str) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if isinstance(key, str) and key.lower() in _SENSITIVE_FIELD_NAMES:
                raise TemporarySubagentError(
                    f"{field_name} must not include persistent or sensitive field: {key}"
                )
            _reject_sensitive_fields(nested, f"{field_name}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _reject_sensitive_fields(nested, f"{field_name}[{index}]")


@dataclass(frozen=True)
class TemporarySubagentProfileOverlay:
    """Task-only persona and output constraints for a temporary subagent."""

    role_name: str
    task_instructions: str
    output_contract: str
    tool_guidance: tuple[str, ...] = ()
    context_limits: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        _require_string(self.role_name, "profile_overlay.role_name")
        _require_string(self.task_instructions, "profile_overlay.task_instructions")
        _require_string(self.output_contract, "profile_overlay.output_contract")
        _string_tuple(self.tool_guidance, "profile_overlay.tool_guidance")
        context_limits = dict(self.context_limits or {})
        _reject_sensitive_fields(context_limits, "profile_overlay.context_limits")
        object.__setattr__(self, "context_limits", context_limits)


@dataclass(frozen=True)
class TemporarySubagentRequest:
    """Validated request to create one task-scoped temporary subagent."""

    delegation_id: str
    parent_worker_id: str
    task_id: str
    purpose: str
    requested_runtime_type: RuntimeType | str
    profile_overlay: TemporarySubagentProfileOverlay
    result_return_policy: TemporarySubagentResultReturnPolicy | str
    parent_runtime_session_id: str | None = None
    parent_request_id: str | None = None
    temporary_subagent_id: str | None = None
    requested_model: str | None = None
    requested_tools: tuple[str, ...] = ()
    workspace_read_roots: tuple[str, ...] = ()
    workspace_write_roots: tuple[str, ...] = ()
    context_refs: tuple[str, ...] = ()
    artifact_manifest_refs: tuple[str, ...] = ()
    max_task_tokens: int | None = None
    max_task_cost_usd: float | None = None
    timeout_seconds: int | None = None

    def __post_init__(self) -> None:
        _require_string(self.delegation_id, "delegation_id")
        validate_worker_id(self.parent_worker_id)
        validate_task_id(self.task_id)
        _require_string(self.purpose, "purpose")
        object.__setattr__(
            self,
            "requested_runtime_type",
            _coerce_runtime_type(self.requested_runtime_type),
        )
        if not isinstance(self.profile_overlay, TemporarySubagentProfileOverlay):
            raise TemporarySubagentError(
                "profile_overlay must be a TemporarySubagentProfileOverlay"
            )
        object.__setattr__(
            self,
            "result_return_policy",
            _coerce_return_policy(self.result_return_policy),
        )
        _optional_string(self.parent_runtime_session_id, "parent_runtime_session_id")
        _optional_string(self.parent_request_id, "parent_request_id")
        _optional_string(self.temporary_subagent_id, "temporary_subagent_id")
        _optional_string(self.requested_model, "requested_model")
        for field_name in (
            "requested_tools",
            "workspace_read_roots",
            "workspace_write_roots",
            "context_refs",
            "artifact_manifest_refs",
        ):
            _string_tuple(getattr(self, field_name), field_name)
        _optional_positive_int(self.max_task_tokens, "max_task_tokens")
        _optional_non_negative_number(self.max_task_cost_usd, "max_task_cost_usd")
        _optional_positive_int(self.timeout_seconds, "timeout_seconds")
        if (
            self.max_task_tokens is None
            and self.max_task_cost_usd is None
            and self.timeout_seconds is None
        ):
            raise TemporarySubagentError(
                "temporary subagent request requires a token, cost, or timeout limit"
            )


@dataclass(frozen=True)
class TemporarySubagentResultEnvelope:
    """Parent-worker-facing result wrapper for a temporary subagent session."""

    delegation_id: str
    parent_worker_id: str
    task_id: str
    terminal_state: TemporarySubagentTerminalState | str
    runtime_result: RuntimeResult | None = None
    runtime_result_ref: str | None = None
    cleanup_status: str = "pending"
    audit_summary: str | None = None

    def __post_init__(self) -> None:
        _require_string(self.delegation_id, "delegation_id")
        validate_worker_id(self.parent_worker_id)
        validate_task_id(self.task_id)
        object.__setattr__(
            self, "terminal_state", _coerce_terminal_state(self.terminal_state)
        )
        if self.runtime_result is not None and not isinstance(
            self.runtime_result, RuntimeResult
        ):
            raise TemporarySubagentError("runtime_result must be a RuntimeResult")
        _optional_string(self.runtime_result_ref, "runtime_result_ref")
        _require_string(self.cleanup_status, "cleanup_status")
        _optional_string(self.audit_summary, "audit_summary")
        if self.runtime_result is None and self.runtime_result_ref is None:
            raise TemporarySubagentError(
                "temporary subagent result requires runtime_result or runtime_result_ref"
            )
        if self.runtime_result is not None:
            expected_state = _terminal_state_from_runtime_state(
                self.runtime_result.final_state
            )
            if self.terminal_state != expected_state:
                raise TemporarySubagentError(
                    "terminal_state must match runtime_result final_state"
                )


def temporary_subagent_request_to_dict(
    request: TemporarySubagentRequest,
) -> dict[str, Any]:
    """Return a deterministic, audit-safe mapping for one request."""

    return {
        "delegation_id": request.delegation_id,
        "parent_worker_id": request.parent_worker_id,
        "task_id": request.task_id,
        "purpose": request.purpose,
        "requested_runtime_type": request.requested_runtime_type.value,
        "profile_overlay": temporary_subagent_profile_overlay_to_dict(
            request.profile_overlay
        ),
        "result_return_policy": request.result_return_policy.value,
        "parent_runtime_session_id": request.parent_runtime_session_id,
        "parent_request_id": request.parent_request_id,
        "temporary_subagent_id": request.temporary_subagent_id,
        "requested_model": request.requested_model,
        "requested_tools": list(request.requested_tools),
        "workspace_read_roots": list(request.workspace_read_roots),
        "workspace_write_roots": list(request.workspace_write_roots),
        "context_refs": list(request.context_refs),
        "artifact_manifest_refs": list(request.artifact_manifest_refs),
        "max_task_tokens": request.max_task_tokens,
        "max_task_cost_usd": request.max_task_cost_usd,
        "timeout_seconds": request.timeout_seconds,
    }


def temporary_subagent_profile_overlay_to_dict(
    overlay: TemporarySubagentProfileOverlay,
) -> dict[str, Any]:
    """Return a JSON-safe profile overlay without durable identity fields."""

    return {
        "role_name": overlay.role_name,
        "task_instructions": overlay.task_instructions,
        "output_contract": overlay.output_contract,
        "tool_guidance": list(overlay.tool_guidance),
        "context_limits": dict(overlay.context_limits or {}),
    }


def temporary_subagent_result_envelope_to_dict(
    envelope: TemporarySubagentResultEnvelope,
) -> dict[str, Any]:
    """Return a JSON-safe result envelope for parent-worker consumption."""

    return {
        "delegation_id": envelope.delegation_id,
        "parent_worker_id": envelope.parent_worker_id,
        "task_id": envelope.task_id,
        "terminal_state": envelope.terminal_state.value,
        "runtime_result": (
            runtime_result_to_dict(envelope.runtime_result)
            if envelope.runtime_result is not None
            else None
        ),
        "runtime_result_ref": envelope.runtime_result_ref,
        "cleanup_status": envelope.cleanup_status,
        "audit_summary": envelope.audit_summary,
    }


def temporary_subagent_request_to_runtime_request(
    request: TemporarySubagentRequest,
    *,
    request_id: str,
    requested_by: str,
    created_at: str,
    session_ref: str | None = None,
) -> RuntimeRequest:
    """Convert a temporary subagent request to the shared runtime contract."""

    parent_request_id = request.parent_request_id or request.delegation_id
    return RuntimeRequest(
        request_id=request_id,
        task_id=request.task_id,
        worker_id=request.parent_worker_id,
        runtime_type=request.requested_runtime_type,
        requested_by=requested_by,
        created_at=created_at,
        context=RuntimeRequestContext(
            input_message=request.purpose,
            thread_summary_refs=request.context_refs,
            artifact_manifest_refs=request.artifact_manifest_refs,
            allowed_tool_descriptions=tuple(
                f"{tool_name}: allowed for this temporary subagent"
                for tool_name in request.requested_tools
            ),
            workspace_policy_ref="temporary-subagent:effective-workspace",
            redaction_policy_ref="temporary-subagent:redaction-policy",
        ),
        budget=RuntimeExecutionBudget(
            budget_source=f"temporary-subagent:{request.delegation_id}",
            model=request.requested_model,
            max_output_tokens=request.max_task_tokens,
            max_cost_usd=request.max_task_cost_usd,
            timeout_seconds=request.timeout_seconds,
        ),
        session_ref=session_ref,
        parent_request_id=parent_request_id,
    )


def _terminal_state_from_runtime_state(
    runtime_state: RuntimeState | str,
) -> TemporarySubagentTerminalState:
    state = RuntimeState(runtime_state)
    if state == RuntimeState.SUCCEEDED:
        return TemporarySubagentTerminalState.SUCCEEDED
    if state == RuntimeState.TIMED_OUT:
        return TemporarySubagentTerminalState.TIMED_OUT
    if state == RuntimeState.CANCELLED:
        return TemporarySubagentTerminalState.CANCELLED
    if state == RuntimeState.FAILED:
        return TemporarySubagentTerminalState.FAILED
    raise TemporarySubagentError(
        "runtime_result final_state must be a terminal runtime state"
    )

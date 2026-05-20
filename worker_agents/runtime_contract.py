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
    thread_summary_refs: tuple[str, ...] = ()
    organization_summary_refs: tuple[str, ...] = ()
    artifact_manifest_refs: tuple[str, ...] = ()
    allowed_tool_descriptions: tuple[str, ...] = ()
    workspace_policy_ref: str | None = None
    redaction_policy_ref: str | None = None
    relevant_excerpts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_string(self.input_message, "input_message")
        for field_name in (
            "thread_summary_refs",
            "organization_summary_refs",
            "artifact_manifest_refs",
            "allowed_tool_descriptions",
            "relevant_excerpts",
        ):
            _string_tuple(getattr(self, field_name), field_name)
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


def dump_runtime_request_json(request: RuntimeRequest) -> str:
    """Serialize a runtime request with stable key ordering for audit logs."""

    return json.dumps(runtime_request_to_dict(request), ensure_ascii=False, sort_keys=True)


def load_runtime_request_json(payload: str) -> RuntimeRequest:
    return runtime_request_from_dict(json.loads(payload))

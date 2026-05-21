"""Managed runner facade for external agent adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Mapping, Protocol

from .external_adapters import (
    ExternalAdapterDefinition,
    ExternalAdapterError,
    ExternalAdapterRegistry,
    validate_external_adapter_request,
)
from .runtime_contract import (
    RuntimeErrorCode,
    RuntimeErrorInfo,
    RuntimeEvent,
    RuntimeEventType,
    RuntimeRequest,
    RuntimeState,
    RuntimeType,
    utc_timestamp,
)
from .storage import WorkerAgentRuntimeDataStore


class ExternalAdapterRunnerError(ValueError):
    """Raised when an external adapter invocation cannot be managed safely."""


class ExternalAdapterBackendState(StrEnum):
    """Execution states reported by an external adapter backend."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ExternalAdapterInputBundle:
    """Low-sensitive input bundle passed to an external adapter backend."""

    task_summary: str
    context_summaries: tuple[str, ...] = ()
    manifest_refs: tuple[str, ...] = ()
    allowed_workspace_refs: tuple[str, ...] = ()
    permission_instructions: tuple[str, ...] = ()
    expected_output_contract: str = "runtime_result_candidate"
    redaction_policy_ref: str | None = None


@dataclass(frozen=True)
class ExternalAdapterRunRequest:
    """Inputs required to start one managed external adapter invocation."""

    adapter_id: str
    runtime_request: RuntimeRequest
    timeout_seconds: int | None = None


@dataclass(frozen=True)
class ExternalAdapterHealthReport:
    """Low-sensitive health check outcome for one adapter."""

    adapter_id: str
    healthy: bool
    checked_at: str
    safe_summary: str
    error: RuntimeErrorInfo | None = None


@dataclass(frozen=True)
class ExternalAdapterBackendStart:
    """Backend response after a start request has been accepted."""

    backend_invocation_id: str
    state: ExternalAdapterBackendState = ExternalAdapterBackendState.RUNNING
    safe_summary: str = "External adapter started."
    raw_output_ref: str | None = None
    raw_error_ref: str | None = None


@dataclass(frozen=True)
class ExternalAdapterBackendSnapshot:
    """Low-sensitive backend progress snapshot."""

    backend_invocation_id: str
    state: ExternalAdapterBackendState
    safe_summary: str
    raw_output_ref: str | None = None
    raw_error_ref: str | None = None


@dataclass(frozen=True)
class ExternalAdapterInvocation:
    """Tracked external adapter invocation and its current safe state."""

    invocation_id: str
    adapter_id: str
    request_id: str
    task_id: str
    worker_id: str
    input_bundle: ExternalAdapterInputBundle
    state: RuntimeState
    events: tuple[RuntimeEvent, ...]
    raw_output_ref: str | None = None
    raw_error_ref: str | None = None


class ExternalAdapterBackend(Protocol):
    """Minimal backend interface; concrete adapters implement this boundary."""

    def health_check(
        self, definition: ExternalAdapterDefinition, timeout_seconds: int
    ) -> ExternalAdapterHealthReport:
        """Return a low-sensitive adapter health report."""

    def start(
        self,
        definition: ExternalAdapterDefinition,
        invocation_id: str,
        input_bundle: ExternalAdapterInputBundle,
        timeout_seconds: int | None,
    ) -> ExternalAdapterBackendStart:
        """Start one invocation without accepting arbitrary shell commands."""

    def cancel(self, invocation_id: str) -> ExternalAdapterBackendSnapshot:
        """Request cancellation for one backend invocation."""

    def poll(self, invocation_id: str) -> ExternalAdapterBackendSnapshot:
        """Return the latest backend invocation snapshot."""


@dataclass
class FakeExternalAdapterBackend:
    """Deterministic external adapter backend for unit tests."""

    healthy: bool = True
    start_state: ExternalAdapterBackendState = ExternalAdapterBackendState.RUNNING
    start_summary: str = "Fake external adapter started."
    raw_output_ref: str | None = None
    raw_error_ref: str | None = None
    snapshots: dict[str, ExternalAdapterBackendSnapshot] = field(default_factory=dict)

    def health_check(
        self, definition: ExternalAdapterDefinition, timeout_seconds: int
    ) -> ExternalAdapterHealthReport:
        if self.healthy:
            return ExternalAdapterHealthReport(
                adapter_id=definition.adapter_id,
                healthy=True,
                checked_at=utc_timestamp(),
                safe_summary="External adapter health check passed.",
            )
        error = RuntimeErrorInfo(
            code=RuntimeErrorCode.ADAPTER_UNHEALTHY,
            message="External adapter health check failed.",
            safe_summary="External adapter is unavailable.",
            retryable=True,
            source=definition.adapter_id,
            created_at=utc_timestamp(),
            raw_error_ref=self.raw_error_ref,
        )
        return ExternalAdapterHealthReport(
            adapter_id=definition.adapter_id,
            healthy=False,
            checked_at=error.created_at,
            safe_summary=error.safe_summary,
            error=error,
        )

    def start(
        self,
        definition: ExternalAdapterDefinition,
        invocation_id: str,
        input_bundle: ExternalAdapterInputBundle,
        timeout_seconds: int | None,
    ) -> ExternalAdapterBackendStart:
        snapshot = ExternalAdapterBackendSnapshot(
            backend_invocation_id=invocation_id,
            state=self.start_state,
            safe_summary=self.start_summary,
            raw_output_ref=self.raw_output_ref,
            raw_error_ref=self.raw_error_ref,
        )
        self.snapshots[invocation_id] = snapshot
        return ExternalAdapterBackendStart(
            backend_invocation_id=invocation_id,
            state=self.start_state,
            safe_summary=self.start_summary,
            raw_output_ref=self.raw_output_ref,
            raw_error_ref=self.raw_error_ref,
        )

    def cancel(self, invocation_id: str) -> ExternalAdapterBackendSnapshot:
        snapshot = ExternalAdapterBackendSnapshot(
            backend_invocation_id=invocation_id,
            state=ExternalAdapterBackendState.CANCELLED,
            safe_summary="External adapter invocation was cancelled.",
        )
        self.snapshots[invocation_id] = snapshot
        return snapshot

    def poll(self, invocation_id: str) -> ExternalAdapterBackendSnapshot:
        try:
            return self.snapshots[invocation_id]
        except KeyError as exc:
            raise ExternalAdapterRunnerError(
                f"external adapter invocation is unknown: {invocation_id}"
            ) from exc


@dataclass
class ExternalAdapterRunner:
    """Prepare and track managed external adapter invocations."""

    registry: ExternalAdapterRegistry
    backend: ExternalAdapterBackend
    runtime_store: WorkerAgentRuntimeDataStore = field(
        default_factory=WorkerAgentRuntimeDataStore
    )
    _invocations: dict[str, ExternalAdapterInvocation] = field(default_factory=dict)

    def health_check(self, adapter_id: str) -> ExternalAdapterHealthReport:
        """Run the adapter's declared health check through the backend."""

        definition = self.registry.get(adapter_id)
        return self.backend.health_check(
            definition, definition.health_check.timeout_seconds
        )

    def start(self, request: ExternalAdapterRunRequest) -> ExternalAdapterInvocation:
        """Start a managed external adapter invocation."""

        definition = self.registry.get(request.adapter_id)
        validate_external_adapter_request(definition, request.runtime_request)
        input_bundle = build_external_adapter_input_bundle(
            request.runtime_request, self.runtime_store
        )
        backend_start = self.backend.start(
            definition,
            _invocation_id(request.runtime_request),
            input_bundle,
            request.timeout_seconds or request.runtime_request.budget.timeout_seconds,
        )
        events = _events_for_backend_start(request.runtime_request, backend_start)
        invocation = ExternalAdapterInvocation(
            invocation_id=backend_start.backend_invocation_id,
            adapter_id=definition.adapter_id,
            request_id=request.runtime_request.request_id,
            task_id=request.runtime_request.task_id,
            worker_id=request.runtime_request.worker_id,
            input_bundle=input_bundle,
            state=_runtime_state_from_backend_state(backend_start.state),
            events=events,
            raw_output_ref=backend_start.raw_output_ref,
            raw_error_ref=backend_start.raw_error_ref,
        )
        self._invocations[invocation.invocation_id] = invocation
        return invocation

    def cancel(self, invocation_id: str) -> ExternalAdapterInvocation:
        """Cancel a previously started external adapter invocation."""

        existing = self._get_invocation(invocation_id)
        snapshot = self.backend.cancel(invocation_id)
        events = existing.events + _events_for_snapshot(existing, snapshot, start_sequence=len(existing.events))
        updated = _replace_invocation(existing, snapshot, events)
        self._invocations[invocation_id] = updated
        return updated

    def poll(self, invocation_id: str) -> ExternalAdapterInvocation:
        """Poll a previously started external adapter invocation."""

        existing = self._get_invocation(invocation_id)
        snapshot = self.backend.poll(invocation_id)
        events = existing.events + _events_for_snapshot(existing, snapshot, start_sequence=len(existing.events))
        updated = _replace_invocation(existing, snapshot, events)
        self._invocations[invocation_id] = updated
        return updated

    def _get_invocation(self, invocation_id: str) -> ExternalAdapterInvocation:
        try:
            return self._invocations[invocation_id]
        except KeyError as exc:
            raise ExternalAdapterRunnerError(
                f"external adapter invocation is unknown: {invocation_id}"
            ) from exc


def build_external_adapter_input_bundle(
    request: RuntimeRequest, runtime_store: WorkerAgentRuntimeDataStore
) -> ExternalAdapterInputBundle:
    """Create the minimal low-sensitive input bundle for an adapter backend."""

    if request.runtime_type != RuntimeType.EXTERNAL_ADAPTER:
        raise ExternalAdapterRunnerError("request runtime_type must be external_adapter")
    task_dir = runtime_store.create_task_directory(request.task_id)
    input_bundle = ExternalAdapterInputBundle(
        task_summary=request.context.input_message,
        context_summaries=(
            request.context.thread_summary_refs
            + request.context.organization_summary_refs
            + request.context.relevant_excerpts
        ),
        manifest_refs=request.context.artifact_manifest_refs,
        allowed_workspace_refs=_optional_ref_tuple(request.context.workspace_policy_ref),
        permission_instructions=request.context.allowed_tool_descriptions,
        redaction_policy_ref=request.context.redaction_policy_ref,
    )
    _validate_input_bundle(input_bundle, task_dir)
    return input_bundle


def external_adapter_input_bundle_to_dict(
    input_bundle: ExternalAdapterInputBundle,
) -> dict[str, object]:
    """Return a JSON-safe adapter input bundle for audit records."""

    return {
        "task_summary": input_bundle.task_summary,
        "context_summaries": list(input_bundle.context_summaries),
        "manifest_refs": list(input_bundle.manifest_refs),
        "allowed_workspace_refs": list(input_bundle.allowed_workspace_refs),
        "permission_instructions": list(input_bundle.permission_instructions),
        "expected_output_contract": input_bundle.expected_output_contract,
        "redaction_policy_ref": input_bundle.redaction_policy_ref,
    }


def external_adapter_invocation_to_dict(
    invocation: ExternalAdapterInvocation,
) -> dict[str, object]:
    """Return a JSON-safe invocation summary without raw adapter output."""

    return {
        "invocation_id": invocation.invocation_id,
        "adapter_id": invocation.adapter_id,
        "request_id": invocation.request_id,
        "task_id": invocation.task_id,
        "worker_id": invocation.worker_id,
        "state": invocation.state.value,
        "input_bundle": external_adapter_input_bundle_to_dict(invocation.input_bundle),
        "event_ids": [event.event_id for event in invocation.events],
        "raw_output_ref": invocation.raw_output_ref,
        "raw_error_ref": invocation.raw_error_ref,
    }


def _optional_ref_tuple(value: str | None) -> tuple[str, ...]:
    return (value,) if value else ()


def _invocation_id(request: RuntimeRequest) -> str:
    return f"external-{request.request_id}"


def _validate_input_bundle(
    input_bundle: ExternalAdapterInputBundle, task_dir: Path
) -> None:
    data = external_adapter_input_bundle_to_dict(input_bundle)
    for key, value in data.items():
        if key in {"task_summary", "expected_output_contract"}:
            if not isinstance(value, str) or not value:
                raise ExternalAdapterRunnerError(f"{key} must be a non-empty string")
        elif key != "redaction_policy_ref" and not isinstance(value, list):
            raise ExternalAdapterRunnerError(f"{key} must be a list")
    if not task_dir.exists():
        raise ExternalAdapterRunnerError("task runtime directory was not created")


def _events_for_backend_start(
    request: RuntimeRequest, backend_start: ExternalAdapterBackendStart
) -> tuple[RuntimeEvent, ...]:
    started = _event(
        request,
        sequence=0,
        state=RuntimeState.STARTING,
        event_type=RuntimeEventType.STARTED,
        summary=backend_start.safe_summary,
    )
    if backend_start.state == ExternalAdapterBackendState.RUNNING:
        return (
            started,
            _event(
                request,
                sequence=1,
                state=RuntimeState.RUNNING,
                event_type=RuntimeEventType.HEARTBEAT,
                summary="External adapter is running.",
            ),
        )
    terminal_state = _runtime_state_from_backend_state(backend_start.state)
    return (
        started,
        _terminal_event(
            request,
            sequence=1,
            state=terminal_state,
            summary=backend_start.safe_summary,
        ),
    )


def _events_for_snapshot(
    invocation: ExternalAdapterInvocation,
    snapshot: ExternalAdapterBackendSnapshot,
    *,
    start_sequence: int,
) -> tuple[RuntimeEvent, ...]:
    request = _request_from_invocation(invocation)
    state = _runtime_state_from_backend_state(snapshot.state)
    if state == RuntimeState.RUNNING:
        return (
            _event(
                request,
                sequence=start_sequence,
                state=RuntimeState.RUNNING,
                event_type=RuntimeEventType.HEARTBEAT,
                summary=snapshot.safe_summary,
            ),
        )
    return (
        _terminal_event(
            request,
            sequence=start_sequence,
            state=state,
            summary=snapshot.safe_summary,
        ),
    )


def _event(
    request: RuntimeRequest,
    *,
    sequence: int,
    state: RuntimeState,
    event_type: RuntimeEventType,
    summary: str,
) -> RuntimeEvent:
    return RuntimeEvent(
        event_id=f"{request.request_id}-{sequence}",
        request_id=request.request_id,
        task_id=request.task_id,
        worker_id=request.worker_id,
        runtime_type=RuntimeType.EXTERNAL_ADAPTER,
        state=state,
        event_type=event_type,
        created_at=utc_timestamp(),
        sequence=sequence,
        payload={"safe_summary": summary},
    )


def _terminal_event(
    request: RuntimeRequest, *, sequence: int, state: RuntimeState, summary: str
) -> RuntimeEvent:
    event_type = (
        RuntimeEventType.COMPLETED
        if state == RuntimeState.SUCCEEDED
        else RuntimeEventType.ERROR
    )
    return _event(
        request,
        sequence=sequence,
        state=state,
        event_type=event_type,
        summary=summary,
    )


def _runtime_state_from_backend_state(state: ExternalAdapterBackendState) -> RuntimeState:
    if state == ExternalAdapterBackendState.RUNNING:
        return RuntimeState.RUNNING
    if state == ExternalAdapterBackendState.SUCCEEDED:
        return RuntimeState.SUCCEEDED
    if state == ExternalAdapterBackendState.TIMED_OUT:
        return RuntimeState.TIMED_OUT
    if state == ExternalAdapterBackendState.CANCELLED:
        return RuntimeState.CANCELLED
    return RuntimeState.FAILED


def _replace_invocation(
    invocation: ExternalAdapterInvocation,
    snapshot: ExternalAdapterBackendSnapshot,
    events: tuple[RuntimeEvent, ...],
) -> ExternalAdapterInvocation:
    return ExternalAdapterInvocation(
        invocation_id=invocation.invocation_id,
        adapter_id=invocation.adapter_id,
        request_id=invocation.request_id,
        task_id=invocation.task_id,
        worker_id=invocation.worker_id,
        input_bundle=invocation.input_bundle,
        state=_runtime_state_from_backend_state(snapshot.state),
        events=events,
        raw_output_ref=snapshot.raw_output_ref or invocation.raw_output_ref,
        raw_error_ref=snapshot.raw_error_ref or invocation.raw_error_ref,
    )


def _request_from_invocation(invocation: ExternalAdapterInvocation) -> RuntimeRequest:
    return RuntimeRequest(
        request_id=invocation.request_id,
        task_id=invocation.task_id,
        worker_id=invocation.worker_id,
        runtime_type=RuntimeType.EXTERNAL_ADAPTER,
        requested_by="external_adapter_runner",
        created_at=utc_timestamp(),
        context=RuntimeRequestContextForEvent(invocation.input_bundle),
        budget=RuntimeBudgetForEvent(),
    )


class RuntimeRequestContextForEvent:
    """Small context shim used only to construct follow-up events."""

    input_message: str
    thread_summary_refs: tuple[str, ...]
    organization_summary_refs: tuple[str, ...]
    artifact_manifest_refs: tuple[str, ...]
    allowed_tool_descriptions: tuple[str, ...]
    workspace_policy_ref: str | None
    redaction_policy_ref: str | None
    relevant_excerpts: tuple[str, ...]

    def __new__(cls, input_bundle: ExternalAdapterInputBundle):
        from .runtime_contract import RuntimeRequestContext

        return RuntimeRequestContext(
            input_message=input_bundle.task_summary,
            artifact_manifest_refs=input_bundle.manifest_refs,
            allowed_tool_descriptions=input_bundle.permission_instructions,
            workspace_policy_ref=(
                input_bundle.allowed_workspace_refs[0]
                if input_bundle.allowed_workspace_refs
                else None
            ),
            redaction_policy_ref=input_bundle.redaction_policy_ref,
            relevant_excerpts=input_bundle.context_summaries,
        )


class RuntimeBudgetForEvent:
    """Small budget shim used only to construct follow-up events."""

    def __new__(cls):
        from .runtime_contract import RuntimeExecutionBudget

        return RuntimeExecutionBudget(
            budget_source="external_adapter_invocation",
            timeout_seconds=1,
        )

"""Map internal runtime contract records back into worker task state."""

from __future__ import annotations

from .runtime_contract import (
    RuntimeErrorCode,
    RuntimeEvent,
    RuntimeEventType,
    RuntimeResult,
    RuntimeState,
    runtime_artifact_ref_to_dict,
    runtime_error_to_dict,
    runtime_memory_proposal_to_dict,
)
from .task_records import WorkerTaskEvent, WorkerTaskResult
from .task_service import WorkerTaskService
from .task_state import TERMINAL_TASK_STATUSES, WorkerTaskError, WorkerTaskState


class InternalWorkerRuntimeTaskIntegrationError(ValueError):
    """Raised when runtime records cannot be safely applied to task state."""


def mark_internal_runtime_started(
    task_service: WorkerTaskService,
    *,
    task_id: str,
    request_id: str,
    updated_by: str = "internal_worker_runtime",
) -> WorkerTaskState:
    """Move a queued worker task into running state and record its request id."""

    state = task_service.start_task(
        task_id,
        updated_by=updated_by,
        status_reason=f"Internal runtime started: {request_id}",
    )
    _save_runtime_state(
        task_service,
        state,
        {
            "runtime_request_id": request_id,
            "runtime_adapter": "internal_worker",
        },
    )
    return task_service.get_task(task_id)


def record_internal_runtime_event(
    task_service: WorkerTaskService,
    event: RuntimeEvent,
    *,
    source: str = "internal_worker_runtime",
) -> WorkerTaskEvent:
    """Append a low-sensitive runtime event to the task-local event stream."""

    task_event = WorkerTaskEvent(
        event_id=event.event_id,
        task_id=event.task_id,
        event_type=f"runtime_{event.event_type.value}",
        created_at=event.created_at,
        source=source,
        summary=_event_summary(event),
        metadata={
            "request_id": event.request_id,
            "worker_id": event.worker_id,
            "runtime_type": event.runtime_type.value,
            "runtime_state": event.state.value,
            "sequence": event.sequence,
            "payload": dict(event.payload or {}),
        },
    )
    task_service.task_store.append_event(task_event)
    if event.event_type in {
        RuntimeEventType.OUTPUT_CHUNK,
        RuntimeEventType.TOOL_CALL_SUMMARY,
        RuntimeEventType.ERROR,
        RuntimeEventType.COMPLETED,
    }:
        _append_rolling_summary(task_service, event.task_id, task_event.summary)
    return task_event


def finalize_internal_runtime_result(
    task_service: WorkerTaskService,
    result: RuntimeResult,
    *,
    updated_by: str = "internal_worker_runtime",
) -> WorkerTaskState:
    """Persist a compact runtime result and move the task to a terminal state."""

    current = task_service.get_task(result.task_id)
    if current.status in TERMINAL_TASK_STATUSES:
        raise WorkerTaskError(f"Task is already terminal: {result.task_id!r}")

    task_result = WorkerTaskResult(
        task_id=result.task_id,
        summary=_result_summary(result),
        artifact_paths=tuple(ref.manifest_ref for ref in result.artifact_refs),
        manifest_candidates=tuple(
            runtime_artifact_ref_to_dict(ref) for ref in result.artifact_refs
        ),
        memory_candidates=tuple(
            runtime_memory_proposal_to_dict(proposal)
            for proposal in (
                result.memory_proposals + result.department_asset_proposals
            )
        ),
        audit_summary_candidates=_audit_summary_candidates(result),
        metadata={
            "request_id": result.request_id,
            "runtime_type": result.runtime_type.value,
            "final_state": result.final_state.value,
            "partial_success": result.partial_success,
        },
    )
    task_service.task_store.save_task_result(task_result)
    _append_rolling_summary(task_service, result.task_id, task_result.summary)

    status_reason = task_result.summary
    result_data = {
        "runtime_request_id": result.request_id,
        "runtime_final_state": result.final_state.value,
        "public_message": result.public_message,
        "internal_summary": result.internal_summary,
        "artifact_count": len(result.artifact_refs),
        "memory_proposal_count": len(result.memory_proposals),
        "department_asset_proposal_count": len(result.department_asset_proposals),
        "safety_request_count": len(result.safety_requests),
    }
    if result.final_state == RuntimeState.SUCCEEDED:
        return task_service.complete_task(
            result.task_id,
            updated_by=updated_by,
            status_reason=status_reason,
            result=result_data,
        )
    if result.final_state == RuntimeState.CANCELLED:
        if task_service.get_task(result.task_id).status.value != "cancelling":
            task_service.request_cancel_task(
                result.task_id,
                updated_by=updated_by,
                status_reason=status_reason,
            )
        return task_service.cancel_task(
            result.task_id,
            updated_by=updated_by,
            status_reason=status_reason,
        )
    if result.final_state == RuntimeState.TIMED_OUT:
        return task_service.expire_task(
            result.task_id,
            updated_by=updated_by,
            status_reason=status_reason,
        )
    return task_service.fail_task(
        result.task_id,
        updated_by=updated_by,
        status_reason=status_reason,
    )


def _save_runtime_state(
    task_service: WorkerTaskService, state: WorkerTaskState, runtime_data: dict[str, str]
) -> None:
    updated_runtime = dict(state.runtime)
    updated_runtime.update(runtime_data)
    task_service.task_store.save_task_state(
        WorkerTaskState(
            **{
                **state.__dict__,
                "runtime": updated_runtime,
            }
        )
    )


def _event_summary(event: RuntimeEvent) -> str:
    payload = dict(event.payload or {})
    for key in ("summary", "message", "safe_summary"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return f"Runtime {event.event_type.value} in state {event.state.value}."


def _result_summary(result: RuntimeResult) -> str:
    if result.error is not None:
        return result.error.safe_summary
    if result.public_message:
        return result.public_message
    if result.internal_summary:
        return result.internal_summary
    if result.audit_summary:
        return result.audit_summary
    return f"Runtime completed with state {result.final_state.value}."


def _audit_summary_candidates(result: RuntimeResult) -> tuple[dict[str, str], ...]:
    candidates: list[dict[str, str]] = []
    if result.audit_summary:
        candidates.append({"summary": result.audit_summary})
    if result.error is not None:
        error_data = runtime_error_to_dict(result.error)
        candidates.append(
            {
                "summary": result.error.safe_summary,
                "error_code": error_data["code"],
            }
        )
    for safety_request in result.safety_requests:
        candidates.append(
            {
                "summary": safety_request.user_visible_summary,
                "request_id": safety_request.request_id,
                "request_type": safety_request.request_type,
            }
        )
    return tuple(candidates)


def _append_rolling_summary(
    task_service: WorkerTaskService, task_id: str, summary: str
) -> None:
    current = task_service.task_store.load_rolling_summary(task_id)
    if current:
        current = current.rstrip() + "\n"
    task_service.task_store.save_rolling_summary(task_id, current + f"- {summary}\n")


def runtime_error_code_to_final_state(code: RuntimeErrorCode) -> RuntimeState:
    """Return the terminal runtime state implied by a structured error code."""

    if code == RuntimeErrorCode.CANCELLED:
        return RuntimeState.CANCELLED
    if code == RuntimeErrorCode.TIMED_OUT:
        return RuntimeState.TIMED_OUT
    return RuntimeState.FAILED

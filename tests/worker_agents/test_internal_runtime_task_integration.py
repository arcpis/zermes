import pytest

from worker_agents.internal_runtime_task_integration import (
    finalize_internal_runtime_result,
    mark_internal_runtime_started,
    record_internal_runtime_event,
)
from worker_agents.profile import WorkerAgentProfile, WorkerBudgetPolicy
from worker_agents.registry_service import WorkerRegistryService
from worker_agents.runtime_contract import (
    RuntimeArtifactRef,
    RuntimeErrorCode,
    RuntimeErrorInfo,
    RuntimeEvent,
    RuntimeEventType,
    RuntimeResult,
    RuntimeState,
    RuntimeType,
)
from worker_agents.storage import WorkerAgentProfileStore, WorkerAgentRuntimeDataStore
from worker_agents.task_service import WorkerTaskService
from worker_agents.task_state import WorkerTaskError, WorkerTaskStatus


def _task_service(tmp_path):
    registry = WorkerRegistryService(
        WorkerAgentProfileStore(tmp_path / "profile" / "worker_agents"),
        now=lambda: "2026-05-21T00:00:00Z",
    )
    service = WorkerTaskService.from_registry_service(
        registry,
        runtime_store=WorkerAgentRuntimeDataStore(
            tmp_path / "install" / "data" / "worker_agents"
        ),
    )
    service.registry_service.register_worker(
        profile=WorkerAgentProfile(
            worker_id="researcher",
            display_name="Researcher",
            description="Research focused questions.",
            role="research",
            budgets=WorkerBudgetPolicy(max_task_tokens=1000, max_turn_tokens=200),
        )
    )
    service.registry_service.enable_worker("researcher")
    service.create_task(
        task_id="task-1",
        worker_id="researcher",
        title="Survey",
        objective="Summarize the current state.",
        queue=True,
    )
    return service


def _event(event_type=RuntimeEventType.OUTPUT_CHUNK, state=RuntimeState.RUNNING):
    return RuntimeEvent(
        event_id=f"event-{event_type.value}",
        request_id="runtime-request-1",
        task_id="task-1",
        worker_id="researcher",
        runtime_type=RuntimeType.INTERNAL_WORKER,
        state=state,
        event_type=event_type,
        created_at="2026-05-21T00:00:00Z",
        sequence=1,
        payload={"summary": "Collected approved context."},
    )


def _success_result():
    return RuntimeResult(
        request_id="runtime-request-1",
        task_id="task-1",
        worker_id="researcher",
        runtime_type=RuntimeType.INTERNAL_WORKER,
        final_state=RuntimeState.SUCCEEDED,
        started_at="2026-05-21T00:00:00Z",
        completed_at="2026-05-21T00:01:00Z",
        public_message="Done.",
        internal_summary="Completed with approved context only.",
        artifact_refs=(
            RuntimeArtifactRef(
                manifest_ref="artifacts/output.json",
                artifact_type="report",
                summary="Output report.",
            ),
        ),
        audit_summary="No private memory text was included.",
    )


def _error_result(final_state, code):
    return RuntimeResult(
        request_id="runtime-request-1",
        task_id="task-1",
        worker_id="researcher",
        runtime_type=RuntimeType.INTERNAL_WORKER,
        final_state=final_state,
        started_at="2026-05-21T00:00:00Z",
        completed_at="2026-05-21T00:01:00Z",
        error=RuntimeErrorInfo(
            code=code,
            message="Runtime stopped.",
            safe_summary=f"Runtime ended as {final_state.value}.",
            retryable=False,
            source="internal_worker_runtime",
            created_at="2026-05-21T00:01:00Z",
        ),
    )


def test_marks_runtime_started_and_records_request_id(tmp_path):
    service = _task_service(tmp_path)

    state = mark_internal_runtime_started(
        service,
        task_id="task-1",
        request_id="runtime-request-1",
    )

    assert state.status == WorkerTaskStatus.RUNNING
    assert state.runtime["runtime_request_id"] == "runtime-request-1"
    assert state.runtime["runtime_adapter"] == "internal_worker"


def test_records_runtime_event_and_updates_summary(tmp_path):
    service = _task_service(tmp_path)
    mark_internal_runtime_started(
        service,
        task_id="task-1",
        request_id="runtime-request-1",
    )

    task_event = record_internal_runtime_event(service, _event())

    assert task_event.event_type == "runtime_output_chunk"
    assert task_event.metadata["runtime_state"] == "running"
    assert "Collected approved context" in service.task_store.load_rolling_summary(
        "task-1"
    )


def test_success_result_saves_compact_result_and_completes_task(tmp_path):
    service = _task_service(tmp_path)
    mark_internal_runtime_started(
        service,
        task_id="task-1",
        request_id="runtime-request-1",
    )

    state = finalize_internal_runtime_result(service, _success_result())
    result = service.task_store.load_task_result("task-1")

    assert state.status == WorkerTaskStatus.SUCCEEDED
    assert state.result["artifact_count"] == 1
    assert result.summary == "Done."
    assert result.manifest_candidates[0]["manifest_ref"] == "artifacts/output.json"
    assert result.audit_summary_candidates[0]["summary"] == (
        "No private memory text was included."
    )


@pytest.mark.parametrize(
    ("final_state", "code", "task_status"),
    [
        (RuntimeState.FAILED, RuntimeErrorCode.NON_RETRYABLE, WorkerTaskStatus.FAILED),
        (RuntimeState.TIMED_OUT, RuntimeErrorCode.TIMED_OUT, WorkerTaskStatus.EXPIRED),
        (RuntimeState.CANCELLED, RuntimeErrorCode.CANCELLED, WorkerTaskStatus.CANCELLED),
    ],
)
def test_error_results_map_to_task_terminal_states(
    tmp_path, final_state, code, task_status
):
    service = _task_service(tmp_path)
    mark_internal_runtime_started(
        service,
        task_id="task-1",
        request_id="runtime-request-1",
    )

    state = finalize_internal_runtime_result(service, _error_result(final_state, code))

    assert state.status == task_status


def test_rejects_repeated_terminal_finalize(tmp_path):
    service = _task_service(tmp_path)
    mark_internal_runtime_started(
        service,
        task_id="task-1",
        request_id="runtime-request-1",
    )
    finalize_internal_runtime_result(service, _success_result())

    with pytest.raises(WorkerTaskError, match="already terminal"):
        finalize_internal_runtime_result(service, _success_result())

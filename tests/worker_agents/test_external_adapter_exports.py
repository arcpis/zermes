from worker_agents import (
    ExternalAdapterBackendState,
    ExternalAdapterRegistry,
    ExternalAdapterRunRequest,
    ExternalAdapterRunner,
    FakeExternalAdapterBackend,
    build_fake_external_adapter_definition,
    normalize_external_adapter_output,
)
from worker_agents.external_adapter_output import ExternalAdapterRawOutput
from worker_agents.runtime_contract import (
    RuntimeExecutionBudget,
    RuntimeRequest,
    RuntimeRequestContext,
    RuntimeState,
    RuntimeType,
)
from worker_agents.storage import WorkerAgentRuntimeDataStore


def test_external_adapter_public_exports_work_together(tmp_path):
    registry = ExternalAdapterRegistry()
    registry.register(build_fake_external_adapter_definition())
    request = RuntimeRequest(
        request_id="runtime-request-1",
        task_id="task-1",
        worker_id="researcher",
        runtime_type=RuntimeType.EXTERNAL_ADAPTER,
        requested_by="zermes_main_agent",
        created_at="2026-05-21T00:00:00Z",
        context=RuntimeRequestContext(
            input_message="Summarize this task.",
            allowed_tool_descriptions=("read_file: approved files only",),
        ),
        budget=RuntimeExecutionBudget(
            budget_source="worker-profile:researcher",
            timeout_seconds=30,
        ),
    )
    runner = ExternalAdapterRunner(
        registry=registry,
        backend=FakeExternalAdapterBackend(),
        runtime_store=WorkerAgentRuntimeDataStore(
            tmp_path / "install" / "data" / "worker_agents"
        ),
    )

    invocation = runner.start(
        ExternalAdapterRunRequest(
            adapter_id="fake-external-adapter",
            runtime_request=request,
        )
    )
    result = normalize_external_adapter_output(
        request,
        ExternalAdapterRawOutput(
            invocation_id=invocation.invocation_id,
            adapter_id=invocation.adapter_id,
            state=ExternalAdapterBackendState.SUCCEEDED,
            safe_summary="Completed through public exports.",
            completed_at="2026-05-21T00:01:00Z",
            adapter_output_text="Done.",
        ),
        started_at="2026-05-21T00:00:30Z",
    )

    assert invocation.state == RuntimeState.RUNNING
    assert result.final_state == RuntimeState.SUCCEEDED
    assert result.public_message == "Done."

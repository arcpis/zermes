from worker_agents.external_adapter_runner import (
    ExternalAdapterBackendState,
    ExternalAdapterRunRequest,
    ExternalAdapterRunner,
    FakeExternalAdapterBackend,
    build_external_adapter_input_bundle,
    external_adapter_invocation_to_dict,
)
from worker_agents.external_adapters import (
    ExternalAdapterRegistry,
    build_fake_external_adapter_definition,
)
from worker_agents.runtime_contract import (
    RuntimeErrorCode,
    RuntimeExecutionBudget,
    RuntimeRequest,
    RuntimeRequestContext,
    RuntimeState,
    RuntimeType,
)
from worker_agents.storage import WorkerAgentRuntimeDataStore


def _request(**context_overrides):
    context = {
        "input_message": "Use only the approved task summary.",
        "artifact_manifest_refs": ("manifests/input.json",),
        "allowed_tool_descriptions": ("read_file: approved files only",),
        "workspace_policy_ref": "policies/workspace.json",
        "redaction_policy_ref": "policies/redaction.json",
    }
    context.update(context_overrides)
    return RuntimeRequest(
        request_id="runtime-request-1",
        task_id="task-1",
        worker_id="researcher",
        runtime_type=RuntimeType.EXTERNAL_ADAPTER,
        requested_by="zermes_main_agent",
        created_at="2026-05-21T00:00:00Z",
        context=RuntimeRequestContext(**context),
        budget=RuntimeExecutionBudget(
            budget_source="worker-profile:researcher",
            timeout_seconds=30,
            max_output_bytes=10000,
        ),
    )


def _runner(tmp_path, backend=None):
    registry = ExternalAdapterRegistry()
    registry.register(build_fake_external_adapter_definition())
    return ExternalAdapterRunner(
        registry=registry,
        backend=backend or FakeExternalAdapterBackend(),
        runtime_store=WorkerAgentRuntimeDataStore(
            tmp_path / "install" / "data" / "worker_agents"
        ),
    )


def test_build_input_bundle_uses_middle_data_task_directory(tmp_path):
    runtime_store = WorkerAgentRuntimeDataStore(
        tmp_path / "install" / "data" / "worker_agents"
    )

    bundle = build_external_adapter_input_bundle(_request(), runtime_store)

    assert bundle.task_summary == "Use only the approved task summary."
    assert bundle.manifest_refs == ("manifests/input.json",)
    assert bundle.permission_instructions == ("read_file: approved files only",)
    assert runtime_store.task_runtime_path("task-1", "artifacts").exists()


def test_runner_health_check_failure_returns_low_sensitive_error(tmp_path):
    runner = _runner(
        tmp_path,
        backend=FakeExternalAdapterBackend(
            healthy=False,
            raw_error_ref="tasks/task-1/logs/health.err",
        ),
    )

    report = runner.health_check("fake-external-adapter")

    assert report.healthy is False
    assert report.error is not None
    assert report.error.code == RuntimeErrorCode.ADAPTER_UNHEALTHY
    assert report.error.raw_error_ref == "tasks/task-1/logs/health.err"


def test_runner_starts_registered_adapter(tmp_path):
    runner = _runner(tmp_path)

    invocation = runner.start(
        ExternalAdapterRunRequest(
            adapter_id="fake-external-adapter",
            runtime_request=_request(),
        )
    )

    assert invocation.invocation_id == "external-runtime-request-1"
    assert invocation.state == RuntimeState.RUNNING
    assert [event.state for event in invocation.events] == [
        RuntimeState.STARTING,
        RuntimeState.RUNNING,
    ]
    assert external_adapter_invocation_to_dict(invocation)["raw_output_ref"] is None


def test_runner_rejects_unregistered_adapter(tmp_path):
    runner = _runner(tmp_path)

    try:
        runner.start(
            ExternalAdapterRunRequest(
                adapter_id="missing-adapter",
                runtime_request=_request(),
            )
        )
    except Exception as exc:
        assert "not registered" in str(exc)
    else:
        raise AssertionError("unregistered adapter was not rejected")


def test_runner_cancel_updates_invocation_state(tmp_path):
    runner = _runner(tmp_path)
    invocation = runner.start(
        ExternalAdapterRunRequest(
            adapter_id="fake-external-adapter",
            runtime_request=_request(),
        )
    )

    cancelled = runner.cancel(invocation.invocation_id)

    assert cancelled.state == RuntimeState.CANCELLED
    assert cancelled.events[-1].state == RuntimeState.CANCELLED


def test_runner_timeout_backend_state_becomes_runtime_timeout(tmp_path):
    runner = _runner(
        tmp_path,
        backend=FakeExternalAdapterBackend(
            start_state=ExternalAdapterBackendState.TIMED_OUT,
            start_summary="Fake adapter timed out.",
            raw_error_ref="tasks/task-1/logs/timeout.err",
        ),
    )

    invocation = runner.start(
        ExternalAdapterRunRequest(
            adapter_id="fake-external-adapter",
            runtime_request=_request(),
        )
    )

    assert invocation.state == RuntimeState.TIMED_OUT
    assert invocation.raw_error_ref == "tasks/task-1/logs/timeout.err"
    assert invocation.events[-1].payload["safe_summary"] == "Fake adapter timed out."

from dataclasses import dataclass

import pytest

from worker_agents.external_adapter_runner import (
    ExternalAdapterBackendState,
    ExternalAdapterRunner,
    FakeExternalAdapterBackend,
)
from worker_agents.external_adapters import (
    ExternalAdapterRegistry,
    build_fake_external_adapter_definition,
)
from worker_agents.profile import (
    WorkerAgentProfile,
    WorkerBudgetPolicy,
    WorkerDelegationPolicy,
    WorkerExecutionLimits,
    WorkerModelSettings,
    WorkerToolPolicy,
    WorkerWorkspacePolicy,
)
from worker_agents.runtime_boundary import AgentRuntimeSessionConfig
from worker_agents.runtime_contract import RuntimeResult, RuntimeState, RuntimeType
from worker_agents.storage import WorkerAgentRuntimeDataStore
from worker_agents.temporary_subagent_runner import (
    TemporarySubagentRunner,
    TemporarySubagentRunnerError,
    run_temporary_subagent,
    temporary_subagent_run_to_dict,
)
from worker_agents.temporary_subagents import (
    TemporarySubagentProfileOverlay,
    TemporarySubagentRequest,
    TemporarySubagentResultReturnPolicy,
)


@dataclass
class RecordingFacade:
    run_config: AgentRuntimeSessionConfig | None = None

    def run(self, config):
        self.run_config = config
        return _Invocation(parent_worker_id=config.persona.parent_worker_id)


@dataclass(frozen=True)
class _Invocation:
    parent_worker_id: str | None


class FakeDelegateTaskAdapter:
    def run(self, request, runtime_request, session_config):
        return RuntimeResult(
            request_id=runtime_request.request_id,
            task_id=runtime_request.task_id,
            worker_id=runtime_request.worker_id,
            runtime_type=RuntimeType.DELEGATE_TASK_ADAPTER,
            final_state=RuntimeState.SUCCEEDED,
            started_at=runtime_request.created_at,
            completed_at="2026-05-21T00:00:01Z",
            internal_summary="Delegate task returned.",
        )


def _profile(**overrides):
    data = {
        "worker_id": "researcher",
        "display_name": "Researcher",
        "description": "Research focused questions.",
        "role": "research",
        "tools": WorkerToolPolicy(allowed_tools=("read_file", "search_notes")),
        "workspace": WorkerWorkspacePolicy(
            read_roots=("workspace/project",),
            write_roots=("workspace/project/tmp",),
        ),
        "model": WorkerModelSettings(
            default_model="fast-model",
            allowed_models=("fast-model",),
        ),
        "budgets": WorkerBudgetPolicy(
            max_task_tokens=1000,
            max_turn_tokens=200,
            max_task_cost_usd=2.0,
        ),
        "limits": WorkerExecutionLimits(
            max_concurrent_tasks=2,
            timeout_seconds=60,
        ),
        "delegation": WorkerDelegationPolicy(
            allow_temporary_child_agents=True,
            allowed_child_models=("fast-model",),
            allowed_child_tools=("read_file",),
            max_child_task_tokens=300,
        ),
    }
    data.update(overrides)
    return WorkerAgentProfile(**data)


def _request(**overrides):
    data = {
        "delegation_id": "delegation-1",
        "parent_worker_id": "researcher",
        "task_id": "task-1",
        "purpose": "Explore one narrow question.",
        "requested_runtime_type": RuntimeType.TEMPORARY_SUBAGENT,
        "profile_overlay": TemporarySubagentProfileOverlay(
            role_name="Focused Explorer",
            task_instructions="Use the supplied context only.",
            output_contract="Return findings.",
        ),
        "result_return_policy": TemporarySubagentResultReturnPolicy.PARENT_WORKER_ONLY,
        "parent_request_id": "parent-request",
        "requested_model": "fast-model",
        "requested_tools": ("read_file",),
        "workspace_read_roots": ("workspace/project/docs",),
        "workspace_write_roots": ("workspace/project/tmp/child",),
        "max_task_tokens": 250,
        "max_task_cost_usd": 1.0,
        "timeout_seconds": 30,
    }
    data.update(overrides)
    return TemporarySubagentRequest(**data)


def test_runner_uses_effective_policy_for_shared_runtime(tmp_path):
    facade = RecordingFacade()
    run = TemporarySubagentRunner(
        parent_profile=_profile(),
        facade=facade,
        runtime_store=WorkerAgentRuntimeDataStore(tmp_path / "data" / "worker_agents"),
    ).run(_request(), request_id="temporary-request")

    assert run.state == RuntimeState.SUCCEEDED
    assert run.runtime_request.request_id == "temporary-request"
    assert run.session_config.persona.parent_worker_id == "researcher"
    assert run.session_config.permissions.allowed_tool_names == ("read_file",)
    assert run.session_config.profile_summary.worker_id is None
    assert run.result_envelope is not None
    assert facade.run_config == run.session_config
    assert (tmp_path / "data" / "worker_agents" / "tasks" / "task-1").exists()


def test_runner_rejects_denied_policy_without_starting_runtime(tmp_path):
    facade = RecordingFacade()
    runner = TemporarySubagentRunner(
        parent_profile=_profile(delegation=WorkerDelegationPolicy()),
        facade=facade,
        runtime_store=WorkerAgentRuntimeDataStore(tmp_path / "data" / "worker_agents"),
    )

    with pytest.raises(TemporarySubagentRunnerError, match="cannot create"):
        runner.run(_request())

    assert facade.run_config is None


def test_runner_wraps_external_adapter_terminal_failure(tmp_path):
    registry = ExternalAdapterRegistry()
    registry.register(build_fake_external_adapter_definition(adapter_id="codex-lite"))
    external_runner = ExternalAdapterRunner(
        registry=registry,
        backend=FakeExternalAdapterBackend(
            start_state=ExternalAdapterBackendState.FAILED,
            start_summary="External adapter failed safely.",
        ),
        runtime_store=WorkerAgentRuntimeDataStore(tmp_path / "data" / "worker_agents"),
    )

    run = run_temporary_subagent(
        _profile(),
        _request(
            requested_runtime_type=RuntimeType.EXTERNAL_ADAPTER,
            temporary_subagent_id="codex-lite",
        ),
        runtime_store=WorkerAgentRuntimeDataStore(tmp_path / "data" / "worker_agents"),
        external_adapter_runner=external_runner,
    )

    assert run.state == RuntimeState.FAILED
    assert run.result_envelope is not None
    assert run.result_envelope.terminal_state.value == "failed"
    assert run.result_envelope.runtime_result.error is not None


def test_runner_uses_delegate_task_adapter_result(tmp_path):
    run = run_temporary_subagent(
        _profile(),
        _request(requested_runtime_type=RuntimeType.DELEGATE_TASK_ADAPTER),
        runtime_store=WorkerAgentRuntimeDataStore(tmp_path / "data" / "worker_agents"),
        delegate_task_adapter=FakeDelegateTaskAdapter(),
    )

    assert run.state == RuntimeState.SUCCEEDED
    assert run.result_envelope is not None
    assert run.result_envelope.runtime_result.runtime_type == RuntimeType.DELEGATE_TASK_ADAPTER


def test_runner_summary_does_not_expose_raw_outputs(tmp_path):
    run = run_temporary_subagent(
        _profile(),
        _request(),
        facade=RecordingFacade(),
        runtime_store=WorkerAgentRuntimeDataStore(tmp_path / "data" / "worker_agents"),
    )

    data = temporary_subagent_run_to_dict(run)

    assert data["state"] == "succeeded"
    assert "runtime_result" not in data

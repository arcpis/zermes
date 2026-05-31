from dataclasses import dataclass

from worker_agents.internal_runtime_context import InternalWorkerRuntimeContextRequest
from worker_agents.internal_runtime_runner import (
    InternalWorkerRuntimeRunner,
    prepare_internal_worker_runtime_run,
    run_internal_worker_runtime_task,
)
from worker_agents.profile import (
    WorkerAgentProfile,
    WorkerBudgetPolicy,
    WorkerModelSettings,
    WorkerToolPolicy,
    WorkerWorkspacePolicy,
)
from worker_agents.registry_service import WorkerRegistryService
from worker_agents.runtime_boundary import AgentRuntimeSessionConfig
from worker_agents.runtime_contract import RuntimeType
from worker_agents.storage import WorkerAgentProfileStore, WorkerAgentRuntimeDataStore
from worker_agents.task_service import WorkerTaskService


@dataclass
class RecordingFacade:
    prepared_config: AgentRuntimeSessionConfig | None = None
    run_config: AgentRuntimeSessionConfig | None = None

    def prepare_invocation(self, config):
        self.prepared_config = config
        return _Invocation(worker_id=config.persona.worker_id)

    def run(self, config):
        self.run_config = config
        return _Invocation(worker_id=config.persona.worker_id)


@dataclass(frozen=True)
class _Invocation:
    worker_id: str | None


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
            tools=WorkerToolPolicy(allowed_tools=("read_file",)),
            workspace=WorkerWorkspacePolicy(read_roots=("workspace/project",)),
            model=WorkerModelSettings(default_model="fast-model"),
            budgets=WorkerBudgetPolicy(max_task_tokens=1000, max_turn_tokens=200),
        )
    )
    service.registry_service.enable_worker("researcher")
    service.create_task(
        task_id="task-1",
        worker_id="researcher",
        title="Survey",
        objective="Summarize the current state.",
        budgets={"max_task_tokens": 500},
        queue=True,
    )
    return service


def test_runner_prepares_internal_runtime_request_and_session(tmp_path):
    service = _task_service(tmp_path)
    facade = RecordingFacade()
    runner = InternalWorkerRuntimeRunner(task_service=service, facade=facade)

    prepared = runner.prepare_run(
        InternalWorkerRuntimeContextRequest(
            worker_id="researcher",
            task_id="task-1",
            thread_summary_refs=("threads/task-1/summary.md",),
        ),
        request_id="runtime-request-1",
    )

    assert prepared.runtime_request.request_id == "runtime-request-1"
    assert prepared.runtime_request.runtime_type == RuntimeType.INTERNAL_WORKER
    assert prepared.runtime_request.context.thread_summary_refs == (
        "threads/task-1/summary.md",
    )
    assert prepared.session_config.persona.worker_id == "researcher"
    assert prepared.invocation.worker_id == "researcher"
    assert facade.prepared_config == prepared.session_config


def test_runner_run_uses_shared_facade_run(tmp_path):
    service = _task_service(tmp_path)
    facade = RecordingFacade()
    runner = InternalWorkerRuntimeRunner(task_service=service, facade=facade)

    invocation = runner.run(
        InternalWorkerRuntimeContextRequest(worker_id="researcher", task_id="task-1")
    )

    assert invocation.worker_id == "researcher"
    assert facade.run_config is not None


def test_runner_runtime_request_returns_routable_result_and_finalizes_task(tmp_path):
    service = _task_service(tmp_path)
    facade = RecordingFacade()
    runner = InternalWorkerRuntimeRunner(task_service=service, facade=facade)
    prepared = runner.prepare_run(
        InternalWorkerRuntimeContextRequest(worker_id="researcher", task_id="task-1"),
        request_id="runtime-request-1",
    )

    result = runner.run_runtime_request(prepared.runtime_request)

    assert result.request_id == "runtime-request-1"
    assert result.worker_id == "researcher"
    assert result.public_message
    assert service.get_task("task-1").status.value == "succeeded"
    assert facade.run_config is not None


def test_convenience_entrypoints(tmp_path):
    service = _task_service(tmp_path)
    facade = RecordingFacade()

    prepared = prepare_internal_worker_runtime_run(
        service,
        InternalWorkerRuntimeContextRequest(worker_id="researcher", task_id="task-1"),
        facade=facade,
    )
    invocation = run_internal_worker_runtime_task(
        service,
        InternalWorkerRuntimeContextRequest(worker_id="researcher", task_id="task-1"),
        facade=facade,
    )

    assert prepared.runtime_request.worker_id == "researcher"
    assert invocation.worker_id == "researcher"

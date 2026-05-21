"""Internal managed worker runner built on the shared runtime facade."""

from __future__ import annotations

from dataclasses import dataclass, field

from .internal_runtime_context import (
    InternalWorkerRuntimeContext,
    InternalWorkerRuntimeContextRequest,
    build_internal_worker_runtime_context,
)
from .runtime_boundary import AgentRuntimeSessionConfig
from .runtime_contract import RuntimeRequest, RuntimeType
from .runtime_facade import AgentRuntimeInvocation, SharedAgentRuntimeFacade
from .task_service import WorkerTaskService


class InternalWorkerRuntimeRunnerError(ValueError):
    """Raised when an internal worker runtime run cannot be prepared."""


@dataclass(frozen=True)
class PreparedInternalWorkerRuntimeRun:
    """Prepared internal runtime inputs before live model or tool execution."""

    context: InternalWorkerRuntimeContext
    runtime_request: RuntimeRequest
    session_config: AgentRuntimeSessionConfig
    invocation: AgentRuntimeInvocation


@dataclass
class InternalWorkerRuntimeRunner:
    """Prepare and invoke internal worker tasks through the shared facade."""

    task_service: WorkerTaskService
    facade: SharedAgentRuntimeFacade = field(default_factory=SharedAgentRuntimeFacade)

    def prepare_run(
        self,
        request: InternalWorkerRuntimeContextRequest,
        *,
        request_id: str | None = None,
    ) -> PreparedInternalWorkerRuntimeRun:
        """Prepare one internal worker runtime run without sending final messages."""

        context = build_internal_worker_runtime_context(self.task_service, request)
        runtime_request = RuntimeRequest(
            request_id=request_id or f"runtime-{request.task_id}",
            task_id=request.task_id,
            worker_id=request.worker_id,
            runtime_type=RuntimeType.INTERNAL_WORKER,
            requested_by=context.requested_by,
            created_at=self.task_service.registry_service.now(),
            context=context.request_context,
            budget=context.execution_budget,
            session_ref=f"runtime-sessions/{request.task_id}.json",
        )
        session_config = AgentRuntimeSessionConfig(
            scope=context.session_scope,
            persona=context.persona,
            profile_summary=context.profile_summary,
            permissions=context.permissions,
            budget=context.session_budget,
            context=context.session_context,
        )
        invocation = self.facade.prepare_invocation(session_config)
        return PreparedInternalWorkerRuntimeRun(
            context=context,
            runtime_request=runtime_request,
            session_config=session_config,
            invocation=invocation,
        )

    def run(
        self,
        request: InternalWorkerRuntimeContextRequest,
        *,
        request_id: str | None = None,
    ) -> AgentRuntimeInvocation:
        """Run the current facade entrypoint for an internal worker task.

        The shared facade currently prepares a validated invocation. Future live
        execution can replace the facade implementation without changing this
        runner boundary.
        """

        prepared = self.prepare_run(request, request_id=request_id)
        return self.facade.run(prepared.session_config)


def prepare_internal_worker_runtime_run(
    task_service: WorkerTaskService,
    request: InternalWorkerRuntimeContextRequest,
    *,
    facade: SharedAgentRuntimeFacade | None = None,
    request_id: str | None = None,
) -> PreparedInternalWorkerRuntimeRun:
    """Convenience entrypoint for callers that do not need a runner instance."""

    return InternalWorkerRuntimeRunner(
        task_service=task_service,
        facade=facade or SharedAgentRuntimeFacade(),
    ).prepare_run(request, request_id=request_id)


def run_internal_worker_runtime_task(
    task_service: WorkerTaskService,
    request: InternalWorkerRuntimeContextRequest,
    *,
    facade: SharedAgentRuntimeFacade | None = None,
    request_id: str | None = None,
) -> AgentRuntimeInvocation:
    """Prepare the shared runtime invocation for one internal worker task."""

    return InternalWorkerRuntimeRunner(
        task_service=task_service,
        facade=facade or SharedAgentRuntimeFacade(),
    ).run(request, request_id=request_id)

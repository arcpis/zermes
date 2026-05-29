"""Internal managed worker runner built on the shared runtime facade."""

from __future__ import annotations

from dataclasses import dataclass, field

from .internal_runtime_context import (
    InternalWorkerRuntimeContext,
    InternalWorkerRuntimeContextRequest,
    build_internal_worker_runtime_context,
)
from .runtime_boundary import AgentRuntimeSessionConfig
from .runtime_contract import RuntimeErrorCode, RuntimeErrorInfo, RuntimeRequest, RuntimeResult, RuntimeState, RuntimeType
from .runtime_facade import AgentRuntimeExecution, AgentRuntimeInvocation, SharedAgentRuntimeFacade
from .internal_runtime_task_integration import (
    finalize_internal_runtime_result,
    mark_internal_runtime_started,
)
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
    ) -> AgentRuntimeInvocation | AgentRuntimeExecution:
        """Run the facade entrypoint for an internal worker task.

        When the facade has a ``WorkerLLMExecutor``, this returns an
        ``AgentRuntimeExecution`` with the LLM reply.  Otherwise it
        returns the prepared ``AgentRuntimeInvocation``.
        """

        prepared = self.prepare_run(request, request_id=request_id)
        return self.facade.run(prepared.session_config)

    def run_runtime_request(self, request: RuntimeRequest) -> RuntimeResult:
        """Run a chat-built runtime request and return a routable result.

        When the facade has a ``WorkerLLMExecutor``, ``run()`` returns an
        ``AgentRuntimeExecution`` with the LLM reply.  Otherwise it
        returns an ``AgentRuntimeInvocation`` (original stub behaviour).
        Both paths produce a ``RuntimeResult`` with the appropriate
        public_message and internal_summary.
        """

        if not isinstance(request, RuntimeRequest):
            raise InternalWorkerRuntimeRunnerError(
                "run_runtime_request requires a RuntimeRequest"
            )
        context_request = _context_request_from_runtime_request(request)
        mark_internal_runtime_started(
            self.task_service,
            task_id=request.task_id,
            request_id=request.request_id,
        )
        run_result = self.run(context_request, request_id=request.request_id)
        timestamp = self.task_service.registry_service.now()

        if isinstance(run_result, AgentRuntimeExecution):
            public_message = run_result.public_message
            internal_summary = run_result.internal_summary
            llm = run_result.llm_result
            if llm is not None and llm.error is not None:
                final_state = RuntimeState.FAILED
                audit_summary = "Internal worker runtime request failed during LLM execution."
                error_info = RuntimeErrorInfo(
                    code=RuntimeErrorCode.NON_RETRYABLE,
                    message=llm.error,
                    safe_summary="Worker runtime could not produce a reply for this message.",
                    retryable=False,
                    source="worker_llm_executor",
                    created_at=timestamp,
                )
            elif llm is not None:
                final_state = RuntimeState.SUCCEEDED
                audit_summary = "Internal worker runtime request executed through LLM."
                error_info = None
            else:
                final_state = RuntimeState.SUCCEEDED
                audit_summary = "Internal worker runtime request reached the shared runtime facade."
                error_info = None
        else:
            public_message = _public_message_from_invocation(run_result)
            internal_summary = _internal_summary_from_invocation(run_result)
            final_state = RuntimeState.SUCCEEDED
            audit_summary = "Internal worker runtime request reached the shared runtime facade."
            error_info = None

        result = RuntimeResult(
            request_id=request.request_id,
            task_id=request.task_id,
            worker_id=request.worker_id,
            runtime_type=RuntimeType.INTERNAL_WORKER,
            final_state=final_state,
            started_at=request.created_at,
            completed_at=timestamp,
            public_message=public_message,
            internal_summary=internal_summary,
            audit_summary=audit_summary,
            error=error_info,
        )
        finalize_internal_runtime_result(self.task_service, result)
        return result


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
) -> AgentRuntimeInvocation | AgentRuntimeExecution:
    """Run the facade entrypoint for one internal worker task."""

    return InternalWorkerRuntimeRunner(
        task_service=task_service,
        facade=facade or SharedAgentRuntimeFacade(),
    ).run(request, request_id=request_id)


def run_internal_worker_runtime_request(
    task_service: WorkerTaskService,
    request: RuntimeRequest,
    *,
    facade: SharedAgentRuntimeFacade | None = None,
) -> RuntimeResult:
    """Run a prebuilt runtime request and return a terminal runtime result."""

    return InternalWorkerRuntimeRunner(
        task_service=task_service,
        facade=facade or SharedAgentRuntimeFacade(),
    ).run_runtime_request(request)


def _context_request_from_runtime_request(
    request: RuntimeRequest,
) -> InternalWorkerRuntimeContextRequest:
    context = request.context
    return InternalWorkerRuntimeContextRequest(
        worker_id=request.worker_id,
        task_id=request.task_id,
        requested_by=request.requested_by,
        thread_summary_refs=context.thread_summary_refs,
        organization_summary_refs=context.organization_summary_refs,
        artifact_manifest_refs=context.artifact_manifest_refs,
        relevant_excerpts=context.relevant_excerpts,
        current_thread_id=context.source_thread_id,
        current_thread_summary=context.target_context_summary,
    )


def _public_message_from_invocation(invocation: AgentRuntimeInvocation) -> str:
    explicit_message = getattr(invocation, "public_message", None)
    if isinstance(explicit_message, str) and explicit_message.strip():
        return explicit_message.strip()
    display_name = (
        getattr(invocation, "display_name", None)
        or getattr(invocation, "worker_id", None)
        or "Worker"
    )
    return (
        f"{display_name} received the request and prepared an internal runtime "
        "session for execution."
    )


def _internal_summary_from_invocation(invocation: AgentRuntimeInvocation) -> str:
    allowed_tool_names = getattr(invocation, "allowed_tool_names", ())
    worker_label = (
        getattr(invocation, "worker_id", None)
        or getattr(invocation, "display_name", None)
        or "Worker"
    )
    return (
        f"Prepared internal worker invocation for "
        f"{worker_label} with "
        f"{len(allowed_tool_names)} allowed tool(s)."
    )

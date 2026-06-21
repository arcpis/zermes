"""Runner facade for task-scoped temporary subagents."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol

from .external_adapter_runner import (
    ExternalAdapterInvocation,
    ExternalAdapterRunRequest,
    ExternalAdapterRunner,
)
from .runtime_boundary import (
    AgentRuntimeLifecycle,
    AgentRuntimePersona,
    AgentRuntimeRole,
    AgentRuntimeSessionConfig,
    AgentRuntimeSessionScope,
    RuntimeBudgetSnapshot,
    RuntimeContextBundle,
    RuntimePermissionSnapshot,
    RuntimeProfileSummary,
)
from .runtime_contract import (
    RuntimeErrorCode,
    RuntimeErrorInfo,
    RuntimeRequest,
    RuntimeResult,
    RuntimeState,
    RuntimeType,
    utc_timestamp,
)
from .runtime_facade import AgentRuntimeInvocation, SharedAgentRuntimeFacade
from .storage import WorkerAgentRuntimeDataStore
from .temporary_subagent_policy import (
    TemporarySubagentPolicyDecision,
    evaluate_temporary_subagent_policy,
    temporary_subagent_policy_decision_to_dict,
)
from .temporary_subagents import (
    TemporarySubagentRequest,
    TemporarySubagentResultEnvelope,
    TemporarySubagentTerminalState,
    temporary_subagent_request_to_dict,
    temporary_subagent_request_to_runtime_request,
)
from .profile import WorkerAgentProfile


class TemporarySubagentRunnerError(ValueError):
    """Raised when a temporary subagent run cannot be managed safely."""


class DelegateTaskAdapter(Protocol):
    """Small adapter boundary for existing delegate-task style execution."""

    def run(
        self,
        request: TemporarySubagentRequest,
        runtime_request: RuntimeRequest,
        session_config: AgentRuntimeSessionConfig,
    ) -> RuntimeResult:
        """Execute one delegated task and return a normalized runtime result."""


@dataclass(frozen=True)
class TemporarySubagentRun:
    """Tracked temporary subagent invocation and parent-facing result state."""

    delegation_id: str
    runtime_request: RuntimeRequest
    policy_decision: TemporarySubagentPolicyDecision
    session_config: AgentRuntimeSessionConfig
    state: RuntimeState
    shared_invocation: AgentRuntimeInvocation | None = None
    external_invocation: ExternalAdapterInvocation | None = None
    result_envelope: TemporarySubagentResultEnvelope | None = None
    cleanup_status: str = "pending"


@dataclass
class TemporarySubagentRunner:
    """Create temporary subagent runtime sessions under parent policy."""

    parent_profile: WorkerAgentProfile
    facade: SharedAgentRuntimeFacade = field(default_factory=SharedAgentRuntimeFacade)
    runtime_store: WorkerAgentRuntimeDataStore = field(
        default_factory=WorkerAgentRuntimeDataStore
    )
    external_adapter_runner: ExternalAdapterRunner | None = None
    delegate_task_adapter: DelegateTaskAdapter | None = None
    active_child_count: int = 0
    remaining_task_tokens: int | None = None

    def run(
        self,
        request: TemporarySubagentRequest,
        *,
        request_id: str | None = None,
    ) -> TemporarySubagentRun:
        """Run the currently supported temporary subagent facade path."""

        decision = evaluate_temporary_subagent_policy(
            self.parent_profile,
            request,
            active_child_count=self.active_child_count,
            remaining_task_tokens=self.remaining_task_tokens,
        )
        if not decision.allowed or decision.effective_policy is None:
            raise TemporarySubagentRunnerError(decision.message)
        runtime_request = temporary_subagent_request_to_runtime_request(
            request,
            request_id=request_id or f"temporary-{request.delegation_id}",
            requested_by=self.parent_profile.worker_id,
            created_at=utc_timestamp(),
            session_ref=f"temporary-subagents/{request.delegation_id}/session.json",
        )
        session_config = _session_config_for_request(request, decision)
        _create_runtime_directory(self.runtime_store, request, decision)
        if request.requested_runtime_type == RuntimeType.EXTERNAL_ADAPTER:
            return self._run_external(request, runtime_request, session_config, decision)
        if request.requested_runtime_type == RuntimeType.DELEGATE_TASK_ADAPTER:
            return self._run_delegate(request, runtime_request, session_config, decision)
        return self._run_shared(request, runtime_request, session_config, decision)

    def _run_shared(
        self,
        request: TemporarySubagentRequest,
        runtime_request: RuntimeRequest,
        session_config: AgentRuntimeSessionConfig,
        decision: TemporarySubagentPolicyDecision,
    ) -> TemporarySubagentRun:
        invocation = self.facade.run(session_config)
        result = RuntimeResult(
            request_id=runtime_request.request_id,
            task_id=runtime_request.task_id,
            worker_id=runtime_request.worker_id,
            runtime_type=RuntimeType.TEMPORARY_SUBAGENT,
            final_state=RuntimeState.SUCCEEDED,
            started_at=runtime_request.created_at,
            completed_at=utc_timestamp(),
            internal_summary="Temporary subagent shared runtime invocation prepared.",
            audit_summary=decision.audit_summary,
        )
        envelope = _envelope_from_result(request, result)
        return TemporarySubagentRun(
            delegation_id=request.delegation_id,
            runtime_request=runtime_request,
            policy_decision=decision,
            session_config=session_config,
            state=RuntimeState.SUCCEEDED,
            shared_invocation=invocation,
            result_envelope=envelope,
        )

    def _run_external(
        self,
        request: TemporarySubagentRequest,
        runtime_request: RuntimeRequest,
        session_config: AgentRuntimeSessionConfig,
        decision: TemporarySubagentPolicyDecision,
    ) -> TemporarySubagentRun:
        if self.external_adapter_runner is None:
            raise TemporarySubagentRunnerError("external_adapter_runner is required")
        adapter_id = _require_adapter_id(request)
        invocation = self.external_adapter_runner.start(
            ExternalAdapterRunRequest(
                adapter_id=adapter_id,
                runtime_request=runtime_request,
                timeout_seconds=decision.effective_policy.timeout_seconds
                if decision.effective_policy
                else None,
            )
        )
        envelope = None
        if invocation.state in {
            RuntimeState.SUCCEEDED,
            RuntimeState.FAILED,
            RuntimeState.TIMED_OUT,
            RuntimeState.CANCELLED,
        }:
            envelope = _envelope_from_result(
                request,
                _result_from_external_invocation(runtime_request, invocation),
            )
        return TemporarySubagentRun(
            delegation_id=request.delegation_id,
            runtime_request=runtime_request,
            policy_decision=decision,
            session_config=session_config,
            state=invocation.state,
            external_invocation=invocation,
            result_envelope=envelope,
        )

    def _run_delegate(
        self,
        request: TemporarySubagentRequest,
        runtime_request: RuntimeRequest,
        session_config: AgentRuntimeSessionConfig,
        decision: TemporarySubagentPolicyDecision,
    ) -> TemporarySubagentRun:
        if self.delegate_task_adapter is None:
            raise TemporarySubagentRunnerError("delegate_task_adapter is required")
        result = self.delegate_task_adapter.run(request, runtime_request, session_config)
        envelope = _envelope_from_result(request, result)
        return TemporarySubagentRun(
            delegation_id=request.delegation_id,
            runtime_request=runtime_request,
            policy_decision=decision,
            session_config=session_config,
            state=result.final_state,
            result_envelope=envelope,
        )


def run_temporary_subagent(
    parent_profile: WorkerAgentProfile,
    request: TemporarySubagentRequest,
    *,
    facade: SharedAgentRuntimeFacade | None = None,
    runtime_store: WorkerAgentRuntimeDataStore | None = None,
    external_adapter_runner: ExternalAdapterRunner | None = None,
    delegate_task_adapter: DelegateTaskAdapter | None = None,
    active_child_count: int = 0,
    remaining_task_tokens: int | None = None,
    request_id: str | None = None,
) -> TemporarySubagentRun:
    """Convenience entrypoint for one temporary subagent run."""

    return TemporarySubagentRunner(
        parent_profile=parent_profile,
        facade=facade or SharedAgentRuntimeFacade(),
        runtime_store=runtime_store or WorkerAgentRuntimeDataStore(),
        external_adapter_runner=external_adapter_runner,
        delegate_task_adapter=delegate_task_adapter,
        active_child_count=active_child_count,
        remaining_task_tokens=remaining_task_tokens,
    ).run(request, request_id=request_id)


def temporary_subagent_run_to_dict(run: TemporarySubagentRun) -> dict[str, object]:
    """Return a JSON-safe run summary without raw transcripts."""

    return {
        "delegation_id": run.delegation_id,
        "runtime_request_id": run.runtime_request.request_id,
        "state": run.state.value,
        "policy_decision": temporary_subagent_policy_decision_to_dict(
            run.policy_decision
        ),
        "cleanup_status": run.cleanup_status,
        "has_result_envelope": run.result_envelope is not None,
    }


def _session_config_for_request(
    request: TemporarySubagentRequest,
    decision: TemporarySubagentPolicyDecision,
) -> AgentRuntimeSessionConfig:
    policy = decision.effective_policy
    if policy is None:
        raise TemporarySubagentRunnerError("allowed decision requires effective policy")
    return AgentRuntimeSessionConfig(
        scope=AgentRuntimeSessionScope.TEMPORARY_CHILD_TASK,
        persona=AgentRuntimePersona(
            role=AgentRuntimeRole.TEMPORARY_CHILD,
            lifecycle=AgentRuntimeLifecycle.TASK_SCOPED,
            display_name=request.profile_overlay.role_name,
            responsibility_summary=request.purpose,
            parent_worker_id=request.parent_worker_id,
            parent_task_id=request.task_id,
        ),
        profile_summary=RuntimeProfileSummary(worker_id=None),
        permissions=RuntimePermissionSnapshot(
            allowed_tool_names=policy.allowed_tools,
            workspace_read_roots=policy.workspace_read_roots,
            workspace_write_roots=policy.workspace_write_roots,
        ),
        budget=RuntimeBudgetSnapshot(
            model_name=policy.model_name,
            model_policy_ref=None if policy.model_name else "temporary-subagent:model",
            max_task_tokens=policy.max_task_tokens,
            max_task_cost_usd=policy.max_task_cost_usd,
            wall_time_seconds=policy.timeout_seconds,
            max_allowed_task_tokens=policy.max_task_tokens,
            max_allowed_task_cost_usd=policy.max_task_cost_usd,
        ),
        context=RuntimeContextBundle(
            user_instruction=request.profile_overlay.task_instructions,
            task_summary=request.purpose,
            thread_summary_refs=request.context_refs,
        ),
        cleanup_policy="task_scoped",
    )


def _create_runtime_directory(
    runtime_store: WorkerAgentRuntimeDataStore,
    request: TemporarySubagentRequest,
    decision: TemporarySubagentPolicyDecision,
) -> None:
    task_dir = runtime_store.create_task_directory(request.task_id)
    delegation_dir = task_dir / "temporary-subagents" / request.delegation_id
    delegation_dir.mkdir(parents=True, exist_ok=True)
    (delegation_dir / "request.json").write_text(
        json.dumps(
            temporary_subagent_request_to_dict(request),
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (delegation_dir / "policy.json").write_text(
        json.dumps(
            temporary_subagent_policy_decision_to_dict(decision),
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _require_adapter_id(request: TemporarySubagentRequest) -> str:
    adapter_id = request.temporary_subagent_id
    if not adapter_id:
        raise TemporarySubagentRunnerError(
            "external temporary subagent requires temporary_subagent_id as adapter id"
        )
    return adapter_id


def _result_from_external_invocation(
    runtime_request: RuntimeRequest, invocation: ExternalAdapterInvocation
) -> RuntimeResult:
    error = None
    if invocation.state != RuntimeState.SUCCEEDED:
        error = RuntimeErrorInfo(
            code=_error_code_for_state(invocation.state),
            message=invocation.state.value,
            safe_summary=invocation.events[-1].payload.get("safe_summary", invocation.state.value),
            retryable=invocation.state == RuntimeState.FAILED,
            source=invocation.adapter_id,
            created_at=utc_timestamp(),
            raw_error_ref=invocation.raw_error_ref,
        )
    return RuntimeResult(
        request_id=runtime_request.request_id,
        task_id=runtime_request.task_id,
        worker_id=runtime_request.worker_id,
        runtime_type=RuntimeType.EXTERNAL_ADAPTER,
        final_state=invocation.state,
        started_at=runtime_request.created_at,
        completed_at=utc_timestamp(),
        internal_summary=(
            invocation.events[-1].payload.get("safe_summary")
            if invocation.events
            else "External adapter completed."
        ),
        audit_summary=f"External temporary subagent adapter {invocation.adapter_id} completed.",
        error=error,
    )


def _error_code_for_state(state: RuntimeState) -> RuntimeErrorCode:
    if state == RuntimeState.TIMED_OUT:
        return RuntimeErrorCode.TIMED_OUT
    if state == RuntimeState.CANCELLED:
        return RuntimeErrorCode.CANCELLED
    return RuntimeErrorCode.RETRYABLE


def _envelope_from_result(
    request: TemporarySubagentRequest, result: RuntimeResult
) -> TemporarySubagentResultEnvelope:
    return TemporarySubagentResultEnvelope(
        delegation_id=request.delegation_id,
        parent_worker_id=request.parent_worker_id,
        task_id=request.task_id,
        terminal_state=_terminal_state_for_result(result),
        runtime_result=result,
        audit_summary="Temporary subagent result returned to parent worker.",
    )


def _terminal_state_for_result(
    result: RuntimeResult,
) -> TemporarySubagentTerminalState:
    if result.final_state == RuntimeState.SUCCEEDED:
        return TemporarySubagentTerminalState.SUCCEEDED
    if result.final_state == RuntimeState.TIMED_OUT:
        return TemporarySubagentTerminalState.TIMED_OUT
    if result.final_state == RuntimeState.CANCELLED:
        return TemporarySubagentTerminalState.CANCELLED
    return TemporarySubagentTerminalState.FAILED

"""Facade for preparing shared managed-agent runtime invocations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .runtime_boundary import (
    AgentRuntimeBoundaryError,
    AgentRuntimeRole,
    AgentRuntimeSessionConfig,
    AgentRuntimeSessionScope,
)

if TYPE_CHECKING:
    from .worker_llm_executor import WorkerLLMExecutor, WorkerLLMResult


@dataclass(frozen=True)
class AgentRuntimeInvocation:
    """Prepared runtime input without live model calls or tool execution."""

    role: AgentRuntimeRole
    scope: AgentRuntimeSessionScope
    display_name: str
    responsibility_summary: str
    worker_id: str | None
    parent_worker_id: str | None
    parent_task_id: str | None
    allowed_tool_names: tuple[str, ...]
    allowed_toolset_names: tuple[str, ...]
    workspace_read_roots: tuple[str, ...]
    workspace_write_roots: tuple[str, ...]
    model_name: str | None
    model_policy_ref: str | None
    max_task_tokens: int | None
    max_task_cost_usd: float | None
    cleanup_policy: str | None
    user_instruction: str
    task_summary: str


@dataclass(frozen=True)
class AgentRuntimeExecution:
    """Result of executing a prepared runtime invocation through the LLM."""

    invocation: AgentRuntimeInvocation
    llm_result: WorkerLLMResult | None = None

    @property
    def worker_id(self) -> str | None:
        return self.invocation.worker_id

    @property
    def display_name(self) -> str:
        return self.invocation.display_name

    @property
    def role(self) -> AgentRuntimeRole:
        return self.invocation.role

    @property
    def scope(self) -> AgentRuntimeSessionScope:
        return self.invocation.scope

    @property
    def has_llm_result(self) -> bool:
        return self.llm_result is not None

    @property
    def has_error(self) -> bool:
        return self.llm_result is not None and self.llm_result.error is not None

    @property
    def public_message(self) -> str:
        if self.llm_result is not None and self.llm_result.content:
            return self.llm_result.content
        display_name = self.invocation.display_name or self.invocation.worker_id or "Worker"
        return (
            f"{display_name} received the request and prepared an internal runtime "
            "session for execution."
        )

    @property
    def internal_summary(self) -> str:
        worker_label = self.invocation.worker_id or self.invocation.display_name or "Worker"
        if self.llm_result is not None:
            return (
                f"Executed internal worker invocation for {worker_label}: "
                f"{self.llm_result.turns_used} turn(s), "
                f"{self.llm_result.tool_calls_made} tool call(s), "
                f"finished_naturally={self.llm_result.finished_naturally}."
            )
        allowed = self.invocation.allowed_tool_names
        return (
            f"Prepared internal worker invocation for {worker_label} with "
            f"{len(allowed)} allowed tool(s)."
        )


class SharedAgentRuntimeFacade:
    """Single preparation point for all roles using the shared agent runtime.

    When a ``WorkerLLMExecutor`` is provided, ``run()`` delegates to
    ``execute_invocation()`` which calls the LLM through
    ``HermesAgentLoop``.  Without an executor, ``run()`` falls back to
    the original stub behaviour (prepare only).
    """

    def __init__(
        self,
        *,
        llm_executor: WorkerLLMExecutor | None = None,
    ) -> None:
        self._llm_executor = llm_executor

    def validate_session(
        self, config: AgentRuntimeSessionConfig
    ) -> AgentRuntimeSessionConfig:
        if not isinstance(config, AgentRuntimeSessionConfig):
            raise AgentRuntimeBoundaryError(
                "shared runtime requires an AgentRuntimeSessionConfig"
            )
        return config

    def prepare_invocation(
        self, config: AgentRuntimeSessionConfig
    ) -> AgentRuntimeInvocation:
        config = self.validate_session(config)
        return AgentRuntimeInvocation(
            role=config.persona.role,
            scope=config.scope,
            display_name=config.persona.display_name,
            responsibility_summary=config.persona.responsibility_summary,
            worker_id=config.persona.worker_id,
            parent_worker_id=config.persona.parent_worker_id,
            parent_task_id=config.persona.parent_task_id,
            allowed_tool_names=config.permissions.allowed_tool_names,
            allowed_toolset_names=config.permissions.allowed_toolset_names,
            workspace_read_roots=config.permissions.workspace_read_roots,
            workspace_write_roots=config.permissions.workspace_write_roots,
            model_name=config.budget.model_name,
            model_policy_ref=config.budget.model_policy_ref,
            max_task_tokens=config.budget.max_task_tokens,
            max_task_cost_usd=config.budget.max_task_cost_usd,
            cleanup_policy=config.cleanup_policy,
            user_instruction=config.context.user_instruction,
            task_summary=config.context.task_summary,
        )

    def run(self, config: AgentRuntimeSessionConfig) -> AgentRuntimeInvocation | AgentRuntimeExecution:
        """Prepare and optionally execute a runtime invocation.

        When a ``WorkerLLMExecutor`` was provided at construction, this
        method calls the LLM and returns an ``AgentRuntimeExecution``
        with the full result.  Otherwise it returns the prepared
        ``AgentRuntimeInvocation`` (original stub behaviour).
        """
        invocation = self.prepare_invocation(config)
        if self._llm_executor is not None:
            return self.execute_invocation(invocation)
        return invocation

    def execute_invocation(
        self, invocation: AgentRuntimeInvocation
    ) -> AgentRuntimeExecution:
        """Execute a prepared invocation through the LLM executor.

        This is the live-model execution path.  It should only be
        called when a ``WorkerLLMExecutor`` is available.
        """
        if self._llm_executor is None:
            raise AgentRuntimeBoundaryError(
                "execute_invocation requires a WorkerLLMExecutor"
            )
        llm_result = self._llm_executor.execute(invocation)
        return AgentRuntimeExecution(invocation=invocation, llm_result=llm_result)

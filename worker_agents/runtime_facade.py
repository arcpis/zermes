"""Facade for preparing shared managed-agent runtime invocations."""

from __future__ import annotations

from dataclasses import dataclass

from .runtime_boundary import (
    AgentRuntimeBoundaryError,
    AgentRuntimeRole,
    AgentRuntimeSessionConfig,
    AgentRuntimeSessionScope,
)


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


class SharedAgentRuntimeFacade:
    """Single preparation point for all roles using the shared agent runtime."""

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

    def run(self, config: AgentRuntimeSessionConfig) -> AgentRuntimeInvocation:
        """Prepare a runtime invocation until the runtime contract owns execution."""
        return self.prepare_invocation(config)

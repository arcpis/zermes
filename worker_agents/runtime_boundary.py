"""Shared runtime boundary for main, worker, and temporary agents."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .profile import validate_worker_id
from .task_state import validate_task_id


class AgentRuntimeBoundaryError(ValueError):
    """Raised when a shared agent runtime boundary is invalid."""


class AgentRuntimeRole(str, Enum):
    """Agent roles that share the same runtime implementation."""

    MAIN_AGENT = "main_agent"
    MANAGED_WORKER = "managed_worker"
    TEMPORARY_CHILD = "temporary_child"


class AgentRuntimeLifecycle(str, Enum):
    """How long runtime identity and state may survive after execution."""

    GOVERNED_MAIN = "governed_main"
    DURABLE_WORKER = "durable_worker"
    TASK_SCOPED = "task_scoped"


def _require_non_empty_string(value: str | None, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise AgentRuntimeBoundaryError(f"{field_name} must be a non-empty string")
    return value


def _normalize_role(role: AgentRuntimeRole | str) -> AgentRuntimeRole:
    try:
        return AgentRuntimeRole(role)
    except ValueError as exc:
        raise AgentRuntimeBoundaryError(f"Unsupported agent runtime role: {role!r}") from exc


@dataclass(frozen=True)
class AgentRuntimePersona:
    """Identity and policy overlay applied before entering the shared runtime."""

    role: AgentRuntimeRole | str
    display_name: str
    responsibility_summary: str
    lifecycle: AgentRuntimeLifecycle | str
    worker_id: str | None = None
    parent_worker_id: str | None = None
    parent_task_id: str | None = None
    tool_policy_ref: str | None = None
    memory_policy_ref: str | None = None
    enables_governance_actions: bool = False
    can_read_private_memory: bool = False
    can_write_private_memory: bool = False
    can_register_durable_worker: bool = False

    def __post_init__(self) -> None:
        role = _normalize_role(self.role)
        try:
            lifecycle = AgentRuntimeLifecycle(self.lifecycle)
        except ValueError as exc:
            raise AgentRuntimeBoundaryError(
                f"Unsupported agent runtime lifecycle: {self.lifecycle!r}"
            ) from exc

        object.__setattr__(self, "role", role)
        object.__setattr__(self, "lifecycle", lifecycle)
        _require_non_empty_string(self.display_name, "display_name")
        _require_non_empty_string(
            self.responsibility_summary, "responsibility_summary"
        )
        self._validate_role_fields(role, lifecycle)

    def _validate_role_fields(
        self, role: AgentRuntimeRole, lifecycle: AgentRuntimeLifecycle
    ) -> None:
        if role == AgentRuntimeRole.MAIN_AGENT:
            self._validate_main_agent(lifecycle)
        elif role == AgentRuntimeRole.MANAGED_WORKER:
            self._validate_managed_worker(lifecycle)
        elif role == AgentRuntimeRole.TEMPORARY_CHILD:
            self._validate_temporary_child(lifecycle)

    def _validate_main_agent(self, lifecycle: AgentRuntimeLifecycle) -> None:
        if lifecycle != AgentRuntimeLifecycle.GOVERNED_MAIN:
            raise AgentRuntimeBoundaryError(
                "main_agent lifecycle must be governed_main"
            )
        if self.worker_id or self.parent_worker_id or self.parent_task_id:
            raise AgentRuntimeBoundaryError(
                "main_agent must not bind worker or parent task identity"
            )
        if self.can_read_private_memory or self.can_write_private_memory:
            raise AgentRuntimeBoundaryError(
                "main_agent must not claim worker private memory access"
            )

    def _validate_managed_worker(self, lifecycle: AgentRuntimeLifecycle) -> None:
        if lifecycle != AgentRuntimeLifecycle.DURABLE_WORKER:
            raise AgentRuntimeBoundaryError(
                "managed_worker lifecycle must be durable_worker"
            )
        if self.worker_id is None:
            raise AgentRuntimeBoundaryError("managed_worker requires worker_id")
        validate_worker_id(self.worker_id)
        if self.parent_worker_id or self.parent_task_id:
            raise AgentRuntimeBoundaryError(
                "managed_worker must not bind temporary parent identity"
            )
        if self.enables_governance_actions:
            raise AgentRuntimeBoundaryError(
                "managed_worker must not enable main-agent governance actions"
            )

    def _validate_temporary_child(self, lifecycle: AgentRuntimeLifecycle) -> None:
        if lifecycle != AgentRuntimeLifecycle.TASK_SCOPED:
            raise AgentRuntimeBoundaryError(
                "temporary_child lifecycle must be task_scoped"
            )
        if self.worker_id:
            raise AgentRuntimeBoundaryError(
                "temporary_child must not bind durable worker_id"
            )
        if self.parent_worker_id is None:
            raise AgentRuntimeBoundaryError(
                "temporary_child requires parent_worker_id"
            )
        if self.parent_task_id is None:
            raise AgentRuntimeBoundaryError("temporary_child requires parent_task_id")
        validate_worker_id(self.parent_worker_id)
        validate_task_id(self.parent_task_id)
        if (
            self.enables_governance_actions
            or self.can_read_private_memory
            or self.can_write_private_memory
            or self.can_register_durable_worker
        ):
            raise AgentRuntimeBoundaryError(
                "temporary_child cannot use governance, private memory, or registry capabilities"
            )

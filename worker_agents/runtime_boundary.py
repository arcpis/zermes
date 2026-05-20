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


class AgentRuntimeSessionScope(str, Enum):
    """The user-visible work shape that owns one runtime invocation."""

    INTERACTIVE_MAIN = "interactive_main"
    MANAGED_WORKER_TASK = "managed_worker_task"
    TEMPORARY_CHILD_TASK = "temporary_child_task"


def _require_non_empty_string(value: str | None, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise AgentRuntimeBoundaryError(f"{field_name} must be a non-empty string")
    return value


def _optional_non_empty_string(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_non_empty_string(value, field_name)


def _normalize_string_tuple(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise AgentRuntimeBoundaryError(f"{field_name} must be a tuple of strings")
    if any(not isinstance(value, str) or not value for value in values):
        raise AgentRuntimeBoundaryError(
            f"{field_name} must be a tuple of non-empty strings"
        )
    return values


def _reject_wildcard(values: tuple[str, ...], field_name: str) -> None:
    if any(value in {"*", "all"} for value in values):
        raise AgentRuntimeBoundaryError(f"{field_name} must not grant all access")


def _optional_positive_int(value: int | None, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AgentRuntimeBoundaryError(f"{field_name} must be a positive integer")
    return value


def _optional_non_negative_float(value: float | None, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise AgentRuntimeBoundaryError(f"{field_name} must be a non-negative number")
    return float(value)


def _normalize_role(role: AgentRuntimeRole | str) -> AgentRuntimeRole:
    try:
        return AgentRuntimeRole(role)
    except ValueError as exc:
        raise AgentRuntimeBoundaryError(f"Unsupported agent runtime role: {role!r}") from exc


def _normalize_session_scope(
    scope: AgentRuntimeSessionScope | str,
) -> AgentRuntimeSessionScope:
    try:
        return AgentRuntimeSessionScope(scope)
    except ValueError as exc:
        raise AgentRuntimeBoundaryError(
            f"Unsupported agent runtime session scope: {scope!r}"
        ) from exc


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


@dataclass(frozen=True)
class RuntimeProfileSummary:
    """Portable profile references allowed to enter one runtime session."""

    worker_id: str | None = None
    identity_ref: str | None = None
    allowed_skill_refs: tuple[str, ...] = ()
    memory_summary_refs: tuple[str, ...] = ()
    department_summary_refs: tuple[str, ...] = ()
    includes_private_memory_text: bool = False

    def __post_init__(self) -> None:
        if self.worker_id is not None:
            validate_worker_id(self.worker_id)
        _optional_non_empty_string(self.identity_ref, "identity_ref")
        _normalize_string_tuple(self.allowed_skill_refs, "allowed_skill_refs")
        _normalize_string_tuple(self.memory_summary_refs, "memory_summary_refs")
        _normalize_string_tuple(self.department_summary_refs, "department_summary_refs")
        if self.includes_private_memory_text:
            raise AgentRuntimeBoundaryError(
                "runtime profile summary must not include private memory text"
            )


@dataclass(frozen=True)
class RuntimePermissionSnapshot:
    """Concrete tool, workspace, and communication permissions for one session."""

    allowed_tool_names: tuple[str, ...] = ()
    allowed_toolset_names: tuple[str, ...] = ()
    workspace_read_roots: tuple[str, ...] = ()
    workspace_write_roots: tuple[str, ...] = ()
    approval_required_tool_names: tuple[str, ...] = ()
    outbound_communication_policy: str = "message_router_only"

    def __post_init__(self) -> None:
        for field_name in (
            "allowed_tool_names",
            "allowed_toolset_names",
            "workspace_read_roots",
            "workspace_write_roots",
            "approval_required_tool_names",
        ):
            values = getattr(self, field_name)
            _normalize_string_tuple(values, field_name)
            _reject_wildcard(values, field_name)
        _require_non_empty_string(
            self.outbound_communication_policy, "outbound_communication_policy"
        )


@dataclass(frozen=True)
class RuntimeBudgetSnapshot:
    """Immutable model, token, cost, and wall-time limits for one session."""

    model_name: str | None = None
    model_policy_ref: str | None = None
    context_window_tokens: int | None = None
    max_output_tokens: int | None = None
    max_task_tokens: int | None = None
    max_task_cost_usd: float | None = None
    wall_time_seconds: int | None = None
    max_allowed_task_tokens: int | None = None
    max_allowed_task_cost_usd: float | None = None

    def __post_init__(self) -> None:
        _optional_non_empty_string(self.model_name, "model_name")
        _optional_non_empty_string(self.model_policy_ref, "model_policy_ref")
        if self.model_name is None and self.model_policy_ref is None:
            raise AgentRuntimeBoundaryError(
                "runtime budget requires model_name or model_policy_ref"
            )
        for field_name in (
            "context_window_tokens",
            "max_output_tokens",
            "max_task_tokens",
            "wall_time_seconds",
            "max_allowed_task_tokens",
        ):
            _optional_positive_int(getattr(self, field_name), field_name)
        _optional_non_negative_float(self.max_task_cost_usd, "max_task_cost_usd")
        _optional_non_negative_float(
            self.max_allowed_task_cost_usd, "max_allowed_task_cost_usd"
        )
        if (
            self.max_task_tokens is not None
            and self.max_allowed_task_tokens is not None
            and self.max_task_tokens > self.max_allowed_task_tokens
        ):
            raise AgentRuntimeBoundaryError(
                "max_task_tokens must not exceed max_allowed_task_tokens"
            )
        if (
            self.max_task_cost_usd is not None
            and self.max_allowed_task_cost_usd is not None
            and self.max_task_cost_usd > self.max_allowed_task_cost_usd
        ):
            raise AgentRuntimeBoundaryError(
                "max_task_cost_usd must not exceed max_allowed_task_cost_usd"
            )


@dataclass(frozen=True)
class RuntimeContextBundle:
    """Minimal task context that excludes full transcripts and raw memories."""

    user_instruction: str
    task_summary: str
    thread_summary_refs: tuple[str, ...] = ()
    relevant_message_refs: tuple[str, ...] = ()
    relevant_excerpts: tuple[str, ...] = ()
    includes_full_transcript: bool = False
    includes_private_memory_text: bool = False

    def __post_init__(self) -> None:
        _require_non_empty_string(self.user_instruction, "user_instruction")
        _require_non_empty_string(self.task_summary, "task_summary")
        _normalize_string_tuple(self.thread_summary_refs, "thread_summary_refs")
        _normalize_string_tuple(self.relevant_message_refs, "relevant_message_refs")
        _normalize_string_tuple(self.relevant_excerpts, "relevant_excerpts")
        if self.includes_full_transcript:
            raise AgentRuntimeBoundaryError(
                "runtime context must not include full transcripts"
            )
        if self.includes_private_memory_text:
            raise AgentRuntimeBoundaryError(
                "runtime context must not include private memory text"
            )


@dataclass(frozen=True)
class AgentRuntimeSessionConfig:
    """Validated input boundary for one shared agent runtime session."""

    scope: AgentRuntimeSessionScope | str
    persona: AgentRuntimePersona
    profile_summary: RuntimeProfileSummary
    permissions: RuntimePermissionSnapshot
    budget: RuntimeBudgetSnapshot
    context: RuntimeContextBundle
    cleanup_policy: str | None = None

    def __post_init__(self) -> None:
        scope = _normalize_session_scope(self.scope)
        object.__setattr__(self, "scope", scope)
        if not isinstance(self.persona, AgentRuntimePersona):
            raise AgentRuntimeBoundaryError("persona must be an AgentRuntimePersona")
        if not isinstance(self.profile_summary, RuntimeProfileSummary):
            raise AgentRuntimeBoundaryError(
                "profile_summary must be a RuntimeProfileSummary"
            )
        if not isinstance(self.permissions, RuntimePermissionSnapshot):
            raise AgentRuntimeBoundaryError(
                "permissions must be a RuntimePermissionSnapshot"
            )
        if not isinstance(self.budget, RuntimeBudgetSnapshot):
            raise AgentRuntimeBoundaryError("budget must be a RuntimeBudgetSnapshot")
        if not isinstance(self.context, RuntimeContextBundle):
            raise AgentRuntimeBoundaryError("context must be a RuntimeContextBundle")
        self._validate_scope_matches_persona(scope)

    def _validate_scope_matches_persona(self, scope: AgentRuntimeSessionScope) -> None:
        if scope == AgentRuntimeSessionScope.INTERACTIVE_MAIN:
            expected_role = AgentRuntimeRole.MAIN_AGENT
        elif scope == AgentRuntimeSessionScope.MANAGED_WORKER_TASK:
            expected_role = AgentRuntimeRole.MANAGED_WORKER
        else:
            expected_role = AgentRuntimeRole.TEMPORARY_CHILD
        if self.persona.role != expected_role:
            raise AgentRuntimeBoundaryError(
                f"{scope.value} requires {expected_role.value} persona"
            )
        if scope == AgentRuntimeSessionScope.MANAGED_WORKER_TASK:
            if self.profile_summary.worker_id != self.persona.worker_id:
                raise AgentRuntimeBoundaryError(
                    "managed worker session profile must match persona worker_id"
                )
        if scope == AgentRuntimeSessionScope.TEMPORARY_CHILD_TASK:
            if self.profile_summary.worker_id is not None:
                raise AgentRuntimeBoundaryError(
                    "temporary child session must not bind a durable profile worker_id"
                )
            _require_non_empty_string(self.cleanup_policy, "cleanup_policy")

"""Durable profile contract for managed worker agents."""

from __future__ import annotations

from dataclasses import dataclass, field


WORKER_PROFILE_FILE_NAME = "worker.json"
WORKER_PROFILE_SCHEMA_VERSION = 1


class WorkerProfileError(ValueError):
    """Raised when a worker profile violates the durable contract."""


def validate_worker_id(worker_id: str) -> str:
    """Return a stable worker id after rejecting path-like values."""
    if not worker_id or worker_id in {".", ".."}:
        raise WorkerProfileError("worker_id must be a non-empty path segment")
    if "/" in worker_id or "\\" in worker_id:
        raise WorkerProfileError("worker_id must not contain path separators")
    return worker_id


@dataclass(frozen=True)
class WorkerRuntimeSettings:
    """Runtime adapter identity without secrets or live process state."""

    runtime_type: str = "internal"
    adapter_name: str = "zermes"
    config_reference: str | None = None


@dataclass(frozen=True)
class WorkerMemorySettings:
    """Private durable memory policy for one worker."""

    enabled: bool = False
    storage_reference: str = "memory"
    write_policy: str = "proposal_required"


@dataclass(frozen=True)
class WorkerSkillSettings:
    """Skill bindings allowed for one worker profile."""

    allowed_skill_ids: tuple[str, ...] = ()
    injection_mode: str = "none"
    learning_records_enabled: bool = False


@dataclass(frozen=True)
class WorkerToolPolicy:
    """Tool authorization limits for one worker."""

    allowed_tools: tuple[str, ...] = ()
    approval_required_tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkerWorkspacePolicy:
    """Filesystem access limits for one worker."""

    read_roots: tuple[str, ...] = ()
    write_roots: tuple[str, ...] = ()
    temporary_directory_policy: str = "task_scoped"


@dataclass(frozen=True)
class WorkerCommunicationPolicy:
    """Messaging permissions for user-present worker conversations."""

    allow_direct_user_chat: bool = False
    allow_group_chat: bool = False
    report_to: str = "zermes_main_agent"
    approval_message_policy: str = "required_for_high_risk_actions"


@dataclass(frozen=True)
class WorkerModelSettings:
    """Model choices and context limits for one worker."""

    default_model: str | None = None
    allowed_models: tuple[str, ...] = ()
    context_window_tokens: int | None = None
    require_approval_for_costly_models: bool = True


@dataclass(frozen=True)
class WorkerBudgetPolicy:
    """Token and cost ceilings for one worker task."""

    max_task_tokens: int = 0
    max_turn_tokens: int = 0
    max_task_cost_usd: float | None = None


@dataclass(frozen=True)
class WorkerExecutionLimits:
    """Concurrency and runtime limits for worker execution."""

    max_concurrent_tasks: int = 1
    timeout_seconds: int | None = None
    max_retries: int = 0
    queue_policy: str = "reject_when_busy"


@dataclass(frozen=True)
class WorkerCostPolicy:
    """Cost ownership and over-budget behavior."""

    cost_owner: str = "user"
    over_budget_action: str = "require_approval"
    require_approval_for_paid_external_runtime: bool = True


@dataclass(frozen=True)
class WorkerDelegationPolicy:
    """Limits for temporary child agents created by this worker."""

    allow_temporary_child_agents: bool = False
    allowed_child_models: tuple[str, ...] = ()
    allowed_child_tools: tuple[str, ...] = ()
    max_child_task_tokens: int = 0


@dataclass(frozen=True)
class WorkerProfileMetadata:
    """Portable audit metadata for a worker profile."""

    created_at: str | None = None
    updated_at: str | None = None
    source: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class WorkerAgentProfile:
    """Durable identity and policy contract for one managed worker."""

    worker_id: str
    display_name: str
    description: str
    role: str
    responsibilities: tuple[str, ...] = ()
    schema_version: int = WORKER_PROFILE_SCHEMA_VERSION
    runtime: WorkerRuntimeSettings = field(default_factory=WorkerRuntimeSettings)
    memory: WorkerMemorySettings = field(default_factory=WorkerMemorySettings)
    skills: WorkerSkillSettings = field(default_factory=WorkerSkillSettings)
    tools: WorkerToolPolicy = field(default_factory=WorkerToolPolicy)
    workspace: WorkerWorkspacePolicy = field(default_factory=WorkerWorkspacePolicy)
    communication: WorkerCommunicationPolicy = field(
        default_factory=WorkerCommunicationPolicy
    )
    model: WorkerModelSettings = field(default_factory=WorkerModelSettings)
    budgets: WorkerBudgetPolicy = field(default_factory=WorkerBudgetPolicy)
    limits: WorkerExecutionLimits = field(default_factory=WorkerExecutionLimits)
    cost_policy: WorkerCostPolicy = field(default_factory=WorkerCostPolicy)
    delegation: WorkerDelegationPolicy = field(default_factory=WorkerDelegationPolicy)
    metadata: WorkerProfileMetadata = field(default_factory=WorkerProfileMetadata)

    def __post_init__(self) -> None:
        validate_worker_id(self.worker_id)
        if self.schema_version != WORKER_PROFILE_SCHEMA_VERSION:
            raise WorkerProfileError(
                f"Unsupported worker profile schema_version: {self.schema_version!r}"
            )

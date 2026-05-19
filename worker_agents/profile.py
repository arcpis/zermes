"""Durable profile contract for managed worker agents."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping


WORKER_PROFILE_FILE_NAME = "worker.json"
WORKER_PROFILE_SCHEMA_VERSION = 1


class WorkerProfileError(ValueError):
    """Raised when a worker profile violates the durable contract."""


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise WorkerProfileError(f"{field_name} must be an object")
    return value


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise WorkerProfileError(f"{field_name} must be a non-empty string")
    return value


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, field_name)


def _require_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise WorkerProfileError(f"{field_name} must be a boolean")
    return value


def _optional_non_negative_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise WorkerProfileError(f"{field_name} must be a non-negative integer")
    return value


def _non_negative_int(value: Any, field_name: str) -> int:
    result = _optional_non_negative_int(value, field_name)
    if result is None:
        raise WorkerProfileError(f"{field_name} must be a non-negative integer")
    return result


def _optional_non_negative_number(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise WorkerProfileError(f"{field_name} must be a non-negative number")
    return float(value)


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise WorkerProfileError(f"{field_name} must be a list of strings")
    result = tuple(value)
    if any(not isinstance(item, str) or not item for item in result):
        raise WorkerProfileError(f"{field_name} must be a list of non-empty strings")
    return result


def _reject_unknown_fields(
    data: Mapping[str, Any], allowed_fields: set[str], field_name: str
) -> None:
    unknown_fields = sorted(set(data) - allowed_fields)
    if unknown_fields:
        joined = ", ".join(unknown_fields)
        raise WorkerProfileError(f"{field_name} has unknown fields: {joined}")


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


_PROFILE_FIELDS = {
    "worker_id",
    "schema_version",
    "display_name",
    "description",
    "role",
    "responsibilities",
    "runtime",
    "memory",
    "skills",
    "tools",
    "workspace",
    "communication",
    "model",
    "budgets",
    "limits",
    "cost_policy",
    "delegation",
    "metadata",
}


def worker_runtime_settings_from_dict(
    data: Mapping[str, Any] | None,
) -> WorkerRuntimeSettings:
    if data is None:
        return WorkerRuntimeSettings()
    data = _require_mapping(data, "runtime")
    _reject_unknown_fields(
        data, {"runtime_type", "adapter_name", "config_reference"}, "runtime"
    )
    return WorkerRuntimeSettings(
        runtime_type=_require_string(data.get("runtime_type", "internal"), "runtime.runtime_type"),
        adapter_name=_require_string(data.get("adapter_name", "zermes"), "runtime.adapter_name"),
        config_reference=_optional_string(
            data.get("config_reference"), "runtime.config_reference"
        ),
    )


def worker_memory_settings_from_dict(data: Mapping[str, Any] | None) -> WorkerMemorySettings:
    if data is None:
        return WorkerMemorySettings()
    data = _require_mapping(data, "memory")
    _reject_unknown_fields(
        data, {"enabled", "storage_reference", "write_policy"}, "memory"
    )
    return WorkerMemorySettings(
        enabled=_require_bool(data.get("enabled", False), "memory.enabled"),
        storage_reference=_require_string(
            data.get("storage_reference", "memory"), "memory.storage_reference"
        ),
        write_policy=_require_string(
            data.get("write_policy", "proposal_required"), "memory.write_policy"
        ),
    )


def worker_skill_settings_from_dict(data: Mapping[str, Any] | None) -> WorkerSkillSettings:
    if data is None:
        return WorkerSkillSettings()
    data = _require_mapping(data, "skills")
    _reject_unknown_fields(
        data, {"allowed_skill_ids", "injection_mode", "learning_records_enabled"}, "skills"
    )
    return WorkerSkillSettings(
        allowed_skill_ids=_string_tuple(
            data.get("allowed_skill_ids", ()), "skills.allowed_skill_ids"
        ),
        injection_mode=_require_string(
            data.get("injection_mode", "none"), "skills.injection_mode"
        ),
        learning_records_enabled=_require_bool(
            data.get("learning_records_enabled", False),
            "skills.learning_records_enabled",
        ),
    )


def worker_tool_policy_from_dict(data: Mapping[str, Any] | None) -> WorkerToolPolicy:
    if data is None:
        return WorkerToolPolicy()
    data = _require_mapping(data, "tools")
    _reject_unknown_fields(data, {"allowed_tools", "approval_required_tools"}, "tools")
    return WorkerToolPolicy(
        allowed_tools=_string_tuple(data.get("allowed_tools", ()), "tools.allowed_tools"),
        approval_required_tools=_string_tuple(
            data.get("approval_required_tools", ()), "tools.approval_required_tools"
        ),
    )


def worker_workspace_policy_from_dict(
    data: Mapping[str, Any] | None,
) -> WorkerWorkspacePolicy:
    if data is None:
        return WorkerWorkspacePolicy()
    data = _require_mapping(data, "workspace")
    _reject_unknown_fields(
        data, {"read_roots", "write_roots", "temporary_directory_policy"}, "workspace"
    )
    return WorkerWorkspacePolicy(
        read_roots=_string_tuple(data.get("read_roots", ()), "workspace.read_roots"),
        write_roots=_string_tuple(data.get("write_roots", ()), "workspace.write_roots"),
        temporary_directory_policy=_require_string(
            data.get("temporary_directory_policy", "task_scoped"),
            "workspace.temporary_directory_policy",
        ),
    )


def worker_communication_policy_from_dict(
    data: Mapping[str, Any] | None,
) -> WorkerCommunicationPolicy:
    if data is None:
        return WorkerCommunicationPolicy()
    data = _require_mapping(data, "communication")
    _reject_unknown_fields(
        data,
        {
            "allow_direct_user_chat",
            "allow_group_chat",
            "report_to",
            "approval_message_policy",
        },
        "communication",
    )
    return WorkerCommunicationPolicy(
        allow_direct_user_chat=_require_bool(
            data.get("allow_direct_user_chat", False),
            "communication.allow_direct_user_chat",
        ),
        allow_group_chat=_require_bool(
            data.get("allow_group_chat", False), "communication.allow_group_chat"
        ),
        report_to=_require_string(
            data.get("report_to", "zermes_main_agent"), "communication.report_to"
        ),
        approval_message_policy=_require_string(
            data.get("approval_message_policy", "required_for_high_risk_actions"),
            "communication.approval_message_policy",
        ),
    )


def worker_model_settings_from_dict(data: Mapping[str, Any] | None) -> WorkerModelSettings:
    if data is None:
        return WorkerModelSettings()
    data = _require_mapping(data, "model")
    _reject_unknown_fields(
        data,
        {
            "default_model",
            "allowed_models",
            "context_window_tokens",
            "require_approval_for_costly_models",
        },
        "model",
    )
    return WorkerModelSettings(
        default_model=_optional_string(data.get("default_model"), "model.default_model"),
        allowed_models=_string_tuple(data.get("allowed_models", ()), "model.allowed_models"),
        context_window_tokens=_optional_non_negative_int(
            data.get("context_window_tokens"), "model.context_window_tokens"
        ),
        require_approval_for_costly_models=_require_bool(
            data.get("require_approval_for_costly_models", True),
            "model.require_approval_for_costly_models",
        ),
    )


def worker_budget_policy_from_dict(data: Mapping[str, Any] | None) -> WorkerBudgetPolicy:
    if data is None:
        return WorkerBudgetPolicy()
    data = _require_mapping(data, "budgets")
    _reject_unknown_fields(
        data, {"max_task_tokens", "max_turn_tokens", "max_task_cost_usd"}, "budgets"
    )
    return WorkerBudgetPolicy(
        max_task_tokens=_non_negative_int(
            data.get("max_task_tokens", 0), "budgets.max_task_tokens"
        ),
        max_turn_tokens=_non_negative_int(
            data.get("max_turn_tokens", 0), "budgets.max_turn_tokens"
        ),
        max_task_cost_usd=_optional_non_negative_number(
            data.get("max_task_cost_usd"), "budgets.max_task_cost_usd"
        ),
    )


def worker_execution_limits_from_dict(
    data: Mapping[str, Any] | None,
) -> WorkerExecutionLimits:
    if data is None:
        return WorkerExecutionLimits()
    data = _require_mapping(data, "limits")
    _reject_unknown_fields(
        data, {"max_concurrent_tasks", "timeout_seconds", "max_retries", "queue_policy"}, "limits"
    )
    max_concurrent_tasks = _non_negative_int(
        data.get("max_concurrent_tasks", 1), "limits.max_concurrent_tasks"
    )
    if max_concurrent_tasks < 1:
        raise WorkerProfileError("limits.max_concurrent_tasks must be at least 1")
    return WorkerExecutionLimits(
        max_concurrent_tasks=max_concurrent_tasks,
        timeout_seconds=_optional_non_negative_int(
            data.get("timeout_seconds"), "limits.timeout_seconds"
        ),
        max_retries=_non_negative_int(data.get("max_retries", 0), "limits.max_retries"),
        queue_policy=_require_string(
            data.get("queue_policy", "reject_when_busy"), "limits.queue_policy"
        ),
    )


def worker_cost_policy_from_dict(data: Mapping[str, Any] | None) -> WorkerCostPolicy:
    if data is None:
        return WorkerCostPolicy()
    data = _require_mapping(data, "cost_policy")
    _reject_unknown_fields(
        data,
        {
            "cost_owner",
            "over_budget_action",
            "require_approval_for_paid_external_runtime",
        },
        "cost_policy",
    )
    return WorkerCostPolicy(
        cost_owner=_require_string(
            data.get("cost_owner", "user"), "cost_policy.cost_owner"
        ),
        over_budget_action=_require_string(
            data.get("over_budget_action", "require_approval"),
            "cost_policy.over_budget_action",
        ),
        require_approval_for_paid_external_runtime=_require_bool(
            data.get("require_approval_for_paid_external_runtime", True),
            "cost_policy.require_approval_for_paid_external_runtime",
        ),
    )


def worker_delegation_policy_from_dict(
    data: Mapping[str, Any] | None,
) -> WorkerDelegationPolicy:
    if data is None:
        return WorkerDelegationPolicy()
    data = _require_mapping(data, "delegation")
    _reject_unknown_fields(
        data,
        {
            "allow_temporary_child_agents",
            "allowed_child_models",
            "allowed_child_tools",
            "max_child_task_tokens",
        },
        "delegation",
    )
    return WorkerDelegationPolicy(
        allow_temporary_child_agents=_require_bool(
            data.get("allow_temporary_child_agents", False),
            "delegation.allow_temporary_child_agents",
        ),
        allowed_child_models=_string_tuple(
            data.get("allowed_child_models", ()), "delegation.allowed_child_models"
        ),
        allowed_child_tools=_string_tuple(
            data.get("allowed_child_tools", ()), "delegation.allowed_child_tools"
        ),
        max_child_task_tokens=_non_negative_int(
            data.get("max_child_task_tokens", 0), "delegation.max_child_task_tokens"
        ),
    )


def worker_profile_metadata_from_dict(
    data: Mapping[str, Any] | None,
) -> WorkerProfileMetadata:
    if data is None:
        return WorkerProfileMetadata()
    data = _require_mapping(data, "metadata")
    _reject_unknown_fields(data, {"created_at", "updated_at", "source", "notes"}, "metadata")
    return WorkerProfileMetadata(
        created_at=_optional_string(data.get("created_at"), "metadata.created_at"),
        updated_at=_optional_string(data.get("updated_at"), "metadata.updated_at"),
        source=_optional_string(data.get("source"), "metadata.source"),
        notes=_optional_string(data.get("notes"), "metadata.notes"),
    )


def worker_profile_from_dict(data: Mapping[str, Any]) -> WorkerAgentProfile:
    """Build a worker profile from a strict dictionary contract."""
    data = _require_mapping(data, "profile")
    _reject_unknown_fields(data, _PROFILE_FIELDS, "profile")

    missing_fields = [
        field_name
        for field_name in (
            "worker_id",
            "schema_version",
            "display_name",
            "description",
            "role",
        )
        if field_name not in data
    ]
    if missing_fields:
        joined = ", ".join(missing_fields)
        raise WorkerProfileError(f"profile is missing required fields: {joined}")

    schema_version = _non_negative_int(data["schema_version"], "schema_version")
    if schema_version != WORKER_PROFILE_SCHEMA_VERSION:
        raise WorkerProfileError(
            f"Unsupported worker profile schema_version: {schema_version!r}"
        )

    return WorkerAgentProfile(
        worker_id=validate_worker_id(_require_string(data["worker_id"], "worker_id")),
        schema_version=schema_version,
        display_name=_require_string(data["display_name"], "display_name"),
        description=_require_string(data["description"], "description"),
        role=_require_string(data["role"], "role"),
        responsibilities=_string_tuple(
            data.get("responsibilities", ()), "responsibilities"
        ),
        runtime=worker_runtime_settings_from_dict(data.get("runtime")),
        memory=worker_memory_settings_from_dict(data.get("memory")),
        skills=worker_skill_settings_from_dict(data.get("skills")),
        tools=worker_tool_policy_from_dict(data.get("tools")),
        workspace=worker_workspace_policy_from_dict(data.get("workspace")),
        communication=worker_communication_policy_from_dict(data.get("communication")),
        model=worker_model_settings_from_dict(data.get("model")),
        budgets=worker_budget_policy_from_dict(data.get("budgets")),
        limits=worker_execution_limits_from_dict(data.get("limits")),
        cost_policy=worker_cost_policy_from_dict(data.get("cost_policy")),
        delegation=worker_delegation_policy_from_dict(data.get("delegation")),
        metadata=worker_profile_metadata_from_dict(data.get("metadata")),
    )


def worker_profile_to_dict(profile: WorkerAgentProfile) -> dict[str, Any]:
    """Convert a worker profile to a deterministic JSON-ready mapping."""
    return {
        "worker_id": profile.worker_id,
        "schema_version": profile.schema_version,
        "display_name": profile.display_name,
        "description": profile.description,
        "role": profile.role,
        "responsibilities": list(profile.responsibilities),
        "runtime": {
            "runtime_type": profile.runtime.runtime_type,
            "adapter_name": profile.runtime.adapter_name,
            "config_reference": profile.runtime.config_reference,
        },
        "memory": {
            "enabled": profile.memory.enabled,
            "storage_reference": profile.memory.storage_reference,
            "write_policy": profile.memory.write_policy,
        },
        "skills": {
            "allowed_skill_ids": list(profile.skills.allowed_skill_ids),
            "injection_mode": profile.skills.injection_mode,
            "learning_records_enabled": profile.skills.learning_records_enabled,
        },
        "tools": {
            "allowed_tools": list(profile.tools.allowed_tools),
            "approval_required_tools": list(profile.tools.approval_required_tools),
        },
        "workspace": {
            "read_roots": list(profile.workspace.read_roots),
            "write_roots": list(profile.workspace.write_roots),
            "temporary_directory_policy": profile.workspace.temporary_directory_policy,
        },
        "communication": {
            "allow_direct_user_chat": profile.communication.allow_direct_user_chat,
            "allow_group_chat": profile.communication.allow_group_chat,
            "report_to": profile.communication.report_to,
            "approval_message_policy": profile.communication.approval_message_policy,
        },
        "model": {
            "default_model": profile.model.default_model,
            "allowed_models": list(profile.model.allowed_models),
            "context_window_tokens": profile.model.context_window_tokens,
            "require_approval_for_costly_models": (
                profile.model.require_approval_for_costly_models
            ),
        },
        "budgets": {
            "max_task_tokens": profile.budgets.max_task_tokens,
            "max_turn_tokens": profile.budgets.max_turn_tokens,
            "max_task_cost_usd": profile.budgets.max_task_cost_usd,
        },
        "limits": {
            "max_concurrent_tasks": profile.limits.max_concurrent_tasks,
            "timeout_seconds": profile.limits.timeout_seconds,
            "max_retries": profile.limits.max_retries,
            "queue_policy": profile.limits.queue_policy,
        },
        "cost_policy": {
            "cost_owner": profile.cost_policy.cost_owner,
            "over_budget_action": profile.cost_policy.over_budget_action,
            "require_approval_for_paid_external_runtime": (
                profile.cost_policy.require_approval_for_paid_external_runtime
            ),
        },
        "delegation": {
            "allow_temporary_child_agents": (
                profile.delegation.allow_temporary_child_agents
            ),
            "allowed_child_models": list(profile.delegation.allowed_child_models),
            "allowed_child_tools": list(profile.delegation.allowed_child_tools),
            "max_child_task_tokens": profile.delegation.max_child_task_tokens,
        },
        "metadata": {
            "created_at": profile.metadata.created_at,
            "updated_at": profile.metadata.updated_at,
            "source": profile.metadata.source,
            "notes": profile.metadata.notes,
        },
    }


def load_worker_profile_json(text: str) -> WorkerAgentProfile:
    """Load a worker profile from JSON text."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise WorkerProfileError(f"Invalid worker profile JSON: {exc.msg}") from exc
    return worker_profile_from_dict(data)


def dump_worker_profile_json(profile: WorkerAgentProfile) -> str:
    """Dump a worker profile as stable, newline-terminated JSON."""
    return json.dumps(worker_profile_to_dict(profile), indent=2) + "\n"

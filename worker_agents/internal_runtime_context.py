"""Minimal context assembly for internal managed worker runtime tasks."""

from __future__ import annotations

from dataclasses import dataclass

from .profile import WorkerAgentProfile
from .department_chats import DepartmentChatBinding, DepartmentChatSummary, DepartmentProjectChat
from .organization import OrgTree
from .registry import WorkerLifecycleStatus, WorkerRegistryRecord
from .runtime_boundary import (
    AgentRuntimeLifecycle,
    AgentRuntimePersona,
    AgentRuntimeRole,
    AgentRuntimeSessionScope,
    RuntimeBudgetSnapshot,
    RuntimeContextBundle,
    RuntimePermissionSnapshot,
    RuntimeProfileSummary,
)
from .runtime_contract import RuntimeExecutionBudget, RuntimeRequestContext
from .task_service import WorkerTaskService
from .task_state import WorkerTaskState, validate_task_id
from .worker_prompt_summary import (
    build_worker_prompt_summary,
    worker_prompt_summary_to_dict,
)


class InternalWorkerRuntimeContextError(ValueError):
    """Raised when a managed worker task cannot produce safe runtime context."""


@dataclass(frozen=True)
class InternalWorkerRuntimeContextRequest:
    """References needed to assemble one internal worker runtime context."""

    worker_id: str
    task_id: str
    requested_by: str = "zermes_main_agent"
    thread_summary_refs: tuple[str, ...] = ()
    organization_summary_refs: tuple[str, ...] = ()
    artifact_manifest_refs: tuple[str, ...] = ()
    relevant_excerpts: tuple[str, ...] = ()
    current_thread_id: str | None = None
    current_thread_summary: str | None = None
    organization_tree: OrgTree | None = None
    department_chat_bindings: tuple[DepartmentChatBinding, ...] = ()
    project_chats: tuple[DepartmentProjectChat, ...] = ()
    department_context_summaries: tuple[DepartmentChatSummary, ...] = ()
    private_thread_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class InternalWorkerRuntimeContext:
    """Low-sensitive inputs shared by the runner and runtime request builder."""

    worker_record: WorkerRegistryRecord
    worker_profile: WorkerAgentProfile
    task_state: WorkerTaskState
    requested_by: str
    request_context: RuntimeRequestContext
    session_context: RuntimeContextBundle
    persona: AgentRuntimePersona
    profile_summary: RuntimeProfileSummary
    permissions: RuntimePermissionSnapshot
    session_budget: RuntimeBudgetSnapshot
    execution_budget: RuntimeExecutionBudget
    session_scope: AgentRuntimeSessionScope = AgentRuntimeSessionScope.MANAGED_WORKER_TASK


def build_internal_worker_runtime_context(
    task_service: WorkerTaskService,
    request: InternalWorkerRuntimeContextRequest,
) -> InternalWorkerRuntimeContext:
    """Build the low-sensitive runtime context for one enabled worker task."""

    if not isinstance(task_service, WorkerTaskService):
        raise InternalWorkerRuntimeContextError(
            "internal worker runtime context requires a WorkerTaskService"
        )
    if not isinstance(request, InternalWorkerRuntimeContextRequest):
        raise InternalWorkerRuntimeContextError(
            "internal worker runtime context requires an InternalWorkerRuntimeContextRequest"
        )

    record = task_service.registry_service.get_worker(request.worker_id)
    if record.status != WorkerLifecycleStatus.ENABLED:
        raise InternalWorkerRuntimeContextError(
            f"Worker is not enabled for runtime execution: {request.worker_id!r}"
        )
    profile = task_service.registry_service.profile_store.load_worker_profile(
        request.worker_id
    )
    task = task_service.get_task(request.task_id)
    if task.worker_id != request.worker_id:
        raise InternalWorkerRuntimeContextError(
            "runtime task worker_id does not match requested worker_id"
        )

    _ensure_string_tuple(request.thread_summary_refs, "thread_summary_refs")
    _ensure_string_tuple(request.organization_summary_refs, "organization_summary_refs")
    _ensure_string_tuple(request.artifact_manifest_refs, "artifact_manifest_refs")
    _ensure_string_tuple(request.relevant_excerpts, "relevant_excerpts")
    _optional_non_empty_string(request.current_thread_id, "current_thread_id")
    _optional_non_empty_string(request.current_thread_summary, "current_thread_summary")
    _ensure_string_tuple(request.private_thread_ids, "private_thread_ids")

    input_message = task.input_summary or task.objective
    task_summary = _task_summary(task)
    prompt_summary = build_worker_prompt_summary(
        profile=profile,
        organization_tree=request.organization_tree,
        department_chat_bindings=request.department_chat_bindings,
        project_chats=request.project_chats,
        department_context_summaries=request.department_context_summaries,
        private_thread_ids=request.private_thread_ids,
        current_thread_id=request.current_thread_id,
        current_thread_summary=request.current_thread_summary,
    )
    request_context = RuntimeRequestContext(
        input_message=input_message,
        worker_prompt_summary=worker_prompt_summary_to_dict(prompt_summary),
        thread_summary_refs=request.thread_summary_refs,
        organization_summary_refs=request.organization_summary_refs,
        artifact_manifest_refs=request.artifact_manifest_refs,
        allowed_tool_descriptions=_allowed_tool_descriptions(profile),
        workspace_policy_ref=_policy_ref("workspace", profile.worker_id),
        redaction_policy_ref="internal-worker-runtime:redaction-policy",
        relevant_excerpts=request.relevant_excerpts,
    )
    session_context = RuntimeContextBundle(
        user_instruction=input_message,
        task_summary=task_summary,
        thread_summary_refs=request.thread_summary_refs,
        relevant_excerpts=request.relevant_excerpts,
    )
    return InternalWorkerRuntimeContext(
        worker_record=record,
        worker_profile=profile,
        task_state=task,
        requested_by=_non_empty_string(request.requested_by, "requested_by"),
        request_context=request_context,
        session_context=session_context,
        persona=_worker_persona(profile),
        profile_summary=_profile_summary(profile),
        permissions=_permission_snapshot(profile),
        session_budget=_session_budget(profile, task),
        execution_budget=_execution_budget(profile, task),
    )


def _worker_persona(profile: WorkerAgentProfile) -> AgentRuntimePersona:
    responsibility_summary = profile.description
    if profile.responsibilities:
        responsibility_summary = "; ".join(profile.responsibilities)
    return AgentRuntimePersona(
        role=AgentRuntimeRole.MANAGED_WORKER,
        lifecycle=AgentRuntimeLifecycle.DURABLE_WORKER,
        display_name=profile.display_name,
        responsibility_summary=responsibility_summary,
        worker_id=profile.worker_id,
        tool_policy_ref=_policy_ref("tools", profile.worker_id),
        memory_policy_ref=_policy_ref("memory", profile.worker_id),
        can_read_private_memory=profile.memory.enabled,
        can_write_private_memory=False,
    )


def _profile_summary(profile: WorkerAgentProfile) -> RuntimeProfileSummary:
    memory_summary_refs = ()
    if profile.memory.enabled:
        memory_summary_refs = (f"workers/{profile.worker_id}/memory/summary.md",)
    return RuntimeProfileSummary(
        worker_id=profile.worker_id,
        identity_ref=f"workers/{profile.worker_id}/worker.json",
        allowed_skill_refs=tuple(
            f"workers/{profile.worker_id}/skills/{skill_id}"
            for skill_id in profile.skills.allowed_skill_ids
        ),
        memory_summary_refs=memory_summary_refs,
    )


def _permission_snapshot(profile: WorkerAgentProfile) -> RuntimePermissionSnapshot:
    return RuntimePermissionSnapshot(
        allowed_tool_names=profile.tools.allowed_tools,
        workspace_read_roots=profile.workspace.read_roots,
        workspace_write_roots=profile.workspace.write_roots,
        approval_required_tool_names=profile.tools.approval_required_tools,
    )


def _session_budget(
    profile: WorkerAgentProfile, task: WorkerTaskState
) -> RuntimeBudgetSnapshot:
    return RuntimeBudgetSnapshot(
        model_name=profile.model.default_model,
        model_policy_ref=None
        if profile.model.default_model
        else _policy_ref("model", profile.worker_id),
        context_window_tokens=profile.model.context_window_tokens,
        max_output_tokens=_task_int_budget(task, "max_turn_tokens")
        or profile.budgets.max_turn_tokens
        or None,
        max_task_tokens=_task_int_budget(task, "max_task_tokens")
        or profile.budgets.max_task_tokens
        or None,
        max_task_cost_usd=_task_float_budget(task, "max_task_cost_usd")
        if "max_task_cost_usd" in task.budgets
        else profile.budgets.max_task_cost_usd,
        wall_time_seconds=_task_int_budget(task, "timeout_seconds")
        or profile.limits.timeout_seconds,
        max_allowed_task_tokens=profile.budgets.max_task_tokens or None,
        max_allowed_task_cost_usd=profile.budgets.max_task_cost_usd,
    )


def _execution_budget(
    profile: WorkerAgentProfile, task: WorkerTaskState
) -> RuntimeExecutionBudget:
    return RuntimeExecutionBudget(
        budget_source=f"worker-profile:{profile.worker_id}",
        model=profile.model.default_model,
        max_input_tokens=profile.model.context_window_tokens,
        max_output_tokens=_task_int_budget(task, "max_turn_tokens")
        or profile.budgets.max_turn_tokens
        or None,
        max_cost_usd=_task_float_budget(task, "max_task_cost_usd")
        if "max_task_cost_usd" in task.budgets
        else profile.budgets.max_task_cost_usd,
        timeout_seconds=_task_int_budget(task, "timeout_seconds")
        or profile.limits.timeout_seconds,
        max_output_bytes=_task_int_budget(task, "max_output_bytes"),
        max_transcript_bytes=_task_int_budget(task, "max_transcript_bytes"),
    )


def _task_summary(task: WorkerTaskState) -> str:
    return f"{task.title}: {task.objective}"


def _allowed_tool_descriptions(profile: WorkerAgentProfile) -> tuple[str, ...]:
    return tuple(
        f"{tool_name}: allowed by worker tool policy"
        for tool_name in profile.tools.allowed_tools
    )


def _policy_ref(policy_name: str, worker_id: str) -> str:
    return f"worker-profile:{worker_id}:{policy_name}"


def _task_int_budget(task: WorkerTaskState, field_name: str) -> int | None:
    value = task.budgets.get(field_name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InternalWorkerRuntimeContextError(
            f"task budget {field_name} must be a positive integer"
        )
    return value


def _task_float_budget(task: WorkerTaskState, field_name: str) -> float | None:
    value = task.budgets.get(field_name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise InternalWorkerRuntimeContextError(
            f"task budget {field_name} must be a non-negative number"
        )
    return float(value)


def _ensure_string_tuple(values: tuple[str, ...], field_name: str) -> None:
    if not isinstance(values, tuple) or any(
        not isinstance(item, str) or not item for item in values
    ):
        raise InternalWorkerRuntimeContextError(
            f"{field_name} must be a tuple of non-empty strings"
        )


def _non_empty_string(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise InternalWorkerRuntimeContextError(
            f"{field_name} must be a non-empty string"
        )
    return value


def _optional_non_empty_string(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    return _non_empty_string(value, field_name)

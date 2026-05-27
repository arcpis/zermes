"""Low-sensitive worker prompt summaries for managed runtime sessions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .department_chats import (
    DepartmentChatBinding,
    DepartmentChatBindingState,
    DepartmentProjectChat,
    DepartmentChatSummary,
)
from .organization import OrgLifecycleState, OrgLeaderKind, OrgNode, OrgNodeType, OrgTree
from .profile import WorkerAgentProfile, validate_worker_id


class WorkerPromptSummaryError(ValueError):
    """Raised when a worker prompt summary cannot be built safely."""


@dataclass(frozen=True)
class WorkerJoinedChatPromptSummary:
    """Chat surface a worker may use without exposing message history."""

    thread_id: str
    chat_kind: str
    org_node_id: str | None = None
    summary: str = ""


@dataclass(frozen=True)
class WorkerDelegationPromptSummary:
    """Prompt-safe decision describing whether a worker may split work."""

    delegation_allowed: bool
    delegation_reason: str
    delegation_targets: tuple[dict[str, str], ...] = ()
    delegation_constraints: dict[str, Any] = field(default_factory=dict)
    required_reply_threads: tuple[str, ...] = ()
    audit_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkerIdentityPromptSummary:
    """Complete low-sensitive identity summary injected into runtime prompts."""

    worker_id: str
    display_name: str
    role: str
    responsibility_summary: str
    department_ids: tuple[str, ...] = ()
    department_names: tuple[str, ...] = ()
    team_ids: tuple[str, ...] = ()
    manager_worker_id: str | None = None
    direct_member_worker_ids: tuple[str, ...] = ()
    department_chat_threads: tuple[WorkerJoinedChatPromptSummary, ...] = ()
    project_chat_threads: tuple[WorkerJoinedChatPromptSummary, ...] = ()
    private_thread_ids: tuple[str, ...] = ()
    default_reply_thread_id: str | None = None
    department_context_refs: tuple[str, ...] = ()
    department_context_summaries: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    workspace_read_roots: tuple[str, ...] = ()
    workspace_write_roots: tuple[str, ...] = ()
    approval_required_tools: tuple[str, ...] = ()
    budget_limits: dict[str, Any] = field(default_factory=dict)
    mention_broadcast_rules: tuple[str, ...] = ()
    current_thread_id: str | None = None
    current_thread_summary: str | None = None
    delegation: WorkerDelegationPromptSummary = field(
        default_factory=lambda: WorkerDelegationPromptSummary(
            delegation_allowed=False,
            delegation_reason="delegation policy has not been evaluated",
        )
    )
    warnings: tuple[str, ...] = ()


def build_worker_prompt_summary(
    *,
    profile: WorkerAgentProfile,
    organization_tree: OrgTree | None = None,
    department_chat_bindings: tuple[DepartmentChatBinding, ...] = (),
    project_chats: tuple[DepartmentProjectChat, ...] = (),
    department_context_summaries: tuple[DepartmentChatSummary, ...] = (),
    private_thread_ids: tuple[str, ...] = (),
    current_thread_id: str | None = None,
    current_thread_summary: str | None = None,
) -> WorkerIdentityPromptSummary:
    """Build the controlled prompt summary from durable low-sensitive inputs."""

    if not isinstance(profile, WorkerAgentProfile):
        raise WorkerPromptSummaryError("profile must be a WorkerAgentProfile")
    validate_worker_id(profile.worker_id)
    org_nodes = _worker_org_nodes(profile.worker_id, organization_tree)
    department_nodes = tuple(
        node for node in org_nodes if node.node_type == OrgNodeType.DEPARTMENT
    )
    team_nodes = tuple(node for node in org_nodes if node.node_type == OrgNodeType.TEAM)
    leader_nodes = _leader_nodes(profile.worker_id, organization_tree)
    direct_members = _direct_member_worker_ids(profile.worker_id, leader_nodes, organization_tree)
    department_chats = _department_chat_summaries(profile.worker_id, department_chat_bindings)
    project_chat_summaries = _project_chat_summaries(
        profile.worker_id,
        project_chats,
        organization_tree,
    )
    context_refs, context_summaries = _department_context_prompt_fields(
        profile.worker_id,
        department_context_summaries,
    )
    default_reply_thread_id = _default_reply_thread(
        current_thread_id,
        department_chats,
        project_chat_summaries,
        private_thread_ids,
    )
    warnings = _warnings(
        org_nodes=org_nodes,
        manager_worker_id=_manager_worker_id(profile.worker_id, org_nodes, organization_tree),
        department_chats=department_chats,
    )
    delegation = _delegation_summary(
        profile=profile,
        leader_nodes=leader_nodes,
        direct_member_worker_ids=direct_members,
        default_reply_thread_id=default_reply_thread_id,
        department_chat_threads=department_chats,
    )
    return WorkerIdentityPromptSummary(
        worker_id=profile.worker_id,
        display_name=profile.display_name,
        role=profile.role,
        responsibility_summary=_responsibility_summary(profile),
        department_ids=tuple(node.org_node_id for node in department_nodes),
        department_names=tuple(node.name for node in department_nodes),
        team_ids=tuple(node.org_node_id for node in team_nodes),
        manager_worker_id=_manager_worker_id(profile.worker_id, org_nodes, organization_tree),
        direct_member_worker_ids=direct_members,
        department_chat_threads=department_chats,
        project_chat_threads=project_chat_summaries,
        private_thread_ids=_string_tuple(private_thread_ids, "private_thread_ids"),
        default_reply_thread_id=default_reply_thread_id,
        department_context_refs=context_refs,
        department_context_summaries=context_summaries,
        allowed_tools=profile.tools.allowed_tools,
        workspace_read_roots=profile.workspace.read_roots,
        workspace_write_roots=profile.workspace.write_roots,
        approval_required_tools=profile.tools.approval_required_tools,
        budget_limits={
            "max_task_tokens": profile.budgets.max_task_tokens,
            "max_turn_tokens": profile.budgets.max_turn_tokens,
            "max_task_cost_usd": profile.budgets.max_task_cost_usd,
            "timeout_seconds": profile.limits.timeout_seconds,
            "max_concurrent_tasks": profile.limits.max_concurrent_tasks,
        },
        mention_broadcast_rules=(
            "Handle mentions only when addressed through Message Router delivery.",
            "Broadcasts are informational unless delivery requires an explicit reply.",
            "Reply only through default_reply_thread_id or the current source thread.",
        ),
        current_thread_id=current_thread_id,
        current_thread_summary=current_thread_summary,
        delegation=delegation,
        warnings=warnings,
    )


def worker_prompt_summary_to_dict(
    summary: WorkerIdentityPromptSummary,
) -> dict[str, Any]:
    """Return a deterministic JSON-ready prompt summary mapping."""

    return {
        "worker_id": summary.worker_id,
        "display_name": summary.display_name,
        "role": summary.role,
        "responsibility_summary": summary.responsibility_summary,
        "department_ids": list(summary.department_ids),
        "department_names": list(summary.department_names),
        "team_ids": list(summary.team_ids),
        "manager_worker_id": summary.manager_worker_id,
        "direct_member_worker_ids": list(summary.direct_member_worker_ids),
        "department_chat_threads": [
            _chat_summary_to_dict(chat) for chat in summary.department_chat_threads
        ],
        "project_chat_threads": [
            _chat_summary_to_dict(chat) for chat in summary.project_chat_threads
        ],
        "private_thread_ids": list(summary.private_thread_ids),
        "default_reply_thread_id": summary.default_reply_thread_id,
        "department_context_refs": list(summary.department_context_refs),
        "department_context_summaries": list(summary.department_context_summaries),
        "allowed_tools": list(summary.allowed_tools),
        "workspace_read_roots": list(summary.workspace_read_roots),
        "workspace_write_roots": list(summary.workspace_write_roots),
        "approval_required_tools": list(summary.approval_required_tools),
        "budget_limits": dict(summary.budget_limits),
        "mention_broadcast_rules": list(summary.mention_broadcast_rules),
        "current_thread_id": summary.current_thread_id,
        "current_thread_summary": summary.current_thread_summary,
        "delegation": worker_delegation_prompt_summary_to_dict(summary.delegation),
        "warnings": list(summary.warnings),
    }


def worker_delegation_prompt_summary_to_dict(
    summary: WorkerDelegationPromptSummary,
) -> dict[str, Any]:
    return {
        "delegation_allowed": summary.delegation_allowed,
        "delegation_reason": summary.delegation_reason,
        "delegation_targets": [dict(target) for target in summary.delegation_targets],
        "delegation_constraints": dict(summary.delegation_constraints),
        "required_reply_threads": list(summary.required_reply_threads),
        "audit_refs": list(summary.audit_refs),
    }


def _worker_org_nodes(worker_id: str, tree: OrgTree | None) -> tuple[OrgNode, ...]:
    if tree is None:
        return ()
    return tuple(
        node
        for node in tree.nodes.values()
        if node.lifecycle == OrgLifecycleState.ACTIVE
        and (
            worker_id in node.member_worker_ids
            or node.individual_worker_id == worker_id
            or node.leader.worker_id == worker_id
        )
    )


def _leader_nodes(worker_id: str, tree: OrgTree | None) -> tuple[OrgNode, ...]:
    if tree is None:
        return ()
    return tuple(
        node
        for node in tree.nodes.values()
        if node.lifecycle == OrgLifecycleState.ACTIVE
        and node.leader.kind == OrgLeaderKind.WORKER
        and node.leader.worker_id == worker_id
    )


def _manager_worker_id(
    worker_id: str,
    org_nodes: tuple[OrgNode, ...],
    tree: OrgTree | None,
) -> str | None:
    if tree is None:
        return None
    for node in org_nodes:
        if node.leader.worker_id and node.leader.worker_id != worker_id:
            return node.leader.worker_id
        if node.parent_id:
            parent = tree.nodes.get(node.parent_id)
            if parent and parent.leader.worker_id and parent.leader.worker_id != worker_id:
                return parent.leader.worker_id
    return None


def _direct_member_worker_ids(
    worker_id: str,
    leader_nodes: tuple[OrgNode, ...],
    tree: OrgTree | None,
) -> tuple[str, ...]:
    members: list[str] = []
    for node in leader_nodes:
        members.extend(member for member in node.member_worker_ids if member != worker_id)
        if tree is not None:
            for child_id in node.child_ids:
                child = tree.nodes.get(child_id)
                if child is None or child.lifecycle != OrgLifecycleState.ACTIVE:
                    continue
                if child.individual_worker_id and child.individual_worker_id != worker_id:
                    members.append(child.individual_worker_id)
                if child.leader.worker_id and child.leader.worker_id != worker_id:
                    members.append(child.leader.worker_id)
    return tuple(dict.fromkeys(members))


def _department_chat_summaries(
    worker_id: str,
    bindings: tuple[DepartmentChatBinding, ...],
) -> tuple[WorkerJoinedChatPromptSummary, ...]:
    result: list[WorkerJoinedChatPromptSummary] = []
    for binding in bindings:
        if binding.state != DepartmentChatBindingState.ACTIVE:
            continue
        if worker_id not in binding.member_worker_ids and binding.owner_worker_id != worker_id:
            continue
        result.append(
            WorkerJoinedChatPromptSummary(
                thread_id=binding.thread_id,
                chat_kind=binding.binding_type.value,
                org_node_id=binding.org_node_id,
                summary=binding.audit_summary,
            )
        )
    return tuple(result)


def _project_chat_summaries(
    worker_id: str,
    project_chats: tuple[DepartmentProjectChat, ...],
    tree: OrgTree | None,
) -> tuple[WorkerJoinedChatPromptSummary, ...]:
    if tree is None:
        return ()
    worker_org_ids = {node.org_node_id for node in _worker_org_nodes(worker_id, tree)}
    result = []
    for project in project_chats:
        if worker_org_ids.isdisjoint(project.participant_org_node_ids):
            continue
        result.append(
            WorkerJoinedChatPromptSummary(
                thread_id=project.thread_id,
                chat_kind="project",
                org_node_id=None,
                summary=f"Project chat {project.project_id}",
            )
        )
    return tuple(result)


def _department_context_prompt_fields(
    worker_id: str,
    summaries: tuple[DepartmentChatSummary, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    refs: list[str] = []
    bodies: list[str] = []
    for summary in summaries:
        refs.extend(summary.audit_refs)
        if summary.body:
            bodies.append(summary.body)
    return tuple(dict.fromkeys(refs)), tuple(dict.fromkeys(bodies))


def _delegation_summary(
    *,
    profile: WorkerAgentProfile,
    leader_nodes: tuple[OrgNode, ...],
    direct_member_worker_ids: tuple[str, ...],
    default_reply_thread_id: str | None,
    department_chat_threads: tuple[WorkerJoinedChatPromptSummary, ...],
) -> WorkerDelegationPromptSummary:
    audit_refs = (f"workers/{profile.worker_id}/worker.json",)
    reply_threads = tuple(
        dict.fromkeys(
            thread_id
            for thread_id in (
                default_reply_thread_id,
                *(chat.thread_id for chat in department_chat_threads),
            )
            if thread_id
        )
    )
    constraints = {
        "allowed_child_models": list(profile.delegation.allowed_child_models),
        "allowed_child_tools": list(profile.delegation.allowed_child_tools),
        "max_child_task_tokens": profile.delegation.max_child_task_tokens,
        "workspace_read_roots": list(profile.workspace.read_roots),
        "workspace_write_roots": list(profile.workspace.write_roots),
        "approval_required_tools": list(profile.tools.approval_required_tools),
        "max_concurrent_tasks": profile.limits.max_concurrent_tasks,
    }
    if not direct_member_worker_ids:
        return WorkerDelegationPromptSummary(
            delegation_allowed=False,
            delegation_reason="worker has no direct subordinate workers",
            delegation_constraints=constraints,
            required_reply_threads=reply_threads,
            audit_refs=audit_refs,
        )
    if not profile.delegation.allow_temporary_child_agents:
        return WorkerDelegationPromptSummary(
            delegation_allowed=False,
            delegation_reason="worker delegation policy does not allow child agents",
            delegation_constraints=constraints,
            required_reply_threads=reply_threads,
            audit_refs=audit_refs,
        )
    targets = tuple(
        {"target_type": "worker", "worker_id": worker_id}
        for worker_id in direct_member_worker_ids
    ) + tuple(
        {
            "target_type": node.node_type.value,
            "org_node_id": node.org_node_id,
            "name": node.name,
        }
        for node in leader_nodes
    )
    return WorkerDelegationPromptSummary(
        delegation_allowed=True,
        delegation_reason="worker leads active organization nodes and policy allows child agents",
        delegation_targets=targets,
        delegation_constraints=constraints,
        required_reply_threads=reply_threads,
        audit_refs=audit_refs,
    )


def _default_reply_thread(
    current_thread_id: str | None,
    department_chats: tuple[WorkerJoinedChatPromptSummary, ...],
    project_chats: tuple[WorkerJoinedChatPromptSummary, ...],
    private_thread_ids: tuple[str, ...],
) -> str | None:
    if current_thread_id:
        return current_thread_id
    for collection in (department_chats, project_chats):
        if collection:
            return collection[0].thread_id
    if private_thread_ids:
        return private_thread_ids[0]
    return None


def _responsibility_summary(profile: WorkerAgentProfile) -> str:
    return "; ".join(profile.responsibilities) if profile.responsibilities else profile.description


def _warnings(
    *,
    org_nodes: tuple[OrgNode, ...],
    manager_worker_id: str | None,
    department_chats: tuple[WorkerJoinedChatPromptSummary, ...],
) -> tuple[str, ...]:
    warnings: list[str] = []
    if not org_nodes:
        warnings.append("missing_department_membership")
    if manager_worker_id is None:
        warnings.append("missing_manager_reference")
    if not department_chats:
        warnings.append("no_joined_department_chat")
    return tuple(warnings)


def _chat_summary_to_dict(summary: WorkerJoinedChatPromptSummary) -> dict[str, Any]:
    return {
        "thread_id": summary.thread_id,
        "chat_kind": summary.chat_kind,
        "org_node_id": summary.org_node_id,
        "summary": summary.summary,
    }


def _string_tuple(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    if not isinstance(values, tuple) or any(
        not isinstance(value, str) or not value for value in values
    ):
        raise WorkerPromptSummaryError(f"{field_name} must be a tuple of strings")
    return values

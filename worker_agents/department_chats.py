"""Department chat bindings for managed worker organization nodes."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from .message_router import (
    ChatParticipantKind,
    ChatParticipantRef,
    ChatThreadType,
    WorkerChatThread,
)
from .organization import MAIN_AGENT_ID, OrganizationError, validate_org_node_id
from .organization import OrgLeaderKind, OrgLifecycleState, OrgNode, OrgNodeType
from .profile import WorkerProfileError, validate_worker_id
from .registry import WorkerLifecycleStatus
from .storage.safe_paths import validate_single_path_segment


DEPARTMENT_CHAT_BINDING_SCHEMA_VERSION = 1


class DepartmentChatError(ValueError):
    """Raised when a department chat binding or summary is invalid."""


class DepartmentChatBindingType(StrEnum):
    """Kinds of organization chat bindings."""

    DEPARTMENT_DEFAULT = "department_default"
    TEAM_DEFAULT = "team_default"
    PROJECT = "project"


class DepartmentChatBindingState(StrEnum):
    """Lifecycle state for a chat binding without managing thread history."""

    ACTIVE = "active"
    PENDING_UPDATE = "pending_update"
    CLOSED = "closed"
    ARCHIVED = "archived"


class DepartmentChatMemberSyncAction(StrEnum):
    """How one worker should be handled during binding membership sync."""

    ADD = "add"
    REMOVE = "remove"
    KEEP = "keep"
    REVIEW = "review"


class DepartmentChatPlanStatus(StrEnum):
    """Outcome status for a proposed binding operation."""

    READY = "ready"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"


class DepartmentChatFallbackKind(StrEnum):
    """Alternative collaboration surface for a single-worker department."""

    DIRECT_THREAD = "direct_thread"
    PARENT_GROUP_THREAD = "parent_group_thread"
    DIRECT_THREAD_PLAN = "direct_thread_plan"


class DepartmentChatSummaryType(StrEnum):
    """Summary kinds that may move between department chats."""

    PERIODIC = "periodic_summary"
    DECISION = "decision"
    DELIVERABLE = "deliverable"
    RISK = "risk"
    HANDOFF = "handoff"
    FINAL_ARCHIVE = "final_archive_summary"


class DepartmentChatSummaryStatus(StrEnum):
    """Delivery state for a low-sensitivity department chat summary."""

    DRAFT = "draft"
    READY = "ready"
    DELIVERED = "delivered"
    REJECTED = "rejected"


@dataclass(frozen=True)
class DepartmentChatBinding:
    """Low-sensitivity link between an organization node and a chat thread."""

    binding_id: str
    org_node_id: str
    thread_id: str
    binding_type: DepartmentChatBindingType
    state: DepartmentChatBindingState = DepartmentChatBindingState.ACTIVE
    owner_worker_id: str | None = None
    member_worker_ids: tuple[str, ...] = ()
    required_participants: tuple[ChatParticipantRef, ...] = ()
    parent_summary_targets: tuple[str, ...] = ()
    created_at: str | None = None
    updated_at: str | None = None
    revision: int = 0
    audit_summary: str = ""
    schema_version: int = DEPARTMENT_CHAT_BINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_binding_id(self.binding_id, "binding_id")
        _validate_org_id(self.org_node_id, "org_node_id")
        _validate_binding_id(self.thread_id, "thread_id")
        object.__setattr__(
            self, "binding_type", _binding_type(self.binding_type)
        )
        object.__setattr__(self, "state", _binding_state(self.state))
        if self.owner_worker_id is not None:
            _validate_worker(self.owner_worker_id, "owner_worker_id")
        members = _unique_workers(self.member_worker_ids, "member_worker_ids")
        object.__setattr__(self, "member_worker_ids", members)
        participants = tuple(self.required_participants)
        _validate_required_participants(participants)
        object.__setattr__(self, "required_participants", participants)
        targets = _unique_org_ids(
            self.parent_summary_targets, "parent_summary_targets"
        )
        object.__setattr__(self, "parent_summary_targets", targets)
        _optional_string(self.created_at, "created_at")
        _optional_string(self.updated_at, "updated_at")
        _non_negative_int(self.revision, "revision")
        _string_value(self.audit_summary, "audit_summary")
        if self.schema_version != DEPARTMENT_CHAT_BINDING_SCHEMA_VERSION:
            raise DepartmentChatError(
                f"Unsupported department chat schema_version: {self.schema_version!r}"
            )


@dataclass(frozen=True)
class DepartmentChatBindingSummary:
    """Low-sensitivity binding summary safe for UI, audit, and prompt context."""

    binding_id: str
    org_node_id: str
    thread_id: str
    binding_type: DepartmentChatBindingType
    state: DepartmentChatBindingState
    owner_worker_id: str | None
    member_count: int
    parent_summary_target_count: int
    audit_summary: str = ""


@dataclass(frozen=True)
class DepartmentChatMemberSyncItem:
    """One worker membership change proposed for a department chat binding."""

    worker_id: str
    action: DepartmentChatMemberSyncAction
    reason: str = ""

    def __post_init__(self) -> None:
        _validate_worker(self.worker_id, "worker_id")
        object.__setattr__(self, "action", _sync_action(self.action))
        _string_value(self.reason, "reason")


@dataclass(frozen=True)
class DepartmentChatMemberSyncPlan:
    """Auditable membership update plan; callers decide when to apply it."""

    binding_id: str
    status: DepartmentChatPlanStatus
    items: tuple[DepartmentChatMemberSyncItem, ...] = ()
    reason: str = ""

    def __post_init__(self) -> None:
        _validate_binding_id(self.binding_id, "binding_id")
        object.__setattr__(self, "status", _plan_status(self.status))
        object.__setattr__(self, "items", tuple(self.items))
        _string_value(self.reason, "reason")


@dataclass(frozen=True)
class DepartmentChatBindingPlan:
    """Result of planning a department or team default chat binding."""

    status: DepartmentChatPlanStatus
    binding: DepartmentChatBinding | None = None
    fallback_target: DepartmentChatFallbackTarget | None = None
    member_sync_plan: DepartmentChatMemberSyncPlan | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _plan_status(self.status))
        _string_value(self.reason, "reason")


@dataclass(frozen=True)
class DepartmentChatFallbackTarget:
    """Auditable fallback when a department group chat should not exist."""

    fallback_kind: DepartmentChatFallbackKind
    worker_id: str | None = None
    thread_id: str | None = None
    parent_org_node_id: str | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "fallback_kind", _fallback_kind(self.fallback_kind))
        if self.worker_id is not None:
            _validate_worker(self.worker_id, "worker_id")
        if self.thread_id is not None:
            _validate_binding_id(self.thread_id, "thread_id")
        if self.parent_org_node_id is not None:
            _validate_org_id(self.parent_org_node_id, "parent_org_node_id")
        _string_value(self.reason, "reason")


@dataclass(frozen=True)
class SingleWorkerDepartmentPlan:
    """Plan describing how to avoid a redundant one-worker group chat."""

    status: DepartmentChatPlanStatus
    employee_worker_ids: tuple[str, ...]
    fallback_target: DepartmentChatFallbackTarget | None = None
    member_sync_plan: DepartmentChatMemberSyncPlan | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _plan_status(self.status))
        object.__setattr__(
            self,
            "employee_worker_ids",
            _unique_workers(self.employee_worker_ids, "employee_worker_ids"),
        )
        _string_value(self.reason, "reason")


@dataclass(frozen=True)
class DepartmentChatSummary:
    """Low-sensitivity summary shared across department chat boundaries."""

    summary_id: str
    source_org_node_id: str
    source_thread_id: str
    target_org_node_id: str
    target_thread_id: str
    summary_type: DepartmentChatSummaryType
    status: DepartmentChatSummaryStatus
    body: str
    manifest_refs: tuple[str, ...] = ()
    audit_refs: tuple[str, ...] = ()
    created_at: str | None = None
    is_project_summary: bool = False
    schema_version: int = DEPARTMENT_CHAT_BINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_binding_id(self.summary_id, "summary_id")
        _validate_org_id(self.source_org_node_id, "source_org_node_id")
        _validate_binding_id(self.source_thread_id, "source_thread_id")
        _validate_org_id(self.target_org_node_id, "target_org_node_id")
        _validate_binding_id(self.target_thread_id, "target_thread_id")
        object.__setattr__(self, "summary_type", _summary_type(self.summary_type))
        object.__setattr__(self, "status", _summary_status(self.status))
        _validate_low_sensitivity_body(self.body)
        object.__setattr__(
            self, "manifest_refs", _safe_ref_tuple(self.manifest_refs, "manifest_refs")
        )
        object.__setattr__(
            self, "audit_refs", _safe_ref_tuple(self.audit_refs, "audit_refs")
        )
        _optional_string(self.created_at, "created_at")
        if not isinstance(self.is_project_summary, bool):
            raise DepartmentChatError("is_project_summary must be a boolean")
        if self.schema_version != DEPARTMENT_CHAT_BINDING_SCHEMA_VERSION:
            raise DepartmentChatError(
                f"Unsupported department chat summary schema_version: {self.schema_version!r}"
            )


@dataclass(frozen=True)
class DepartmentProjectChat:
    """Minimal cross-department project chat structure."""

    project_id: str
    thread_id: str
    participant_org_node_ids: tuple[str, ...]
    summary_target_org_node_ids: tuple[str, ...]
    deliverable_manifest_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_binding_id(self.project_id, "project_id")
        _validate_binding_id(self.thread_id, "thread_id")
        object.__setattr__(
            self,
            "participant_org_node_ids",
            _unique_org_ids(self.participant_org_node_ids, "participant_org_node_ids"),
        )
        object.__setattr__(
            self,
            "summary_target_org_node_ids",
            _unique_org_ids(
                self.summary_target_org_node_ids, "summary_target_org_node_ids"
            ),
        )
        object.__setattr__(
            self,
            "deliverable_manifest_refs",
            _safe_ref_tuple(
                self.deliverable_manifest_refs, "deliverable_manifest_refs"
            ),
        )


class DepartmentChatBindingService:
    """Plans department chat bindings from organization and registry summaries."""

    def __init__(
        self,
        *,
        worker_lookup: Mapping[str, Any],
        user_id: str,
    ) -> None:
        self.worker_lookup = worker_lookup
        self.user_id = user_id

    def plan_default_binding(
        self,
        *,
        org_node: OrgNode,
        thread_id: str,
        binding_id: str | None = None,
        existing_binding: DepartmentChatBinding | None = None,
    ) -> DepartmentChatBindingPlan:
        """Create a default chat binding plan without mutating router state."""
        node_error = self._node_unavailable_reason(org_node)
        if node_error:
            return DepartmentChatBindingPlan(
                status=DepartmentChatPlanStatus.REJECTED,
                reason=node_error,
            )
        owner_worker_id = self._owner_worker_id(org_node)
        if owner_worker_id is None:
            return DepartmentChatBindingPlan(
                status=DepartmentChatPlanStatus.NEEDS_REVIEW,
                reason="organization node requires a worker leader",
            )
        expected_workers = tuple(
            dict.fromkeys((owner_worker_id, *org_node.member_worker_ids))
        )
        unavailable = [
            worker_id
            for worker_id in expected_workers
            if not self._worker_can_join(worker_id)
        ]
        if unavailable:
            return DepartmentChatBindingPlan(
                status=DepartmentChatPlanStatus.REJECTED,
                reason=f"unavailable worker references: {', '.join(unavailable)}",
            )
        single_worker_plan = plan_single_worker_department_chat(
            org_node=org_node,
            employee_worker_ids=expected_workers,
            direct_thread_id_by_worker={},
            parent_thread_id_by_org={},
            current_binding=existing_binding,
        )
        if single_worker_plan.status == DepartmentChatPlanStatus.NEEDS_REVIEW:
            return DepartmentChatBindingPlan(
                status=DepartmentChatPlanStatus.NEEDS_REVIEW,
                fallback_target=single_worker_plan.fallback_target,
                member_sync_plan=single_worker_plan.member_sync_plan,
                reason=single_worker_plan.reason,
            )
        binding = DepartmentChatBinding(
            binding_id=binding_id or f"{org_node.org_node_id}-default",
            org_node_id=org_node.org_node_id,
            thread_id=thread_id,
            binding_type=_default_binding_type_for_node(org_node),
            owner_worker_id=owner_worker_id,
            member_worker_ids=expected_workers,
            required_participants=required_department_chat_participants(self.user_id),
            parent_summary_targets=(org_node.parent_id,) if org_node.parent_id else (),
            audit_summary=f"Default chat binding for {org_node.org_node_id}.",
        )
        return DepartmentChatBindingPlan(
            status=DepartmentChatPlanStatus.READY,
            binding=binding,
            member_sync_plan=plan_department_chat_member_sync(
                current_binding=existing_binding,
                planned_binding=binding,
            )
            if existing_binding is not None
            else None,
        )

    def validate_binding_participants(
        self, binding: DepartmentChatBinding, thread: WorkerChatThread
    ) -> None:
        """Validate that an existing thread still satisfies a binding."""
        if not thread_has_required_department_participants(thread):
            raise DepartmentChatError("department chat thread requires user and main agent")
        if thread.thread_type not in {
            ChatThreadType.ORGANIZATION_GROUP,
            ChatThreadType.PROJECT_GROUP,
        }:
            raise DepartmentChatError("department chat binding requires a group thread")
        worker_participants = {
            participant.participant_id
            for participant in thread.participants
            if participant.kind == ChatParticipantKind.WORKER
        }
        missing_workers = [
            worker_id
            for worker_id in binding.member_worker_ids
            if worker_id not in worker_participants
        ]
        if missing_workers:
            raise DepartmentChatError(
                f"department chat thread is missing workers: {', '.join(missing_workers)}"
            )

    def _node_unavailable_reason(self, org_node: OrgNode) -> str:
        if org_node.node_type not in {OrgNodeType.DEPARTMENT, OrgNodeType.TEAM}:
            return "default chat bindings require a department or team node"
        if org_node.lifecycle != OrgLifecycleState.ACTIVE:
            return "default chat bindings require an active organization node"
        return ""

    def _owner_worker_id(self, org_node: OrgNode) -> str | None:
        if org_node.leader.kind != OrgLeaderKind.WORKER:
            return None
        return org_node.leader.worker_id

    def _worker_can_join(self, worker_id: str) -> bool:
        record = self.worker_lookup.get(worker_id)
        status = _worker_status_value(record)
        return status not in {
            WorkerLifecycleStatus.ARCHIVED.value,
            WorkerLifecycleStatus.DELETED.value,
        } and record is not None


def count_department_chat_employees(*worker_id_groups: tuple[str, ...]) -> tuple[str, ...]:
    """Return unique worker ids that count as employees in a department chat."""
    employee_ids: dict[str, None] = {}
    for group in worker_id_groups:
        for worker_id in group:
            _validate_worker(worker_id, "employee_worker_ids")
            employee_ids[worker_id] = None
    return tuple(employee_ids)


def plan_single_worker_department_chat(
    *,
    org_node: OrgNode,
    employee_worker_ids: tuple[str, ...],
    direct_thread_id_by_worker: Mapping[str, str],
    parent_thread_id_by_org: Mapping[str, str],
    current_binding: DepartmentChatBinding | None = None,
) -> SingleWorkerDepartmentPlan:
    """Choose a non-group fallback for departments with fewer than two employees."""
    employees = count_department_chat_employees(employee_worker_ids)
    if len(employees) >= 2:
        return SingleWorkerDepartmentPlan(
            status=DepartmentChatPlanStatus.READY,
            employee_worker_ids=employees,
            reason="department has enough employee participants for a group chat",
        )
    if not employees:
        return SingleWorkerDepartmentPlan(
            status=DepartmentChatPlanStatus.NEEDS_REVIEW,
            employee_worker_ids=employees,
            reason="department has no employee participants",
        )
    worker_id = employees[0]
    sync_plan = None
    if current_binding is not None and current_binding.state in {
        DepartmentChatBindingState.ACTIVE,
        DepartmentChatBindingState.PENDING_UPDATE,
    }:
        sync_plan = DepartmentChatMemberSyncPlan(
            binding_id=current_binding.binding_id,
            status=DepartmentChatPlanStatus.NEEDS_REVIEW,
            items=(
                DepartmentChatMemberSyncItem(
                    worker_id=worker_id,
                    action=DepartmentChatMemberSyncAction.REVIEW,
                    reason="single-worker department should use fallback chat",
                ),
            ),
            reason="close group entry and preserve summaries before migrating",
        )
    return SingleWorkerDepartmentPlan(
        status=DepartmentChatPlanStatus.NEEDS_REVIEW,
        employee_worker_ids=employees,
        fallback_target=_single_worker_fallback(
            org_node=org_node,
            worker_id=worker_id,
            direct_thread_id_by_worker=direct_thread_id_by_worker,
            parent_thread_id_by_org=parent_thread_id_by_org,
        ),
        member_sync_plan=sync_plan,
        reason="single-worker departments should not create group chats",
    )


def _single_worker_fallback(
    *,
    org_node: OrgNode,
    worker_id: str,
    direct_thread_id_by_worker: Mapping[str, str],
    parent_thread_id_by_org: Mapping[str, str],
) -> DepartmentChatFallbackTarget:
    direct_thread_id = direct_thread_id_by_worker.get(worker_id)
    if direct_thread_id:
        return DepartmentChatFallbackTarget(
            fallback_kind=DepartmentChatFallbackKind.DIRECT_THREAD,
            worker_id=worker_id,
            thread_id=direct_thread_id,
            reason="use existing direct thread for the only employee",
        )
    if org_node.parent_id is not None:
        parent_thread_id = parent_thread_id_by_org.get(org_node.parent_id)
        if parent_thread_id:
            return DepartmentChatFallbackTarget(
                fallback_kind=DepartmentChatFallbackKind.PARENT_GROUP_THREAD,
                worker_id=worker_id,
                thread_id=parent_thread_id,
                parent_org_node_id=org_node.parent_id,
                reason="use parent group chat with summary-only context",
            )
    return DepartmentChatFallbackTarget(
        fallback_kind=DepartmentChatFallbackKind.DIRECT_THREAD_PLAN,
        worker_id=worker_id,
        reason="create or reuse a direct thread for the only employee",
    )


def plan_department_chat_member_sync(
    *,
    current_binding: DepartmentChatBinding | None,
    planned_binding: DepartmentChatBinding,
) -> DepartmentChatMemberSyncPlan:
    """Compare current and planned members without editing thread history."""
    if current_binding is None:
        items = tuple(
            DepartmentChatMemberSyncItem(
                worker_id=worker_id,
                action=DepartmentChatMemberSyncAction.ADD,
                reason="new default chat member",
            )
            for worker_id in planned_binding.member_worker_ids
        )
        return DepartmentChatMemberSyncPlan(
            binding_id=planned_binding.binding_id,
            status=DepartmentChatPlanStatus.READY,
            items=items,
        )
    if current_binding.state in {
        DepartmentChatBindingState.CLOSED,
        DepartmentChatBindingState.ARCHIVED,
    }:
        return DepartmentChatMemberSyncPlan(
            binding_id=current_binding.binding_id,
            status=DepartmentChatPlanStatus.NEEDS_REVIEW,
            reason="closed or archived bindings require explicit reopening approval",
        )
    current_members = set(current_binding.member_worker_ids)
    planned_members = set(planned_binding.member_worker_ids)
    items = []
    for worker_id in sorted(planned_members - current_members):
        items.append(
            DepartmentChatMemberSyncItem(
                worker_id=worker_id,
                action=DepartmentChatMemberSyncAction.ADD,
                reason="organization member added",
            )
        )
    for worker_id in sorted(current_members & planned_members):
        items.append(
            DepartmentChatMemberSyncItem(
                worker_id=worker_id,
                action=DepartmentChatMemberSyncAction.KEEP,
                reason="organization member retained",
            )
        )
    for worker_id in sorted(current_members - planned_members):
        items.append(
            DepartmentChatMemberSyncItem(
                worker_id=worker_id,
                action=DepartmentChatMemberSyncAction.REMOVE,
                reason="organization member removed",
            )
        )
    return DepartmentChatMemberSyncPlan(
        binding_id=current_binding.binding_id,
        status=DepartmentChatPlanStatus.READY,
        items=tuple(items),
    )


_BINDING_FIELDS = {
    "binding_id",
    "schema_version",
    "org_node_id",
    "thread_id",
    "binding_type",
    "state",
    "owner_worker_id",
    "member_worker_ids",
    "required_participants",
    "parent_summary_targets",
    "created_at",
    "updated_at",
    "revision",
    "audit_summary",
}
_PARTICIPANT_FIELDS = {"kind", "participant_id"}


def department_chat_binding_from_dict(
    data: Mapping[str, Any]
) -> DepartmentChatBinding:
    """Load a binding from a strict dictionary contract."""
    data = _require_mapping(data, "department_chat_binding")
    _reject_unknown_fields(data, _BINDING_FIELDS, "department_chat_binding")
    participants = _require_list(
        data.get("required_participants", ()), "required_participants"
    )
    return DepartmentChatBinding(
        binding_id=_require_string(data.get("binding_id"), "binding_id"),
        schema_version=data.get(
            "schema_version", DEPARTMENT_CHAT_BINDING_SCHEMA_VERSION
        ),
        org_node_id=_require_string(data.get("org_node_id"), "org_node_id"),
        thread_id=_require_string(data.get("thread_id"), "thread_id"),
        binding_type=_binding_type(data.get("binding_type")),
        state=_binding_state(data.get("state", DepartmentChatBindingState.ACTIVE)),
        owner_worker_id=_optional_string(
            data.get("owner_worker_id"), "owner_worker_id"
        ),
        member_worker_ids=_string_tuple(
            data.get("member_worker_ids", ()), "member_worker_ids"
        ),
        required_participants=tuple(
            chat_participant_from_dict(participant) for participant in participants
        ),
        parent_summary_targets=_string_tuple(
            data.get("parent_summary_targets", ()), "parent_summary_targets"
        ),
        created_at=_optional_string(data.get("created_at"), "created_at"),
        updated_at=_optional_string(data.get("updated_at"), "updated_at"),
        revision=_non_negative_int(data.get("revision", 0), "revision"),
        audit_summary=_require_string(data.get("audit_summary", ""), "audit_summary"),
    )


def department_chat_binding_to_dict(
    binding: DepartmentChatBinding,
) -> dict[str, Any]:
    """Dump a binding without transcript or private worker assets."""
    return {
        "binding_id": binding.binding_id,
        "schema_version": binding.schema_version,
        "org_node_id": binding.org_node_id,
        "thread_id": binding.thread_id,
        "binding_type": binding.binding_type.value,
        "state": binding.state.value,
        "owner_worker_id": binding.owner_worker_id,
        "member_worker_ids": list(binding.member_worker_ids),
        "required_participants": [
            chat_participant_to_dict(participant)
            for participant in binding.required_participants
        ],
        "parent_summary_targets": list(binding.parent_summary_targets),
        "created_at": binding.created_at,
        "updated_at": binding.updated_at,
        "revision": binding.revision,
        "audit_summary": binding.audit_summary,
    }


def dump_department_chat_binding_json(binding: DepartmentChatBinding) -> str:
    """Dump a binding as stable JSON text."""
    return json.dumps(
        department_chat_binding_to_dict(binding), ensure_ascii=False, indent=2
    )


def load_department_chat_binding_json(payload: str) -> DepartmentChatBinding:
    """Load a binding from JSON text."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise DepartmentChatError(
            f"Invalid department chat binding JSON: {exc.msg}"
        ) from exc
    return department_chat_binding_from_dict(data)


def summarize_department_chat_binding(
    binding: DepartmentChatBinding,
) -> DepartmentChatBindingSummary:
    """Return a low-sensitivity summary for a department chat binding."""
    return DepartmentChatBindingSummary(
        binding_id=binding.binding_id,
        org_node_id=binding.org_node_id,
        thread_id=binding.thread_id,
        binding_type=binding.binding_type,
        state=binding.state,
        owner_worker_id=binding.owner_worker_id,
        member_count=len(binding.member_worker_ids),
        parent_summary_target_count=len(binding.parent_summary_targets),
        audit_summary=binding.audit_summary,
    )


def department_chat_binding_summary_to_dict(
    summary: DepartmentChatBindingSummary,
) -> dict[str, Any]:
    return {
        "binding_id": summary.binding_id,
        "org_node_id": summary.org_node_id,
        "thread_id": summary.thread_id,
        "binding_type": summary.binding_type.value,
        "state": summary.state.value,
        "owner_worker_id": summary.owner_worker_id,
        "member_count": summary.member_count,
        "parent_summary_target_count": summary.parent_summary_target_count,
        "audit_summary": summary.audit_summary,
    }


def required_department_chat_participants(
    user_id: str,
) -> tuple[ChatParticipantRef, ChatParticipantRef]:
    """Return the required user and main-agent participants for group chats."""
    return (
        ChatParticipantRef(ChatParticipantKind.USER, user_id),
        ChatParticipantRef(ChatParticipantKind.MAIN_AGENT, MAIN_AGENT_ID),
    )


def thread_has_required_department_participants(thread: WorkerChatThread) -> bool:
    """Return whether a thread has the user and main-agent participants."""
    kinds = {participant.kind for participant in thread.participants}
    return ChatParticipantKind.USER in kinds and ChatParticipantKind.MAIN_AGENT in kinds


def plan_department_chat_summary(
    *,
    summary_id: str,
    source_node: OrgNode,
    source_thread_id: str,
    target_node: OrgNode,
    target_thread_id: str,
    summary_type: DepartmentChatSummaryType,
    body: str,
    manifest_refs: tuple[str, ...] = (),
    audit_refs: tuple[str, ...] = (),
    created_at: str | None = None,
    is_project_summary: bool = False,
) -> DepartmentChatSummary:
    """Build a low-sensitivity summary while enforcing hierarchy boundaries."""
    if (
        source_node.parent_id != target_node.org_node_id
        and not is_project_summary
    ):
        raise DepartmentChatError(
            "non-parent department summaries must be explicit project summaries"
        )
    return DepartmentChatSummary(
        summary_id=summary_id,
        source_org_node_id=source_node.org_node_id,
        source_thread_id=source_thread_id,
        target_org_node_id=target_node.org_node_id,
        target_thread_id=target_thread_id,
        summary_type=summary_type,
        status=DepartmentChatSummaryStatus.READY,
        body=body,
        manifest_refs=manifest_refs,
        audit_refs=audit_refs,
        created_at=created_at,
        is_project_summary=is_project_summary,
    )


def plan_final_department_chat_archive_summary(
    *,
    summary_id: str,
    source_node: OrgNode,
    source_thread_id: str,
    target_node: OrgNode,
    target_thread_id: str,
    close_reason: str,
    replacement_thread_id: str | None = None,
    audit_refs: tuple[str, ...] = (),
    created_at: str | None = None,
) -> DepartmentChatSummary:
    """Create the final summary emitted when a department chat closes."""
    _string_value(close_reason, "close_reason")
    replacement_text = (
        f" Replacement thread: {replacement_thread_id}."
        if replacement_thread_id
        else ""
    )
    return plan_department_chat_summary(
        summary_id=summary_id,
        source_node=source_node,
        source_thread_id=source_thread_id,
        target_node=target_node,
        target_thread_id=target_thread_id,
        summary_type=DepartmentChatSummaryType.FINAL_ARCHIVE,
        body=f"Closed department chat. Reason: {close_reason}.{replacement_text}",
        audit_refs=audit_refs,
        created_at=created_at,
    )


def department_chat_summary_to_dict(summary: DepartmentChatSummary) -> dict[str, Any]:
    """Dump a summary without raw transcript or private worker context."""
    return {
        "summary_id": summary.summary_id,
        "schema_version": summary.schema_version,
        "source_org_node_id": summary.source_org_node_id,
        "source_thread_id": summary.source_thread_id,
        "target_org_node_id": summary.target_org_node_id,
        "target_thread_id": summary.target_thread_id,
        "summary_type": summary.summary_type.value,
        "status": summary.status.value,
        "body": summary.body,
        "manifest_refs": list(summary.manifest_refs),
        "audit_refs": list(summary.audit_refs),
        "created_at": summary.created_at,
        "is_project_summary": summary.is_project_summary,
    }


def chat_participant_from_dict(data: Mapping[str, Any]) -> ChatParticipantRef:
    data = _require_mapping(data, "required_participant")
    _reject_unknown_fields(data, _PARTICIPANT_FIELDS, "required_participant")
    return ChatParticipantRef(
        kind=ChatParticipantKind(
            _require_string(data.get("kind"), "participant.kind")
        ),
        participant_id=_require_string(data.get("participant_id"), "participant_id"),
    )


def chat_participant_to_dict(participant: ChatParticipantRef) -> dict[str, Any]:
    return {
        "kind": participant.kind.value,
        "participant_id": participant.participant_id,
    }


def _validate_required_participants(
    participants: tuple[ChatParticipantRef, ...]
) -> None:
    if len(set(participants)) != len(participants):
        raise DepartmentChatError("required_participants must be unique")
    user_count = sum(
        1 for participant in participants if participant.kind == ChatParticipantKind.USER
    )
    main_count = sum(
        1
        for participant in participants
        if participant.kind == ChatParticipantKind.MAIN_AGENT
    )
    if user_count != 1:
        raise DepartmentChatError("department chats require exactly one user")
    if main_count != 1:
        raise DepartmentChatError("department chats require the main agent")
    unsupported = [
        participant.kind.value
        for participant in participants
        if participant.kind
        not in {ChatParticipantKind.USER, ChatParticipantKind.MAIN_AGENT}
    ]
    if unsupported:
        raise DepartmentChatError(
            "required_participants may only include user and main_agent"
        )


def _binding_type(value: DepartmentChatBindingType | str) -> DepartmentChatBindingType:
    if isinstance(value, DepartmentChatBindingType):
        return value
    raw = _require_string(value, "binding_type")
    try:
        return DepartmentChatBindingType(raw)
    except ValueError as exc:
        raise DepartmentChatError(f"Unknown department chat binding type: {raw!r}") from exc


def _binding_state(value: DepartmentChatBindingState | str) -> DepartmentChatBindingState:
    if isinstance(value, DepartmentChatBindingState):
        return value
    raw = _require_string(value, "state")
    try:
        return DepartmentChatBindingState(raw)
    except ValueError as exc:
        raise DepartmentChatError(f"Unknown department chat binding state: {raw!r}") from exc


def _summary_type(value: DepartmentChatSummaryType | str) -> DepartmentChatSummaryType:
    if isinstance(value, DepartmentChatSummaryType):
        return value
    raw = _require_string(value, "summary_type")
    try:
        return DepartmentChatSummaryType(raw)
    except ValueError as exc:
        raise DepartmentChatError(f"Unknown department chat summary type: {raw!r}") from exc


def _summary_status(
    value: DepartmentChatSummaryStatus | str,
) -> DepartmentChatSummaryStatus:
    if isinstance(value, DepartmentChatSummaryStatus):
        return value
    raw = _require_string(value, "status")
    try:
        return DepartmentChatSummaryStatus(raw)
    except ValueError as exc:
        raise DepartmentChatError(f"Unknown department chat summary status: {raw!r}") from exc


def _sync_action(
    value: DepartmentChatMemberSyncAction | str,
) -> DepartmentChatMemberSyncAction:
    if isinstance(value, DepartmentChatMemberSyncAction):
        return value
    raw = _require_string(value, "action")
    try:
        return DepartmentChatMemberSyncAction(raw)
    except ValueError as exc:
        raise DepartmentChatError(f"Unknown department chat sync action: {raw!r}") from exc


def _plan_status(value: DepartmentChatPlanStatus | str) -> DepartmentChatPlanStatus:
    if isinstance(value, DepartmentChatPlanStatus):
        return value
    raw = _require_string(value, "status")
    try:
        return DepartmentChatPlanStatus(raw)
    except ValueError as exc:
        raise DepartmentChatError(f"Unknown department chat plan status: {raw!r}") from exc


def _fallback_kind(value: DepartmentChatFallbackKind | str) -> DepartmentChatFallbackKind:
    if isinstance(value, DepartmentChatFallbackKind):
        return value
    raw = _require_string(value, "fallback_kind")
    try:
        return DepartmentChatFallbackKind(raw)
    except ValueError as exc:
        raise DepartmentChatError(f"Unknown department chat fallback kind: {raw!r}") from exc


def _default_binding_type_for_node(org_node: OrgNode) -> DepartmentChatBindingType:
    if org_node.node_type == OrgNodeType.DEPARTMENT:
        return DepartmentChatBindingType.DEPARTMENT_DEFAULT
    if org_node.node_type == OrgNodeType.TEAM:
        return DepartmentChatBindingType.TEAM_DEFAULT
    raise DepartmentChatError("default chat bindings require a department or team node")


def _worker_status_value(worker_record: Any) -> str | None:
    if isinstance(worker_record, WorkerLifecycleStatus):
        return worker_record.value
    if isinstance(worker_record, str):
        return worker_record or None
    status = getattr(worker_record, "status", None)
    if isinstance(status, WorkerLifecycleStatus):
        return status.value
    if isinstance(status, str):
        return status
    if isinstance(worker_record, Mapping):
        raw_status = worker_record.get("status")
        if isinstance(raw_status, WorkerLifecycleStatus):
            return raw_status.value
        if isinstance(raw_status, str):
            return raw_status
    return None


def _validate_binding_id(value: str, field_name: str) -> str:
    try:
        return validate_single_path_segment(value, field_name)
    except ValueError as exc:
        raise DepartmentChatError(str(exc)) from exc


def _validate_org_id(value: str, field_name: str) -> str:
    try:
        return validate_org_node_id(value)
    except OrganizationError as exc:
        raise DepartmentChatError(f"{field_name} is invalid: {exc}") from exc


def _validate_worker(value: str, field_name: str) -> str:
    try:
        return validate_worker_id(value)
    except WorkerProfileError as exc:
        raise DepartmentChatError(f"{field_name} is invalid: {exc}") from exc


def _unique_workers(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    result = tuple(values)
    for value in result:
        _validate_worker(value, field_name)
    if len(set(result)) != len(result):
        raise DepartmentChatError(f"{field_name} must not contain duplicates")
    return result


def _unique_org_ids(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    result = tuple(values)
    for value in result:
        _validate_org_id(value, field_name)
    if len(set(result)) != len(result):
        raise DepartmentChatError(f"{field_name} must not contain duplicates")
    return result


def _safe_ref_tuple(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise DepartmentChatError(f"{field_name} must be a list of strings")
    result = tuple(values)
    for value in result:
        _validate_binding_id(value, field_name)
    if len(set(result)) != len(result):
        raise DepartmentChatError(f"{field_name} must not contain duplicates")
    return result


_FORBIDDEN_SUMMARY_MARKERS = (
    "raw_transcript",
    "private_memory",
    "credentials",
    "environment",
    "external_agent_raw_output",
)


def _validate_low_sensitivity_body(value: str) -> None:
    _string_value(value, "body")
    lowered = value.lower()
    for marker in _FORBIDDEN_SUMMARY_MARKERS:
        if marker in lowered:
            raise DepartmentChatError(
                f"department chat summaries must not contain {marker}"
            )


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DepartmentChatError(f"{field_name} must be an object")
    return value


def _require_list(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise DepartmentChatError(f"{field_name} must be a list")
    return value


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise DepartmentChatError(f"{field_name} must be a string")
    return value


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, field_name)


def _string_value(value: Any, field_name: str) -> str:
    return _require_string(value, field_name)


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise DepartmentChatError(f"{field_name} must be a list of strings")
    result = tuple(value)
    if any(not isinstance(item, str) or not item for item in result):
        raise DepartmentChatError(f"{field_name} must be a list of non-empty strings")
    return result


def _non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DepartmentChatError(f"{field_name} must be a non-negative integer")
    return value


def _reject_unknown_fields(
    data: Mapping[str, Any], allowed_fields: set[str], field_name: str
) -> None:
    unknown_fields = sorted(set(data) - allowed_fields)
    if unknown_fields:
        joined = ", ".join(unknown_fields)
        raise DepartmentChatError(f"{field_name} has unknown fields: {joined}")

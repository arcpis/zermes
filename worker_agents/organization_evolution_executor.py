"""Controlled executor boundary for approved organization evolution proposals."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping

from utils import atomic_json_write

from .organization import validate_org_node_id
from .organization import (
    OrgLifecycleState,
    OrgNode,
    OrgTree,
)
from .organization_evolution import (
    EvolutionProposalStatus,
    OrganizationEvolutionError,
    OrganizationEvolutionProposal,
    classify_evolution_risks,
    resolve_approval_requirement,
    validate_evolution_proposal,
)
from .profile import validate_worker_id
from .registry import (
    WorkerLifecycleStatus,
    WorkerRegistryRecord,
    WorkerRegistryStore,
    archive_worker_record,
    delete_worker_record,
    transition_worker_status,
)
from .storage.organization_store import OrganizationStore
from .storage.paths import get_worker_agents_organization_dir
from .storage.safe_paths import validate_single_path_segment


EVOLUTION_EXECUTION_SCHEMA_VERSION = 1


class EvolutionExecutionStatus(StrEnum):
    """Lifecycle for one approved organization evolution execution."""

    PENDING = "pending"
    RUNNING = "running"
    BLOCKED = "blocked"
    FAILED = "failed"
    COMPLETED = "completed"
    REQUIRES_MANUAL_RECOVERY = "requires_manual_recovery"


class EvolutionExecutionStep(StrEnum):
    """Explicit executor steps that may write durable organization state."""

    REGISTRY_PRECHECK = "registry_precheck"
    REGISTRY_LIFECYCLE_UPDATE = "registry_lifecycle_update"
    ORGANIZATION_TREE_UPDATE = "organization_tree_update"
    CHAT_BINDING_UPDATE = "chat_binding_update"
    ASSET_DISPOSITION_UPDATE = "asset_disposition_update"
    AUDIT_WRITE = "audit_write"


class ControlledEvolutionOperation(StrEnum):
    """Organization evolution operations supported by the controlled executor."""

    CREATE_CHILD_AGENT = "create_child_agent"
    DELETE_CHILD_AGENT = "delete_child_agent"
    MERGE_DEPARTMENT = "merge_department"
    ARCHIVE_ORG_NODE = "archive_org_node"


@dataclass(frozen=True)
class EvolutionExecutionState:
    """Auditable state for a recoverable organization evolution execution."""

    execution_id: str
    proposal_id: str
    status: EvolutionExecutionStatus | str
    actor: str
    started_at: str
    updated_at: str
    locked_org_node_ids: tuple[str, ...]
    locked_worker_ids: tuple[str, ...]
    completed_steps: tuple[EvolutionExecutionStep, ...] = ()
    failed_step: EvolutionExecutionStep | str | None = None
    failure_reason: str | None = None
    manual_recovery_hint: str = ""
    schema_version: int = EVOLUTION_EXECUTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_schema_version(self.schema_version)
        _safe_id(self.execution_id, "execution id")
        _safe_id(self.proposal_id, "proposal id")
        object.__setattr__(self, "status", _execution_status(self.status))
        _require_string(self.actor, "actor")
        _require_string(self.started_at, "started_at")
        _require_string(self.updated_at, "updated_at")
        object.__setattr__(
            self,
            "locked_org_node_ids",
            _unique_org_node_ids(self.locked_org_node_ids, "locked_org_node_ids"),
        )
        object.__setattr__(
            self,
            "locked_worker_ids",
            _unique_worker_ids(self.locked_worker_ids, "locked_worker_ids"),
        )
        object.__setattr__(
            self,
            "completed_steps",
            tuple(_execution_step(step) for step in self.completed_steps),
        )
        if self.failed_step is not None:
            object.__setattr__(self, "failed_step", _execution_step(self.failed_step))
        if self.failure_reason is not None:
            _require_string(self.failure_reason, "failure_reason")
        if not isinstance(self.manual_recovery_hint, str):
            raise OrganizationEvolutionError("manual_recovery_hint must be a string")


@dataclass(frozen=True)
class ControlledEvolutionPlan:
    """Minimal bounded write plan derived from one approved proposal.

    The executor accepts this structured plan instead of a generic tree patch so
    every write can be checked against the proposal's declared scope.
    """

    proposal: OrganizationEvolutionProposal
    operation: ControlledEvolutionOperation | str
    expected_tree_revision: int
    org_nodes_to_write: tuple[OrgNode, ...] = ()
    org_node_ids_to_remove: tuple[str, ...] = ()
    registry_records_to_create: tuple[WorkerRegistryRecord, ...] = ()
    worker_lifecycle_updates: Mapping[str, WorkerLifecycleStatus | str] = field(
        default_factory=dict
    )
    chat_binding_updates: Mapping[str, str] = field(default_factory=dict)
    asset_disposition_markers: Mapping[str, str] = field(default_factory=dict)
    merge_source_node_ids: tuple[str, ...] = ()
    merge_target_node_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.proposal, OrganizationEvolutionProposal):
            raise OrganizationEvolutionError(
                "proposal must be an OrganizationEvolutionProposal"
            )
        object.__setattr__(self, "operation", _controlled_operation(self.operation))
        _non_negative_int(self.expected_tree_revision, "expected_tree_revision")
        object.__setattr__(self, "org_nodes_to_write", tuple(self.org_nodes_to_write))
        if any(not isinstance(node, OrgNode) for node in self.org_nodes_to_write):
            raise OrganizationEvolutionError("org_nodes_to_write must contain OrgNode")
        object.__setattr__(
            self,
            "org_node_ids_to_remove",
            _unique_org_node_ids(self.org_node_ids_to_remove, "org_node_ids_to_remove"),
        )
        object.__setattr__(
            self,
            "registry_records_to_create",
            tuple(self.registry_records_to_create),
        )
        if any(
            not isinstance(record, WorkerRegistryRecord)
            for record in self.registry_records_to_create
        ):
            raise OrganizationEvolutionError(
                "registry_records_to_create must contain WorkerRegistryRecord"
            )
        lifecycle_updates = {
            validate_worker_id(worker_id): _worker_lifecycle_status(status)
            for worker_id, status in self.worker_lifecycle_updates.items()
        }
        object.__setattr__(self, "worker_lifecycle_updates", lifecycle_updates)
        object.__setattr__(
            self,
            "chat_binding_updates",
            {
                validate_org_node_id(node_id): _require_string(status, "chat status")
                for node_id, status in self.chat_binding_updates.items()
            },
        )
        object.__setattr__(
            self,
            "asset_disposition_markers",
            {
                validate_org_node_id(node_id): _require_string(marker, "asset marker")
                for node_id, marker in self.asset_disposition_markers.items()
            },
        )
        object.__setattr__(
            self,
            "merge_source_node_ids",
            _unique_org_node_ids(self.merge_source_node_ids, "merge_source_node_ids"),
        )
        if self.merge_target_node_id is not None:
            object.__setattr__(
                self,
                "merge_target_node_id",
                validate_org_node_id(self.merge_target_node_id),
            )
        _validate_plan_scope(self)


@dataclass
class EvolutionExecutionStore:
    """Profile-home execution state and lock storage."""

    root: Path = field(default_factory=get_worker_agents_organization_dir)

    @property
    def executions_dir(self) -> Path:
        return self.root / "executions"

    @property
    def lock_path(self) -> Path:
        return self.root / "execution-locks.json"

    @property
    def chat_binding_status_path(self) -> Path:
        return self.root / "chat-binding-status.json"

    @property
    def asset_disposition_marker_path(self) -> Path:
        return self.root / "asset-disposition-markers.json"

    def initialize(self) -> Path:
        self.executions_dir.mkdir(parents=True, exist_ok=True)
        return self.root

    def execution_path(self, execution_id: str) -> Path:
        safe_id = _safe_id(execution_id, "execution id")
        return self.executions_dir / f"{safe_id}.json"

    def save_state(self, state: EvolutionExecutionState) -> Path:
        self.initialize()
        path = self.execution_path(state.execution_id)
        atomic_json_write(path, evolution_execution_state_to_dict(state))
        return path

    def load_state(self, execution_id: str) -> EvolutionExecutionState:
        path = self.execution_path(execution_id)
        if not path.exists():
            raise OrganizationEvolutionError(
                f"Evolution execution does not exist: {execution_id!r}"
            )
        return evolution_execution_state_from_dict(_load_json_object(path, "execution"))

    def load_locks(self) -> dict[str, EvolutionExecutionState]:
        if not self.lock_path.exists():
            return {}
        data = _load_json_object(self.lock_path, "execution locks")
        raw_locks = _require_mapping(data.get("locks", {}), "locks")
        return {
            _safe_id(execution_id, "execution id"): evolution_execution_state_from_dict(
                _require_mapping(value, "execution lock")
            )
            for execution_id, value in raw_locks.items()
        }

    def save_locks(self, locks: Mapping[str, EvolutionExecutionState]) -> None:
        self.initialize()
        atomic_json_write(
            self.lock_path,
            {
                "schema_version": EVOLUTION_EXECUTION_SCHEMA_VERSION,
                "locks": {
                    execution_id: evolution_execution_state_to_dict(state)
                    for execution_id, state in sorted(locks.items())
                },
            },
        )

    def acquire_lock(self, state: EvolutionExecutionState) -> None:
        locks = self.load_locks()
        _reject_lock_conflict(state, locks.values())
        locks[state.execution_id] = state
        self.save_locks(locks)

    def save_chat_binding_statuses(self, statuses: Mapping[str, str]) -> None:
        self.initialize()
        atomic_json_write(
            self.chat_binding_status_path,
            {"schema_version": EVOLUTION_EXECUTION_SCHEMA_VERSION, "statuses": dict(statuses)},
        )

    def load_chat_binding_statuses(self) -> dict[str, str]:
        if not self.chat_binding_status_path.exists():
            return {}
        data = _load_json_object(self.chat_binding_status_path, "chat binding statuses")
        statuses = _require_mapping(data.get("statuses", {}), "statuses")
        return {
            validate_org_node_id(node_id): _require_string(status, "chat status")
            for node_id, status in statuses.items()
        }

    def save_asset_disposition_markers(self, markers: Mapping[str, str]) -> None:
        self.initialize()
        atomic_json_write(
            self.asset_disposition_marker_path,
            {"schema_version": EVOLUTION_EXECUTION_SCHEMA_VERSION, "markers": dict(markers)},
        )

    def load_asset_disposition_markers(self) -> dict[str, str]:
        if not self.asset_disposition_marker_path.exists():
            return {}
        data = _load_json_object(
            self.asset_disposition_marker_path, "asset disposition markers"
        )
        markers = _require_mapping(data.get("markers", {}), "markers")
        return {
            validate_org_node_id(node_id): _require_string(marker, "asset marker")
            for node_id, marker in markers.items()
        }


def begin_evolution_execution(
    proposal: OrganizationEvolutionProposal | Mapping[str, Any],
    *,
    actor: str,
    now: str,
    store: EvolutionExecutionStore | None = None,
    execution_id: str | None = None,
    plan_expires_at: str | None = None,
) -> EvolutionExecutionState:
    """Validate an approved proposal and create a running execution lock."""

    validated = validate_evolution_proposal(proposal)
    _require_executable_proposal(validated, now=now, plan_expires_at=plan_expires_at)
    state = EvolutionExecutionState(
        execution_id=execution_id or f"execution_{uuid.uuid4().hex}",
        proposal_id=validated.proposal_id,
        status=EvolutionExecutionStatus.RUNNING,
        actor=actor,
        started_at=now,
        updated_at=now,
        locked_org_node_ids=validated.target_node_ids,
        locked_worker_ids=validated.affected_worker_ids,
    )
    execution_store = store or EvolutionExecutionStore()
    execution_store.acquire_lock(state)
    execution_store.save_state(state)
    return state


def apply_approved_evolution_plan(
    plan: ControlledEvolutionPlan,
    *,
    state: EvolutionExecutionState,
    actor: str,
    now: str,
    organization_store: OrganizationStore,
    registry_store: WorkerRegistryStore,
    execution_store: EvolutionExecutionStore,
) -> EvolutionExecutionState:
    """Apply one approved plan through bounded registry and tree writes."""

    if plan.proposal.status is not EvolutionProposalStatus.APPROVED:
        raise OrganizationEvolutionError("evolution proposal must be approved")
    if state.status is not EvolutionExecutionStatus.RUNNING:
        raise OrganizationEvolutionError("evolution execution must be running")
    if state.proposal_id != plan.proposal.proposal_id:
        raise OrganizationEvolutionError("execution state proposal mismatch")
    if not set(plan.proposal.target_node_ids) <= set(state.locked_org_node_ids):
        raise OrganizationEvolutionError("execution state does not lock target nodes")
    if not set(plan.proposal.affected_worker_ids) <= set(state.locked_worker_ids):
        raise OrganizationEvolutionError("execution state does not lock affected workers")

    updated_state = state
    try:
        tree = organization_store.load_active_organization()
        if tree is None:
            raise OrganizationEvolutionError("active organization tree is required")
        if tree.revision != plan.expected_tree_revision:
            raise OrganizationEvolutionError("active organization revision mismatch")

        records = registry_store.load_records()
        _validate_registry_precheck(plan, records)
        updated_state = _complete_and_save(
            updated_state,
            EvolutionExecutionStep.REGISTRY_PRECHECK,
            now=now,
            store=execution_store,
        )

        records = _apply_registry_updates(plan, records, actor=actor)
        registry_store.save_records(records)
        updated_state = _complete_and_save(
            updated_state,
            EvolutionExecutionStep.REGISTRY_LIFECYCLE_UPDATE,
            now=now,
            store=execution_store,
        )

        updated_tree = _apply_tree_updates(plan, tree)
        organization_store.save_active_organization(
            updated_tree, expected_revision=tree.revision
        )
        updated_state = _complete_and_save(
            updated_state,
            EvolutionExecutionStep.ORGANIZATION_TREE_UPDATE,
            now=now,
            store=execution_store,
        )

        chat_statuses = execution_store.load_chat_binding_statuses()
        chat_statuses.update(plan.chat_binding_updates)
        execution_store.save_chat_binding_statuses(chat_statuses)
        updated_state = _complete_and_save(
            updated_state,
            EvolutionExecutionStep.CHAT_BINDING_UPDATE,
            now=now,
            store=execution_store,
        )

        asset_markers = execution_store.load_asset_disposition_markers()
        asset_markers.update(plan.asset_disposition_markers)
        execution_store.save_asset_disposition_markers(asset_markers)
        updated_state = _complete_and_save(
            updated_state,
            EvolutionExecutionStep.ASSET_DISPOSITION_UPDATE,
            now=now,
            store=execution_store,
        )
        return updated_state
    except Exception as exc:
        failed_state = mark_execution_failed(
            updated_state,
            _next_unfinished_write_step(updated_state),
            reason=str(exc),
            manual_recovery_hint=(
                "Review completed_steps, active organization tree, registry, "
                "chat status markers, and asset disposition markers before retrying."
            ),
            updated_at=now,
        )
        execution_store.save_state(failed_state)
        if isinstance(exc, OrganizationEvolutionError):
            raise
        raise OrganizationEvolutionError(str(exc)) from exc


def mark_execution_step_completed(
    state: EvolutionExecutionState,
    step: EvolutionExecutionStep | str,
    *,
    updated_at: str,
) -> EvolutionExecutionState:
    """Return state with one completed step recorded once."""

    completed_step = _execution_step(step)
    completed_steps = state.completed_steps
    if completed_step not in completed_steps:
        completed_steps = (*completed_steps, completed_step)
    return replace(state, completed_steps=completed_steps, updated_at=updated_at)


def mark_execution_failed(
    state: EvolutionExecutionState,
    step: EvolutionExecutionStep | str,
    *,
    reason: str,
    manual_recovery_hint: str,
    updated_at: str,
) -> EvolutionExecutionState:
    """Return state for a failed execution that requires human recovery."""

    return replace(
        state,
        status=EvolutionExecutionStatus.REQUIRES_MANUAL_RECOVERY,
        failed_step=_execution_step(step),
        failure_reason=_require_string(reason, "reason"),
        manual_recovery_hint=_require_string(
            manual_recovery_hint, "manual_recovery_hint"
        ),
        updated_at=updated_at,
    )


_EXECUTION_STATE_FIELDS = {
    "schema_version",
    "execution_id",
    "proposal_id",
    "status",
    "actor",
    "started_at",
    "updated_at",
    "locked_org_node_ids",
    "locked_worker_ids",
    "completed_steps",
    "failed_step",
    "failure_reason",
    "manual_recovery_hint",
}


def evolution_execution_state_to_dict(
    state: EvolutionExecutionState,
) -> dict[str, Any]:
    return {
        "schema_version": state.schema_version,
        "execution_id": state.execution_id,
        "proposal_id": state.proposal_id,
        "status": state.status.value,
        "actor": state.actor,
        "started_at": state.started_at,
        "updated_at": state.updated_at,
        "locked_org_node_ids": list(state.locked_org_node_ids),
        "locked_worker_ids": list(state.locked_worker_ids),
        "completed_steps": [step.value for step in state.completed_steps],
        "failed_step": state.failed_step.value if state.failed_step else None,
        "failure_reason": state.failure_reason,
        "manual_recovery_hint": state.manual_recovery_hint,
    }


def evolution_execution_state_from_dict(
    data: Mapping[str, Any],
) -> EvolutionExecutionState:
    data = _require_mapping(data, "evolution execution state")
    _reject_unknown_fields(data, _EXECUTION_STATE_FIELDS, "evolution execution state")
    return EvolutionExecutionState(
        schema_version=data.get(
            "schema_version", EVOLUTION_EXECUTION_SCHEMA_VERSION
        ),
        execution_id=_require_string(data.get("execution_id"), "execution_id"),
        proposal_id=_require_string(data.get("proposal_id"), "proposal_id"),
        status=_require_string(data.get("status"), "status"),
        actor=_require_string(data.get("actor"), "actor"),
        started_at=_require_string(data.get("started_at"), "started_at"),
        updated_at=_require_string(data.get("updated_at"), "updated_at"),
        locked_org_node_ids=_string_tuple(
            data.get("locked_org_node_ids", ()), "locked_org_node_ids"
        ),
        locked_worker_ids=_string_tuple(
            data.get("locked_worker_ids", ()), "locked_worker_ids"
        ),
        completed_steps=_string_tuple(
            data.get("completed_steps", ()), "completed_steps"
        ),
        failed_step=_optional_string(data.get("failed_step"), "failed_step"),
        failure_reason=_optional_string(data.get("failure_reason"), "failure_reason"),
        manual_recovery_hint=_string_value(
            data.get("manual_recovery_hint", ""), "manual_recovery_hint"
        ),
    )


def _require_executable_proposal(
    proposal: OrganizationEvolutionProposal,
    *,
    now: str,
    plan_expires_at: str | None,
) -> None:
    if proposal.status is not EvolutionProposalStatus.APPROVED:
        raise OrganizationEvolutionError("evolution proposal must be approved")
    if plan_expires_at is not None and now > plan_expires_at:
        raise OrganizationEvolutionError("evolution proposal plan has expired")
    requirement = resolve_approval_requirement(
        proposal,
        classify_evolution_risks(proposal),
    )
    if requirement.blocking_flags:
        flags = ", ".join(flag.value for flag in requirement.blocking_flags)
        raise OrganizationEvolutionError(
            f"evolution proposal has unresolved blocking flags: {flags}"
        )


def _reject_lock_conflict(
    state: EvolutionExecutionState,
    active_states: Any,
) -> None:
    wanted_nodes = set(state.locked_org_node_ids)
    wanted_workers = set(state.locked_worker_ids)
    for existing in active_states:
        if existing.status is not EvolutionExecutionStatus.RUNNING:
            continue
        if existing.proposal_id == state.proposal_id:
            raise OrganizationEvolutionError("evolution proposal is already running")
        if wanted_nodes & set(existing.locked_org_node_ids):
            raise OrganizationEvolutionError("organization node is already locked")
        if wanted_workers & set(existing.locked_worker_ids):
            raise OrganizationEvolutionError("worker is already locked")


def _validate_plan_scope(plan: ControlledEvolutionPlan) -> None:
    target_node_ids = set(plan.proposal.target_node_ids)
    written_node_ids = {node.org_node_id for node in plan.org_nodes_to_write}
    scoped_node_ids = (
        written_node_ids
        | set(plan.org_node_ids_to_remove)
        | set(plan.chat_binding_updates)
        | set(plan.asset_disposition_markers)
        | set(plan.merge_source_node_ids)
    )
    if plan.merge_target_node_id is not None:
        scoped_node_ids.add(plan.merge_target_node_id)
    if not scoped_node_ids <= target_node_ids:
        raise OrganizationEvolutionError(
            "controlled plan modifies nodes outside proposal scope"
        )

    affected_worker_ids = set(plan.proposal.affected_worker_ids)
    worker_ids = {record.worker_id for record in plan.registry_records_to_create}
    worker_ids |= set(plan.worker_lifecycle_updates)
    if not worker_ids <= affected_worker_ids:
        raise OrganizationEvolutionError(
            "controlled plan modifies workers outside proposal scope"
        )


def _validate_registry_precheck(
    plan: ControlledEvolutionPlan,
    records: Mapping[str, WorkerRegistryRecord],
) -> None:
    for record in plan.registry_records_to_create:
        if record.worker_id in records:
            raise OrganizationEvolutionError(
                f"worker registry record already exists: {record.worker_id!r}"
            )
    for worker_id in plan.worker_lifecycle_updates:
        if worker_id not in records:
            raise OrganizationEvolutionError(
                f"worker registry record is missing: {worker_id!r}"
            )


def _apply_registry_updates(
    plan: ControlledEvolutionPlan,
    records: Mapping[str, WorkerRegistryRecord],
    *,
    actor: str,
) -> dict[str, WorkerRegistryRecord]:
    updated = dict(records)
    for record in plan.registry_records_to_create:
        updated[record.worker_id] = record
    for worker_id, status in plan.worker_lifecycle_updates.items():
        current = updated[worker_id]
        if status is WorkerLifecycleStatus.ARCHIVED:
            updated[worker_id] = archive_worker_record(
                current,
                updated_by=actor,
                status_reason=f"{plan.operation.value} execution",
            )
        elif status is WorkerLifecycleStatus.DELETED:
            updated[worker_id] = delete_worker_record(
                current,
                updated_by=actor,
                status_reason=f"{plan.operation.value} execution",
            )
        else:
            updated[worker_id] = transition_worker_status(
                current,
                status,
                updated_by=actor,
                status_reason=f"{plan.operation.value} execution",
            )
    return updated


def _apply_tree_updates(plan: ControlledEvolutionPlan, tree: OrgTree) -> OrgTree:
    nodes = dict(tree.nodes)
    if plan.operation is ControlledEvolutionOperation.MERGE_DEPARTMENT:
        _apply_merge_tree_updates(plan, nodes)
    for node_id in plan.org_node_ids_to_remove:
        _remove_node_from_tree(node_id, nodes)
    for node in plan.org_nodes_to_write:
        _write_node_to_tree(node, nodes)
    updated_tree = replace(
        tree,
        nodes=nodes,
        revision=tree.revision + 1,
    )
    return updated_tree


def _apply_merge_tree_updates(
    plan: ControlledEvolutionPlan,
    nodes: dict[str, OrgNode],
) -> None:
    if not plan.merge_source_node_ids or plan.merge_target_node_id is None:
        raise OrganizationEvolutionError(
            "merge execution requires source and target nodes"
        )
    if plan.merge_target_node_id not in nodes:
        raise OrganizationEvolutionError("merge target node is missing")
    target = nodes[plan.merge_target_node_id]
    migrated_children = list(target.child_ids)
    migrated_members = list(target.member_worker_ids)
    for source_id in plan.merge_source_node_ids:
        source = nodes.get(source_id)
        if source is None:
            raise OrganizationEvolutionError("merge source node is missing")
        for child_id in source.child_ids:
            child = nodes[child_id]
            nodes[child_id] = replace(child, parent_id=plan.merge_target_node_id)
            if child_id not in migrated_children:
                migrated_children.append(child_id)
        for worker_id in source.member_worker_ids:
            if worker_id not in migrated_members:
                migrated_members.append(worker_id)
        nodes[source_id] = replace(
            source,
            child_ids=(),
            member_worker_ids=(),
            lifecycle=OrgLifecycleState.ARCHIVED,
        )
    nodes[plan.merge_target_node_id] = replace(
        target,
        child_ids=tuple(migrated_children),
        member_worker_ids=tuple(migrated_members),
    )


def _remove_node_from_tree(node_id: str, nodes: dict[str, OrgNode]) -> None:
    node = nodes.get(node_id)
    if node is None:
        raise OrganizationEvolutionError(f"organization node is missing: {node_id!r}")
    if node.child_ids:
        raise OrganizationEvolutionError("cannot remove organization node with children")
    if node.parent_id is not None and node.parent_id in nodes:
        parent = nodes[node.parent_id]
        nodes[node.parent_id] = replace(
            parent,
            child_ids=tuple(
                child_id for child_id in parent.child_ids if child_id != node_id
            ),
        )
    del nodes[node_id]


def _write_node_to_tree(node: OrgNode, nodes: dict[str, OrgNode]) -> None:
    if node.parent_id is not None and node.parent_id not in nodes:
        raise OrganizationEvolutionError("organization node parent is missing")
    existing = nodes.get(node.org_node_id)
    nodes[node.org_node_id] = node
    if node.parent_id is not None:
        parent = nodes[node.parent_id]
        child_ids = list(parent.child_ids)
        if node.org_node_id not in child_ids:
            child_ids.append(node.org_node_id)
            nodes[node.parent_id] = replace(parent, child_ids=tuple(child_ids))
    if existing is not None and existing.parent_id and existing.parent_id != node.parent_id:
        old_parent = nodes.get(existing.parent_id)
        if old_parent is not None:
            nodes[existing.parent_id] = replace(
                old_parent,
                child_ids=tuple(
                    child_id
                    for child_id in old_parent.child_ids
                    if child_id != node.org_node_id
                ),
            )


def _complete_and_save(
    state: EvolutionExecutionState,
    step: EvolutionExecutionStep,
    *,
    now: str,
    store: EvolutionExecutionStore,
) -> EvolutionExecutionState:
    updated_state = mark_execution_step_completed(state, step, updated_at=now)
    store.save_state(updated_state)
    return updated_state


def _next_unfinished_write_step(
    state: EvolutionExecutionState,
) -> EvolutionExecutionStep:
    for step in (
        EvolutionExecutionStep.REGISTRY_PRECHECK,
        EvolutionExecutionStep.REGISTRY_LIFECYCLE_UPDATE,
        EvolutionExecutionStep.ORGANIZATION_TREE_UPDATE,
        EvolutionExecutionStep.CHAT_BINDING_UPDATE,
        EvolutionExecutionStep.ASSET_DISPOSITION_UPDATE,
    ):
        if step not in state.completed_steps:
            return step
    return EvolutionExecutionStep.ASSET_DISPOSITION_UPDATE


def _load_json_object(path: Path, record_name: str) -> Mapping[str, Any]:
    import json

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise OrganizationEvolutionError(
            f"Invalid {record_name} JSON: {exc.msg}"
        ) from exc
    return _require_mapping(data, record_name)


def _execution_status(
    value: EvolutionExecutionStatus | str,
) -> EvolutionExecutionStatus:
    try:
        return (
            value
            if isinstance(value, EvolutionExecutionStatus)
            else EvolutionExecutionStatus(value)
        )
    except ValueError as exc:
        raise OrganizationEvolutionError(
            f"Unknown evolution execution status: {value!r}"
        ) from exc


def _execution_step(value: EvolutionExecutionStep | str) -> EvolutionExecutionStep:
    try:
        return (
            value
            if isinstance(value, EvolutionExecutionStep)
            else EvolutionExecutionStep(value)
        )
    except ValueError as exc:
        raise OrganizationEvolutionError(
            f"Unknown evolution execution step: {value!r}"
        ) from exc


def _controlled_operation(
    value: ControlledEvolutionOperation | str,
) -> ControlledEvolutionOperation:
    try:
        return (
            value
            if isinstance(value, ControlledEvolutionOperation)
            else ControlledEvolutionOperation(value)
        )
    except ValueError as exc:
        raise OrganizationEvolutionError(
            f"Unknown controlled evolution operation: {value!r}"
        ) from exc


def _worker_lifecycle_status(
    value: WorkerLifecycleStatus | str,
) -> WorkerLifecycleStatus:
    try:
        return (
            value
            if isinstance(value, WorkerLifecycleStatus)
            else WorkerLifecycleStatus(value)
        )
    except ValueError as exc:
        raise OrganizationEvolutionError(
            f"Unknown worker lifecycle status: {value!r}"
        ) from exc


def _unique_org_node_ids(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    result = _string_tuple(values, field_name)
    for value in result:
        validate_org_node_id(value)
    if len(set(result)) != len(result):
        raise OrganizationEvolutionError(f"{field_name} must not contain duplicates")
    return result


def _unique_worker_ids(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    result = _string_tuple(values, field_name)
    for value in result:
        validate_worker_id(value)
    if len(set(result)) != len(result):
        raise OrganizationEvolutionError(f"{field_name} must not contain duplicates")
    return result


def _safe_id(value: str, field_name: str) -> str:
    try:
        return validate_single_path_segment(value, field_name)
    except ValueError as exc:
        raise OrganizationEvolutionError(str(exc)) from exc


def _validate_schema_version(value: int) -> None:
    if value != EVOLUTION_EXECUTION_SCHEMA_VERSION:
        raise OrganizationEvolutionError(
            f"Unsupported evolution execution schema_version: {value!r}"
        )


def _non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise OrganizationEvolutionError(f"{field_name} must be a non-negative integer")
    return value


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise OrganizationEvolutionError(f"{field_name} must be an object")
    return value


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise OrganizationEvolutionError(f"{field_name} must be a non-empty string")
    return value


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, field_name)


def _string_value(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise OrganizationEvolutionError(f"{field_name} must be a string")
    return value


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise OrganizationEvolutionError(f"{field_name} must be a list of strings")
    result = tuple(value)
    if any(not isinstance(item, str) or not item for item in result):
        raise OrganizationEvolutionError(
            f"{field_name} must be a list of non-empty strings"
        )
    return result


def _reject_unknown_fields(
    data: Mapping[str, Any], allowed_fields: set[str], field_name: str
) -> None:
    unknown_fields = sorted(set(data) - allowed_fields)
    if unknown_fields:
        joined = ", ".join(unknown_fields)
        raise OrganizationEvolutionError(f"{field_name} has unknown fields: {joined}")

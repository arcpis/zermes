"""Controlled executor boundary for approved organization evolution proposals."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping

from utils import atomic_json_write

from .organization import validate_org_node_id
from .organization_evolution import (
    EVOLUTION_PROPOSAL_SCHEMA_VERSION,
    EvolutionProposalStatus,
    OrganizationEvolutionError,
    OrganizationEvolutionProposal,
    classify_evolution_risks,
    resolve_approval_requirement,
    validate_evolution_proposal,
)
from .profile import validate_worker_id
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

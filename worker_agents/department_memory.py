"""Department memory contracts and review-safe storage helpers."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
from enum import StrEnum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping

from utils import atomic_json_write

from .organization import validate_org_node_id
from .private_assets import PrivateAssetProposalInput
from .result_routing import RoutedProposalKind, RoutedProposalRecord
from .storage import get_worker_agents_home


DEPARTMENT_MEMORY_SCHEMA_VERSION = 1

_SENSITIVE_FIELD_NAMES = frozenset(
    {
        "api_key",
        "complete_transcript",
        "cookie",
        "credential",
        "credentials",
        "env",
        "environment",
        "external_raw_log",
        "external_raw_output",
        "full_prompt",
        "full_transcript",
        "private_memory",
        "private_memory_text",
        "raw_output",
        "raw_stderr",
        "raw_stdout",
        "raw_transcript",
        "refresh_token",
        "secret",
        "stderr",
        "stdout",
        "token",
    }
)


class DepartmentMemoryError(ValueError):
    """Raised when department memory crosses a durable asset boundary."""


class DepartmentMemoryKind(StrEnum):
    """Long-lived knowledge categories owned by a department."""

    RESPONSIBILITY = "responsibility"
    DELIVERY_STANDARD = "delivery_standard"
    RETROSPECTIVE = "retrospective"
    RISK = "risk"
    COLLABORATION_NORM = "collaboration_norm"
    PLAYBOOK_NOTE = "playbook_note"


class DepartmentMemoryVisibility(StrEnum):
    """Who may consume a department memory summary."""

    PRIVATE_TO_DEPARTMENT = "private_to_department"
    INHERITABLE_SUMMARY = "inheritable_summary"
    ORGANIZATION_SUMMARY = "organization_summary"


class DepartmentMemorySensitivity(StrEnum):
    """Sensitivity labels used before reading or adopting memory."""

    LOW = "low"
    INTERNAL = "internal"
    RESTRICTED = "restricted"
    USER_CONFIRMATION_REQUIRED = "user_confirmation_required"


class DepartmentMemoryProposalState(StrEnum):
    """Review lifecycle for department memory proposals."""

    PENDING = "pending"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


class DepartmentMemoryProposalCreateStatus(StrEnum):
    """Whether proposal creation wrote a new record or found a duplicate."""

    CREATED = "created"
    EXISTING = "existing"


class DepartmentMemoryReviewerRole(StrEnum):
    """Roles allowed to review department memory proposals."""

    DEPARTMENT_LEAD = "department_lead"
    MAIN_AGENT = "main_agent"
    USER = "user"
    GOVERNANCE_SERVICE = "governance_service"


class DepartmentMemoryReviewDecision(StrEnum):
    """Supported review decisions for a department memory proposal."""

    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_CHANGES = "request_changes"
    EXPIRE = "expire"


@dataclass(frozen=True)
class DepartmentMemoryRecord:
    """Approved department memory; pending proposals use a separate record."""

    department_id: str
    memory_id: str
    kind: DepartmentMemoryKind | str
    summary: str
    source_refs: tuple[str, ...] = ()
    visibility: DepartmentMemoryVisibility | str = (
        DepartmentMemoryVisibility.PRIVATE_TO_DEPARTMENT
    )
    sensitivity: DepartmentMemorySensitivity | str = DepartmentMemorySensitivity.LOW
    revision: int = 1
    active: bool = True
    accepted_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    audit_summary: str = ""
    schema_version: int = DEPARTMENT_MEMORY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        validate_org_node_id(self.department_id)
        _validate_identifier(self.memory_id, "memory_id")
        object.__setattr__(self, "kind", _memory_kind(self.kind))
        _require_string(self.summary, "summary")
        object.__setattr__(
            self, "visibility", _memory_visibility(self.visibility)
        )
        object.__setattr__(
            self, "sensitivity", _memory_sensitivity(self.sensitivity)
        )
        _require_positive_int(self.revision, "revision")
        if not isinstance(self.active, bool):
            raise DepartmentMemoryError("active must be a boolean")
        object.__setattr__(
            self,
            "source_refs",
            tuple(_validate_relative_ref(ref, "source_refs") for ref in self.source_refs),
        )
        for value, field_name in (
            (self.accepted_at, "accepted_at"),
            (self.created_at, "created_at"),
            (self.updated_at, "updated_at"),
        ):
            if value is not None:
                _require_string(value, field_name)
        if not isinstance(self.audit_summary, str):
            raise DepartmentMemoryError("audit_summary must be a string")


@dataclass(frozen=True)
class DepartmentMemoryProposal:
    """Pending department memory candidate; it is not an active memory."""

    proposal_id: str
    department_id: str
    kind: DepartmentMemoryKind | str
    candidate_summary: str
    source_actor: str
    source_refs: tuple[str, ...] = ()
    rationale: str = ""
    source_hash: str | None = None
    visibility: DepartmentMemoryVisibility | str = (
        DepartmentMemoryVisibility.PRIVATE_TO_DEPARTMENT
    )
    sensitivity: DepartmentMemorySensitivity | str = DepartmentMemorySensitivity.INTERNAL
    review_requirement: str = "department_lead_or_main_agent"
    state: DepartmentMemoryProposalState | str = DepartmentMemoryProposalState.PENDING
    created_at: str | None = None
    updated_at: str | None = None
    audit_summary: str = ""
    schema_version: int = DEPARTMENT_MEMORY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        _validate_identifier(self.proposal_id, "proposal_id")
        validate_org_node_id(self.department_id)
        object.__setattr__(self, "kind", _memory_kind(self.kind))
        _require_string(self.candidate_summary, "candidate_summary")
        _require_string(self.source_actor, "source_actor")
        object.__setattr__(
            self, "visibility", _memory_visibility(self.visibility)
        )
        object.__setattr__(
            self, "sensitivity", _memory_sensitivity(self.sensitivity)
        )
        object.__setattr__(self, "state", _proposal_state(self.state))
        object.__setattr__(
            self,
            "source_refs",
            tuple(_validate_relative_ref(ref, "source_refs") for ref in self.source_refs),
        )
        _require_string(self.review_requirement, "review_requirement")
        for value, field_name in (
            (self.rationale, "rationale"),
            (self.audit_summary, "audit_summary"),
        ):
            if not isinstance(value, str):
                raise DepartmentMemoryError(f"{field_name} must be a string")
        for value, field_name in (
            (self.source_hash, "source_hash"),
            (self.created_at, "created_at"),
            (self.updated_at, "updated_at"),
        ):
            if value is not None:
                _require_string(value, field_name)


@dataclass(frozen=True)
class DepartmentMemoryProposalCreateResult:
    """Result of creating a department memory proposal."""

    proposal: DepartmentMemoryProposal
    status: DepartmentMemoryProposalCreateStatus = (
        DepartmentMemoryProposalCreateStatus.CREATED
    )

    def __post_init__(self) -> None:
        if not isinstance(self.proposal, DepartmentMemoryProposal):
            raise DepartmentMemoryError("proposal must be a DepartmentMemoryProposal")
        object.__setattr__(self, "status", _proposal_create_status(self.status))


@dataclass(frozen=True)
class DepartmentMemoryReviewAction:
    """One explicit review decision made by an authorized actor."""

    proposal_id: str
    decision: DepartmentMemoryReviewDecision | str
    actor_id: str
    actor_role: DepartmentMemoryReviewerRole | str
    reason: str
    reviewed_at: str
    user_confirmation_ref: str | None = None
    supersede_memory_id: str | None = None
    audit_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_identifier(self.proposal_id, "proposal_id")
        object.__setattr__(self, "decision", _review_decision(self.decision))
        _require_string(self.actor_id, "actor_id")
        object.__setattr__(self, "actor_role", _reviewer_role(self.actor_role))
        _require_string(self.reason, "reason")
        _require_string(self.reviewed_at, "reviewed_at")
        if self.user_confirmation_ref is not None:
            _validate_relative_ref(self.user_confirmation_ref, "user_confirmation_ref")
        if self.supersede_memory_id is not None:
            _validate_identifier(self.supersede_memory_id, "supersede_memory_id")
        object.__setattr__(
            self,
            "audit_refs",
            tuple(_validate_relative_ref(ref, "audit_refs") for ref in self.audit_refs),
        )


@dataclass
class DepartmentMemoryProposalStore:
    """Profile-home store for pending department memory proposals."""

    root: Path = field(default_factory=get_worker_agents_home)

    def department_memory_root(self, department_id: str) -> Path:
        return department_memory_dir(self.root, department_id)

    def proposals_dir(self, department_id: str) -> Path:
        return self.department_memory_root(department_id) / "proposals"

    def proposal_path(self, department_id: str, proposal_id: str) -> Path:
        _validate_identifier(proposal_id, "proposal_id")
        return self.proposals_dir(department_id) / f"{proposal_id}.json"

    def create_proposal(
        self, proposal: DepartmentMemoryProposal
    ) -> DepartmentMemoryProposalCreateResult:
        """Persist one pending proposal, returning an existing duplicate if found."""

        if proposal.state is not DepartmentMemoryProposalState.PENDING:
            raise DepartmentMemoryError("new department memory proposals must be pending")
        existing = self.find_pending_duplicate(
            department_id=proposal.department_id,
            kind=proposal.kind,
            source_hash=proposal.source_hash,
        )
        if existing is not None:
            return DepartmentMemoryProposalCreateResult(
                existing, DepartmentMemoryProposalCreateStatus.EXISTING
            )
        path = self.proposal_path(proposal.department_id, proposal.proposal_id)
        if path.exists():
            raise DepartmentMemoryError(
                f"Department memory proposal already exists: {proposal.proposal_id!r}"
            )
        atomic_json_write(path, department_memory_proposal_to_dict(proposal))
        return DepartmentMemoryProposalCreateResult(proposal)

    def save_proposal(self, proposal: DepartmentMemoryProposal) -> Path:
        """Overwrite one proposal after state changes made by review services."""

        path = self.proposal_path(proposal.department_id, proposal.proposal_id)
        atomic_json_write(path, department_memory_proposal_to_dict(proposal))
        return path

    def load_proposal(
        self, department_id: str, proposal_id: str
    ) -> DepartmentMemoryProposal:
        path = self.proposal_path(department_id, proposal_id)
        if not path.exists():
            raise DepartmentMemoryError(
                f"Department memory proposal does not exist: {proposal_id!r}"
            )
        return department_memory_proposal_from_dict(_load_json_object(path, "proposal"))

    def list_proposals(
        self,
        department_id: str,
        *,
        state: DepartmentMemoryProposalState | str | None = None,
        kind: DepartmentMemoryKind | str | None = None,
        sensitivity: DepartmentMemorySensitivity | str | None = None,
    ) -> list[DepartmentMemoryProposal]:
        """Return department proposals sorted by creation time and id."""

        directory = self.proposals_dir(department_id)
        if not directory.exists():
            return []
        state_value = _proposal_state(state) if state is not None else None
        kind_value = _memory_kind(kind) if kind is not None else None
        sensitivity_value = (
            _memory_sensitivity(sensitivity) if sensitivity is not None else None
        )
        proposals = [
            department_memory_proposal_from_dict(_load_json_object(path, "proposal"))
            for path in directory.glob("*.json")
        ]
        filtered = [
            proposal
            for proposal in proposals
            if (state_value is None or proposal.state == state_value)
            and (kind_value is None or proposal.kind == kind_value)
            and (sensitivity_value is None or proposal.sensitivity == sensitivity_value)
        ]
        return sorted(
            filtered,
            key=lambda proposal: (
                proposal.created_at or "",
                proposal.proposal_id,
            ),
        )

    def find_pending_duplicate(
        self,
        *,
        department_id: str,
        kind: DepartmentMemoryKind | str,
        source_hash: str | None,
    ) -> DepartmentMemoryProposal | None:
        """Find a pending proposal with the same department, kind, and source hash."""

        if source_hash is None:
            return None
        for proposal in self.list_proposals(
            department_id,
            state=DepartmentMemoryProposalState.PENDING,
            kind=kind,
        ):
            if proposal.source_hash == source_hash:
                return proposal
        return None


@dataclass
class DepartmentMemoryReviewService:
    """Review service that is allowed to promote proposals to active memory."""

    store: DepartmentMemoryProposalStore = field(
        default_factory=DepartmentMemoryProposalStore
    )

    @property
    def root(self) -> Path:
        return self.store.root

    def accepted_dir(self, department_id: str) -> Path:
        return department_memory_dir(self.root, department_id) / "accepted"

    def history_dir(self, department_id: str, memory_id: str) -> Path:
        _validate_identifier(memory_id, "memory_id")
        return department_memory_dir(self.root, department_id) / "history" / memory_id

    def memory_path(self, department_id: str, memory_id: str) -> Path:
        _validate_identifier(memory_id, "memory_id")
        return self.accepted_dir(department_id) / f"{memory_id}.json"

    def history_path(
        self, department_id: str, memory_id: str, revision: int
    ) -> Path:
        _require_positive_int(revision, "revision")
        return self.history_dir(department_id, memory_id) / f"{revision}.json"

    def load_memory(self, department_id: str, memory_id: str) -> DepartmentMemoryRecord:
        path = self.memory_path(department_id, memory_id)
        if not path.exists():
            raise DepartmentMemoryError(
                f"Department memory does not exist: {memory_id!r}"
            )
        return department_memory_from_dict(_load_json_object(path, "department memory"))

    def approve(
        self, department_id: str, proposal_id: str, action: DepartmentMemoryReviewAction
    ) -> DepartmentMemoryRecord:
        """Approve a proposal and write the active memory record."""

        proposal = self.store.load_proposal(department_id, proposal_id)
        self._validate_action(proposal, action, DepartmentMemoryReviewDecision.APPROVE)
        if proposal.state not in {
            DepartmentMemoryProposalState.PENDING,
            DepartmentMemoryProposalState.CHANGES_REQUESTED,
        }:
            raise DepartmentMemoryError("only pending proposals can be approved")
        if _requires_user_confirmation(proposal) and not action.user_confirmation_ref:
            raise DepartmentMemoryError("user confirmation is required for this proposal")

        memory_id = action.supersede_memory_id or proposal.proposal_id
        revision = 1
        if action.supersede_memory_id is not None:
            current = self.load_memory(proposal.department_id, action.supersede_memory_id)
            self._write_history(replace(current, active=False))
            revision = current.revision + 1

        memory = DepartmentMemoryRecord(
            department_id=proposal.department_id,
            memory_id=memory_id,
            kind=proposal.kind,
            summary=proposal.candidate_summary,
            source_refs=proposal.source_refs + action.audit_refs,
            visibility=proposal.visibility,
            sensitivity=proposal.sensitivity,
            revision=revision,
            active=True,
            accepted_at=action.reviewed_at,
            created_at=proposal.created_at,
            updated_at=action.reviewed_at,
            audit_summary=_review_audit_summary(proposal, action),
        )
        atomic_json_write(self.memory_path(memory.department_id, memory.memory_id), department_memory_to_dict(memory))
        updated_state = (
            DepartmentMemoryProposalState.SUPERSEDED
            if action.supersede_memory_id is not None
            else DepartmentMemoryProposalState.APPROVED
        )
        self.store.save_proposal(
            _proposal_with_review_state(proposal, updated_state, action)
        )
        return memory

    def reject(
        self, department_id: str, proposal_id: str, action: DepartmentMemoryReviewAction
    ) -> DepartmentMemoryProposal:
        return self._update_proposal_state(
            department_id,
            proposal_id,
            action,
            DepartmentMemoryReviewDecision.REJECT,
            DepartmentMemoryProposalState.REJECTED,
        )

    def request_changes(
        self, department_id: str, proposal_id: str, action: DepartmentMemoryReviewAction
    ) -> DepartmentMemoryProposal:
        return self._update_proposal_state(
            department_id,
            proposal_id,
            action,
            DepartmentMemoryReviewDecision.REQUEST_CHANGES,
            DepartmentMemoryProposalState.CHANGES_REQUESTED,
        )

    def expire(
        self, department_id: str, proposal_id: str, action: DepartmentMemoryReviewAction
    ) -> DepartmentMemoryProposal:
        return self._update_proposal_state(
            department_id,
            proposal_id,
            action,
            DepartmentMemoryReviewDecision.EXPIRE,
            DepartmentMemoryProposalState.EXPIRED,
        )

    def _update_proposal_state(
        self,
        department_id: str,
        proposal_id: str,
        action: DepartmentMemoryReviewAction,
        expected_decision: DepartmentMemoryReviewDecision,
        new_state: DepartmentMemoryProposalState,
    ) -> DepartmentMemoryProposal:
        proposal = self.store.load_proposal(department_id, proposal_id)
        self._validate_action(proposal, action, expected_decision)
        if proposal.state is not DepartmentMemoryProposalState.PENDING:
            raise DepartmentMemoryError("only pending proposals can change review state")
        updated = _proposal_with_review_state(proposal, new_state, action)
        self.store.save_proposal(updated)
        return updated

    def _validate_action(
        self,
        proposal: DepartmentMemoryProposal,
        action: DepartmentMemoryReviewAction,
        expected_decision: DepartmentMemoryReviewDecision,
    ) -> None:
        if action.proposal_id != proposal.proposal_id:
            raise DepartmentMemoryError("review action proposal_id does not match")
        if action.decision is not expected_decision:
            raise DepartmentMemoryError("review action decision does not match")
        # The enum coercion on the action constrains review to known actor roles.
        if not action.actor_id:
            raise DepartmentMemoryError("review action actor_id is required")

    def _write_history(self, memory: DepartmentMemoryRecord) -> Path:
        path = self.history_path(memory.department_id, memory.memory_id, memory.revision)
        atomic_json_write(path, department_memory_to_dict(memory))
        return path


def validate_department_memory_payload(payload: Mapping[str, Any]) -> None:
    """Reject raw, private, or secret-bearing fields before durable storage."""

    _reject_sensitive_payload(payload, "payload")


def proposal_from_routed_department_asset(
    routed: RoutedProposalRecord,
    *,
    kind: DepartmentMemoryKind | str,
    visibility: DepartmentMemoryVisibility | str = (
        DepartmentMemoryVisibility.PRIVATE_TO_DEPARTMENT
    ),
    sensitivity: DepartmentMemorySensitivity | str = DepartmentMemorySensitivity.INTERNAL,
    created_at: str | None = None,
) -> DepartmentMemoryProposal:
    """Convert a routed department asset candidate into a memory proposal."""

    if routed.proposal_kind is not RoutedProposalKind.DEPARTMENT_ASSET:
        raise DepartmentMemoryError("routed proposal must target a department asset")
    department_id = _department_id_from_target_scope(routed.target_scope)
    source_hash = routed.metadata.get("source_hash")
    if source_hash is not None:
        _require_string(source_hash, "source_hash")
    review_reason = routed.metadata.get("review_reason") or ""
    if not isinstance(review_reason, str):
        raise DepartmentMemoryError("review_reason must be a string")
    return DepartmentMemoryProposal(
        proposal_id=routed.proposal_id,
        department_id=department_id,
        kind=kind,
        candidate_summary=routed.summary,
        source_actor=routed.source_worker_id,
        source_refs=(f"tasks/{routed.task_id}/runtime/{routed.source_route_item_id}",),
        rationale=review_reason,
        source_hash=source_hash,
        visibility=visibility,
        sensitivity=sensitivity,
        review_requirement="department_lead_or_main_agent",
        created_at=created_at,
        audit_summary=(
            f"Routed department asset proposal {routed.proposal_id} "
            f"from task {routed.task_id}."
        ),
    )


def proposal_from_private_asset_input(
    proposal_input: PrivateAssetProposalInput,
    *,
    proposal_id: str,
    department_id: str,
    kind: DepartmentMemoryKind | str,
    source_actor: str | None = None,
    visibility: DepartmentMemoryVisibility | str = (
        DepartmentMemoryVisibility.PRIVATE_TO_DEPARTMENT
    ),
    sensitivity: DepartmentMemorySensitivity | str = DepartmentMemorySensitivity.INTERNAL,
    created_at: str | None = None,
) -> DepartmentMemoryProposal:
    """Convert a low-sensitivity private asset input without reading private text."""

    return DepartmentMemoryProposal(
        proposal_id=proposal_id,
        department_id=department_id,
        kind=kind,
        candidate_summary=proposal_input.summary,
        source_actor=source_actor or proposal_input.source_worker_id,
        source_refs=proposal_input.source_refs,
        rationale=proposal_input.review_requirement,
        source_hash=proposal_input.content_hash,
        visibility=visibility,
        sensitivity=sensitivity,
        review_requirement=proposal_input.review_requirement,
        created_at=created_at,
        audit_summary=proposal_input.audit_summary,
    )


def department_memory_dir(worker_agents_home: str | Path, department_id: str) -> Path:
    """Return the durable department memory root without creating it."""

    validate_org_node_id(department_id)
    return (
        Path(worker_agents_home)
        / "organization"
        / "departments"
        / department_id
        / "memory"
    )


def department_memory_to_dict(memory: DepartmentMemoryRecord) -> dict[str, Any]:
    """Return a deterministic JSON-ready active department memory."""

    return {
        "department_id": memory.department_id,
        "memory_id": memory.memory_id,
        "schema_version": memory.schema_version,
        "kind": memory.kind.value,
        "summary": memory.summary,
        "source_refs": list(memory.source_refs),
        "visibility": memory.visibility.value,
        "sensitivity": memory.sensitivity.value,
        "revision": memory.revision,
        "active": memory.active,
        "accepted_at": memory.accepted_at,
        "created_at": memory.created_at,
        "updated_at": memory.updated_at,
        "audit_summary": memory.audit_summary,
    }


def department_memory_from_dict(data: Mapping[str, Any]) -> DepartmentMemoryRecord:
    """Load an active department memory after validating its boundary."""

    data = _require_mapping(data, "department memory")
    _reject_unknown_fields(data, _MEMORY_FIELDS, "department memory")
    return DepartmentMemoryRecord(
        department_id=_require_string(data.get("department_id"), "department_id"),
        memory_id=_require_string(data.get("memory_id"), "memory_id"),
        schema_version=data.get("schema_version", DEPARTMENT_MEMORY_SCHEMA_VERSION),
        kind=_require_string(data.get("kind"), "kind"),
        summary=_require_string(data.get("summary"), "summary"),
        source_refs=_string_tuple(data.get("source_refs", ()), "source_refs"),
        visibility=data.get(
            "visibility", DepartmentMemoryVisibility.PRIVATE_TO_DEPARTMENT
        ),
        sensitivity=data.get("sensitivity", DepartmentMemorySensitivity.LOW),
        revision=data.get("revision", 1),
        active=data.get("active", True),
        accepted_at=_optional_string(data.get("accepted_at"), "accepted_at"),
        created_at=_optional_string(data.get("created_at"), "created_at"),
        updated_at=_optional_string(data.get("updated_at"), "updated_at"),
        audit_summary=_string_value(data.get("audit_summary", ""), "audit_summary"),
    )


def department_memory_proposal_to_dict(
    proposal: DepartmentMemoryProposal,
) -> dict[str, Any]:
    """Return a deterministic JSON-ready department memory proposal."""

    return {
        "proposal_id": proposal.proposal_id,
        "department_id": proposal.department_id,
        "schema_version": proposal.schema_version,
        "kind": proposal.kind.value,
        "candidate_summary": proposal.candidate_summary,
        "source_actor": proposal.source_actor,
        "source_refs": list(proposal.source_refs),
        "rationale": proposal.rationale,
        "source_hash": proposal.source_hash,
        "visibility": proposal.visibility.value,
        "sensitivity": proposal.sensitivity.value,
        "review_requirement": proposal.review_requirement,
        "state": proposal.state.value,
        "created_at": proposal.created_at,
        "updated_at": proposal.updated_at,
        "audit_summary": proposal.audit_summary,
    }


def department_memory_proposal_from_dict(
    data: Mapping[str, Any],
) -> DepartmentMemoryProposal:
    """Load a department memory proposal after validating its boundary."""

    data = _require_mapping(data, "department memory proposal")
    _reject_unknown_fields(data, _PROPOSAL_FIELDS, "department memory proposal")
    return DepartmentMemoryProposal(
        proposal_id=_require_string(data.get("proposal_id"), "proposal_id"),
        department_id=_require_string(data.get("department_id"), "department_id"),
        schema_version=data.get("schema_version", DEPARTMENT_MEMORY_SCHEMA_VERSION),
        kind=_require_string(data.get("kind"), "kind"),
        candidate_summary=_require_string(
            data.get("candidate_summary"), "candidate_summary"
        ),
        source_actor=_require_string(data.get("source_actor"), "source_actor"),
        source_refs=_string_tuple(data.get("source_refs", ()), "source_refs"),
        rationale=_string_value(data.get("rationale", ""), "rationale"),
        source_hash=_optional_string(data.get("source_hash"), "source_hash"),
        visibility=data.get(
            "visibility", DepartmentMemoryVisibility.PRIVATE_TO_DEPARTMENT
        ),
        sensitivity=data.get("sensitivity", DepartmentMemorySensitivity.INTERNAL),
        review_requirement=_require_string(
            data.get("review_requirement"), "review_requirement"
        ),
        state=data.get("state", DepartmentMemoryProposalState.PENDING),
        created_at=_optional_string(data.get("created_at"), "created_at"),
        updated_at=_optional_string(data.get("updated_at"), "updated_at"),
        audit_summary=_string_value(data.get("audit_summary", ""), "audit_summary"),
    )


_MEMORY_FIELDS = {
    "department_id",
    "memory_id",
    "schema_version",
    "kind",
    "summary",
    "source_refs",
    "visibility",
    "sensitivity",
    "revision",
    "active",
    "accepted_at",
    "created_at",
    "updated_at",
    "audit_summary",
}
_PROPOSAL_FIELDS = {
    "proposal_id",
    "department_id",
    "schema_version",
    "kind",
    "candidate_summary",
    "source_actor",
    "source_refs",
    "rationale",
    "source_hash",
    "visibility",
    "sensitivity",
    "review_requirement",
    "state",
    "created_at",
    "updated_at",
    "audit_summary",
}


def _require_schema_version(schema_version: Any) -> None:
    if schema_version != DEPARTMENT_MEMORY_SCHEMA_VERSION:
        raise DepartmentMemoryError(
            f"Unsupported department memory schema_version: {schema_version!r}"
        )


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise DepartmentMemoryError(f"{field_name} must be a non-empty string")
    return value


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, field_name)


def _string_value(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise DepartmentMemoryError(f"{field_name} must be a string")
    return value


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise DepartmentMemoryError(f"{field_name} must be a list of strings")
    result = tuple(value)
    if any(not isinstance(item, str) or not item for item in result):
        raise DepartmentMemoryError(f"{field_name} must be a list of non-empty strings")
    return result


def _require_positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DepartmentMemoryError(f"{field_name} must be a positive integer")
    return value


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DepartmentMemoryError(f"{field_name} must be an object")
    return value


def _reject_unknown_fields(
    data: Mapping[str, Any], allowed_fields: set[str], field_name: str
) -> None:
    unknown_fields = sorted(set(data) - allowed_fields)
    if unknown_fields:
        joined = ", ".join(unknown_fields)
        raise DepartmentMemoryError(f"{field_name} has unknown fields: {joined}")


def _validate_identifier(value: str, field_name: str) -> str:
    _require_string(value, field_name)
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise DepartmentMemoryError(f"{field_name} must be a single path segment")
    return value


def _validate_relative_ref(value: str, field_name: str) -> str:
    _require_string(value, field_name)
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or ".." in posix.parts
        or ".." in windows.parts
    ):
        raise DepartmentMemoryError(f"{field_name} must stay within allowed storage")
    return value


def _memory_kind(value: DepartmentMemoryKind | str) -> DepartmentMemoryKind:
    try:
        return (
            value
            if isinstance(value, DepartmentMemoryKind)
            else DepartmentMemoryKind(value)
        )
    except ValueError as exc:
        raise DepartmentMemoryError(f"Unknown department memory kind: {value!r}") from exc


def _memory_visibility(
    value: DepartmentMemoryVisibility | str,
) -> DepartmentMemoryVisibility:
    try:
        return (
            value
            if isinstance(value, DepartmentMemoryVisibility)
            else DepartmentMemoryVisibility(value)
        )
    except ValueError as exc:
        raise DepartmentMemoryError(
            f"Unknown department memory visibility: {value!r}"
        ) from exc


def _memory_sensitivity(
    value: DepartmentMemorySensitivity | str,
) -> DepartmentMemorySensitivity:
    try:
        return (
            value
            if isinstance(value, DepartmentMemorySensitivity)
            else DepartmentMemorySensitivity(value)
        )
    except ValueError as exc:
        raise DepartmentMemoryError(
            f"Unknown department memory sensitivity: {value!r}"
        ) from exc


def _proposal_state(
    value: DepartmentMemoryProposalState | str,
) -> DepartmentMemoryProposalState:
    try:
        return (
            value
            if isinstance(value, DepartmentMemoryProposalState)
            else DepartmentMemoryProposalState(value)
        )
    except ValueError as exc:
        raise DepartmentMemoryError(
            f"Unknown department memory proposal state: {value!r}"
        ) from exc


def _reject_sensitive_payload(value: Any, field_name: str) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_text = str(key)
            if key_text.lower() in _SENSITIVE_FIELD_NAMES:
                raise DepartmentMemoryError(
                    f"{field_name} contains sensitive field: {key_text}"
                )
            _reject_sensitive_payload(nested, f"{field_name}.{key_text}")
        return
    if isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _reject_sensitive_payload(nested, f"{field_name}[{index}]")


def _proposal_create_status(
    value: DepartmentMemoryProposalCreateStatus | str,
) -> DepartmentMemoryProposalCreateStatus:
    try:
        return (
            value
            if isinstance(value, DepartmentMemoryProposalCreateStatus)
            else DepartmentMemoryProposalCreateStatus(value)
        )
    except ValueError as exc:
        raise DepartmentMemoryError(
            f"Unknown department memory proposal create status: {value!r}"
        ) from exc


def _reviewer_role(
    value: DepartmentMemoryReviewerRole | str,
) -> DepartmentMemoryReviewerRole:
    try:
        return (
            value
            if isinstance(value, DepartmentMemoryReviewerRole)
            else DepartmentMemoryReviewerRole(value)
        )
    except ValueError as exc:
        raise DepartmentMemoryError(
            f"Unknown department memory reviewer role: {value!r}"
        ) from exc


def _review_decision(
    value: DepartmentMemoryReviewDecision | str,
) -> DepartmentMemoryReviewDecision:
    try:
        return (
            value
            if isinstance(value, DepartmentMemoryReviewDecision)
            else DepartmentMemoryReviewDecision(value)
        )
    except ValueError as exc:
        raise DepartmentMemoryError(
            f"Unknown department memory review decision: {value!r}"
        ) from exc


def _requires_user_confirmation(proposal: DepartmentMemoryProposal) -> bool:
    return proposal.sensitivity in {
        DepartmentMemorySensitivity.RESTRICTED,
        DepartmentMemorySensitivity.USER_CONFIRMATION_REQUIRED,
    }


def _proposal_with_review_state(
    proposal: DepartmentMemoryProposal,
    state: DepartmentMemoryProposalState,
    action: DepartmentMemoryReviewAction,
) -> DepartmentMemoryProposal:
    return replace(
        proposal,
        state=state,
        updated_at=action.reviewed_at,
        audit_summary=_review_audit_summary(proposal, action),
    )


def _review_audit_summary(
    proposal: DepartmentMemoryProposal, action: DepartmentMemoryReviewAction
) -> str:
    return (
        f"{action.actor_role.value} {action.actor_id} "
        f"{action.decision.value}d department memory proposal "
        f"{proposal.proposal_id}: {action.reason}"
    )


def _department_id_from_target_scope(target_scope: str) -> str:
    _require_string(target_scope, "target_scope")
    prefix = "department:"
    if not target_scope.startswith(prefix):
        raise DepartmentMemoryError("target_scope must start with 'department:'")
    department_id = target_scope[len(prefix) :]
    validate_org_node_id(department_id)
    return department_id


def _load_json_object(path: Path, field_name: str) -> Mapping[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DepartmentMemoryError(f"{field_name} JSON is invalid: {path}") from exc
    return _require_mapping(data, field_name)

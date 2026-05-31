"""Durable store for organization evolution proposals."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

from utils import atomic_json_write

from ..organization_evolution import (
    EvolutionProposalStatus,
    EvolutionProposalType,
    OrganizationEvolutionError,
    OrganizationEvolutionProposal,
    classify_evolution_risks,
    organization_evolution_proposal_from_dict,
    organization_evolution_proposal_to_dict,
    resolve_approval_requirement,
    validate_evolution_proposal,
)
from .paths import get_organization_proposals_dir
from .safe_paths import validate_single_path_segment


EVOLUTION_PROPOSAL_RECORD_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class EvolutionProposalStatusChange:
    """One auditable proposal status transition."""

    actor: str
    changed_at: str
    from_status: EvolutionProposalStatus | str | None
    to_status: EvolutionProposalStatus | str
    reason: str

    def __post_init__(self) -> None:
        _require_string(self.actor, "actor")
        _require_string(self.changed_at, "changed_at")
        if self.from_status is not None:
            object.__setattr__(self, "from_status", _proposal_status(self.from_status))
        object.__setattr__(self, "to_status", _proposal_status(self.to_status))
        _require_string(self.reason, "reason")


@dataclass(frozen=True)
class StoredEvolutionProposal:
    """Stored proposal plus audit history."""

    proposal: OrganizationEvolutionProposal
    status_history: tuple[EvolutionProposalStatusChange, ...] = ()
    schema_version: int = EVOLUTION_PROPOSAL_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EVOLUTION_PROPOSAL_RECORD_SCHEMA_VERSION:
            raise OrganizationEvolutionError(
                "Unsupported evolution proposal record schema_version: "
                f"{self.schema_version!r}"
            )
        if not isinstance(self.proposal, OrganizationEvolutionProposal):
            raise OrganizationEvolutionError(
                "proposal must be an OrganizationEvolutionProposal"
            )
        if self.status_history:
            latest = self.status_history[-1].to_status
            if latest is not self.proposal.status:
                raise OrganizationEvolutionError(
                    "status_history latest status must match proposal status"
                )


@dataclass
class EvolutionProposalStore:
    """Profile-home store for proposal-first organization evolution."""

    root: Path = field(default_factory=get_organization_proposals_dir)

    def initialize(self) -> Path:
        """Create only the proposal directory, not the active organization tree."""
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root

    def proposal_path(self, proposal_id: str) -> Path:
        safe_id = _safe_proposal_id(proposal_id)
        return self.root / f"{safe_id}.json"

    def create_proposal(
        self,
        proposal: OrganizationEvolutionProposal | Mapping[str, Any],
        *,
        actor: str,
        changed_at: str,
        reason: str,
    ) -> Path:
        validated = _validate_for_store(proposal)
        path = self.proposal_path(validated.proposal_id)
        if path.exists():
            raise OrganizationEvolutionError(
                f"Evolution proposal already exists: {validated.proposal_id!r}"
            )
        record = StoredEvolutionProposal(
            proposal=validated,
            status_history=(
                EvolutionProposalStatusChange(
                    actor=actor,
                    changed_at=changed_at,
                    from_status=None,
                    to_status=validated.status,
                    reason=reason,
                ),
            ),
        )
        self.initialize()
        atomic_json_write(path, stored_evolution_proposal_to_dict(record))
        return path

    def load_record(self, proposal_id: str) -> StoredEvolutionProposal:
        path = self.proposal_path(proposal_id)
        if not path.exists():
            raise OrganizationEvolutionError(
                f"Evolution proposal does not exist: {proposal_id!r}"
            )
        return stored_evolution_proposal_from_dict(_load_json_object(path))

    def load_proposal(self, proposal_id: str) -> OrganizationEvolutionProposal:
        return self.load_record(proposal_id).proposal

    def list_proposals(
        self,
        *,
        status: EvolutionProposalStatus | str | None = None,
        proposal_type: EvolutionProposalType | str | None = None,
        target_node_id: str | None = None,
    ) -> list[OrganizationEvolutionProposal]:
        expected_status = _proposal_status(status) if status is not None else None
        expected_type = _proposal_type(proposal_type) if proposal_type is not None else None
        return [
            record.proposal
            for record in sorted(
                (stored_evolution_proposal_from_dict(_load_json_object(path)) for path in self.root.glob("*.json")),
                key=lambda item: (item.proposal.created_at or "", item.proposal.proposal_id),
            )
            if _matches_filters(
                record.proposal,
                status=expected_status,
                proposal_type=expected_type,
                target_node_id=target_node_id,
            )
        ]

    def update_status(
        self,
        proposal_id: str,
        new_status: EvolutionProposalStatus | str,
        *,
        actor: str,
        changed_at: str,
        reason: str,
    ) -> Path:
        record = self.load_record(proposal_id)
        target_status = _proposal_status(new_status)
        _validate_status_transition(record.proposal.status, target_status)
        updated_proposal = _validate_for_store(
            replace(record.proposal, status=target_status, updated_at=changed_at)
        )
        updated_record = StoredEvolutionProposal(
            proposal=updated_proposal,
            status_history=(
                *record.status_history,
                EvolutionProposalStatusChange(
                    actor=actor,
                    changed_at=changed_at,
                    from_status=record.proposal.status,
                    to_status=target_status,
                    reason=reason,
                ),
            ),
        )
        path = self.proposal_path(proposal_id)
        atomic_json_write(path, stored_evolution_proposal_to_dict(updated_record))
        return path


_STORED_PROPOSAL_FIELDS = {"schema_version", "proposal", "status_history"}
_STATUS_CHANGE_FIELDS = {
    "actor",
    "changed_at",
    "from_status",
    "to_status",
    "reason",
}
_ALLOWED_STATUS_TRANSITIONS = {
    EvolutionProposalStatus.DRAFT: frozenset(
        {
            EvolutionProposalStatus.PENDING_APPROVAL,
            EvolutionProposalStatus.REJECTED,
            EvolutionProposalStatus.EXPIRED,
        }
    ),
    EvolutionProposalStatus.PENDING_APPROVAL: frozenset(
        {
            EvolutionProposalStatus.APPROVED,
            EvolutionProposalStatus.REJECTED,
            EvolutionProposalStatus.EXPIRED,
        }
    ),
    EvolutionProposalStatus.APPROVED: frozenset(
        {
            EvolutionProposalStatus.EXECUTED,
            EvolutionProposalStatus.FAILED,
            EvolutionProposalStatus.EXPIRED,
        }
    ),
    EvolutionProposalStatus.REJECTED: frozenset(),
    EvolutionProposalStatus.EXPIRED: frozenset(),
    EvolutionProposalStatus.EXECUTED: frozenset(),
    EvolutionProposalStatus.FAILED: frozenset(),
}


def stored_evolution_proposal_to_dict(
    record: StoredEvolutionProposal,
) -> dict[str, Any]:
    return {
        "schema_version": record.schema_version,
        "proposal": organization_evolution_proposal_to_dict(record.proposal),
        "status_history": [
            evolution_proposal_status_change_to_dict(change)
            for change in record.status_history
        ],
    }


def stored_evolution_proposal_from_dict(
    data: Mapping[str, Any],
) -> StoredEvolutionProposal:
    data = _require_mapping(data, "stored evolution proposal")
    _reject_unknown_fields(data, _STORED_PROPOSAL_FIELDS, "stored evolution proposal")
    return StoredEvolutionProposal(
        schema_version=data.get(
            "schema_version", EVOLUTION_PROPOSAL_RECORD_SCHEMA_VERSION
        ),
        proposal=organization_evolution_proposal_from_dict(
            _require_mapping(data.get("proposal"), "proposal")
        ),
        status_history=tuple(
            evolution_proposal_status_change_from_dict(
                _require_mapping(item, "status_history item")
            )
            for item in data.get("status_history", ())
        ),
    )


def evolution_proposal_status_change_to_dict(
    change: EvolutionProposalStatusChange,
) -> dict[str, Any]:
    return {
        "actor": change.actor,
        "changed_at": change.changed_at,
        "from_status": (
            change.from_status.value if change.from_status is not None else None
        ),
        "to_status": change.to_status.value,
        "reason": change.reason,
    }


def evolution_proposal_status_change_from_dict(
    data: Mapping[str, Any],
) -> EvolutionProposalStatusChange:
    data = _require_mapping(data, "evolution proposal status change")
    _reject_unknown_fields(
        data,
        _STATUS_CHANGE_FIELDS,
        "evolution proposal status change",
    )
    return EvolutionProposalStatusChange(
        actor=_require_string(data.get("actor"), "actor"),
        changed_at=_require_string(data.get("changed_at"), "changed_at"),
        from_status=data.get("from_status"),
        to_status=_require_string(data.get("to_status"), "to_status"),
        reason=_require_string(data.get("reason"), "reason"),
    )


def _validate_for_store(
    proposal: OrganizationEvolutionProposal | Mapping[str, Any],
) -> OrganizationEvolutionProposal:
    validated = validate_evolution_proposal(proposal)
    risks = classify_evolution_risks(validated)
    resolve_approval_requirement(validated, risks)
    return validated


def _validate_status_transition(
    current_status: EvolutionProposalStatus,
    new_status: EvolutionProposalStatus,
) -> None:
    allowed = _ALLOWED_STATUS_TRANSITIONS[current_status]
    if new_status not in allowed:
        raise OrganizationEvolutionError(
            f"Invalid evolution proposal status transition: "
            f"{current_status.value} -> {new_status.value}"
        )


def _matches_filters(
    proposal: OrganizationEvolutionProposal,
    *,
    status: EvolutionProposalStatus | None,
    proposal_type: EvolutionProposalType | None,
    target_node_id: str | None,
) -> bool:
    if status is not None and proposal.status is not status:
        return False
    if proposal_type is not None and proposal.proposal_type is not proposal_type:
        return False
    if target_node_id is not None and target_node_id not in proposal.target_node_ids:
        return False
    return True


def _load_json_object(path: Path) -> Mapping[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise OrganizationEvolutionError(
            f"Invalid evolution proposal JSON: {exc.msg}"
        ) from exc
    return _require_mapping(data, "stored evolution proposal")


def _safe_proposal_id(proposal_id: str) -> str:
    try:
        return validate_single_path_segment(proposal_id, "evolution proposal id")
    except ValueError as exc:
        raise OrganizationEvolutionError(str(exc)) from exc


def _proposal_status(
    value: EvolutionProposalStatus | str,
) -> EvolutionProposalStatus:
    try:
        return (
            value
            if isinstance(value, EvolutionProposalStatus)
            else EvolutionProposalStatus(value)
        )
    except ValueError as exc:
        raise OrganizationEvolutionError(
            f"Unknown evolution proposal status: {value!r}"
        ) from exc


def _proposal_type(value: EvolutionProposalType | str) -> EvolutionProposalType:
    try:
        return (
            value
            if isinstance(value, EvolutionProposalType)
            else EvolutionProposalType(value)
        )
    except ValueError as exc:
        raise OrganizationEvolutionError(
            f"Unknown evolution proposal type: {value!r}"
        ) from exc


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise OrganizationEvolutionError(f"{field_name} must be an object")
    return value


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise OrganizationEvolutionError(f"{field_name} must be a non-empty string")
    return value


def _reject_unknown_fields(
    data: Mapping[str, Any], allowed_fields: set[str], field_name: str
) -> None:
    unknown_fields = sorted(set(data) - allowed_fields)
    if unknown_fields:
        joined = ", ".join(unknown_fields)
        raise OrganizationEvolutionError(f"{field_name} has unknown fields: {joined}")

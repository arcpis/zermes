"""Durable organization storage for active managed-worker structure."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping

from utils import atomic_json_write

from ..organization import (
    ORGANIZATION_SCHEMA_VERSION,
    OrgTree,
    OrganizationError,
    load_org_tree_json,
    org_tree_from_dict,
    org_tree_to_dict,
    validate_org_node_id,
)
from .paths import (
    get_active_organization_path,
    get_organization_history_dir,
    get_organization_proposals_dir,
    get_worker_agents_organization_dir,
)
from .safe_paths import validate_single_path_segment


class OrganizationProposalStatus(StrEnum):
    """Lifecycle for stored organization change proposals."""

    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"
    ARCHIVED = "archived"


@dataclass(frozen=True)
class OrganizationProposalSummary:
    """Low-sensitivity organization proposal summary for audit and UI lists."""

    proposal_id: str
    created_at: str
    submitted_by: str
    summary: str
    target_node_id: str | None = None
    status: OrganizationProposalStatus = OrganizationProposalStatus.PROPOSED
    updated_at: str | None = None
    schema_version: int = ORGANIZATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        validate_single_path_segment(self.proposal_id, "proposal id")
        _require_non_empty_string(self.created_at, "created_at")
        _require_non_empty_string(self.submitted_by, "submitted_by")
        _require_non_empty_string(self.summary, "summary")
        if self.target_node_id is not None:
            validate_org_node_id(self.target_node_id)
        object.__setattr__(self, "status", _proposal_status(self.status))
        _validate_schema_version(self.schema_version)


@dataclass(frozen=True)
class OrganizationHistorySummary:
    """Low-sensitivity organization change summary for durable audit history."""

    change_id: str
    created_at: str
    actor: str
    summary: str
    affected_node_ids: tuple[str, ...] = ()
    previous_revision: int | None = None
    new_revision: int | None = None
    schema_version: int = ORGANIZATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        validate_single_path_segment(self.change_id, "change id")
        _require_non_empty_string(self.created_at, "created_at")
        _require_non_empty_string(self.actor, "actor")
        _require_non_empty_string(self.summary, "summary")
        for node_id in self.affected_node_ids:
            validate_org_node_id(node_id)
        if self.previous_revision is not None:
            _require_non_negative_int(self.previous_revision, "previous_revision")
        if self.new_revision is not None:
            _require_non_negative_int(self.new_revision, "new_revision")
        _validate_schema_version(self.schema_version)


@dataclass
class OrganizationStore:
    """Profile-home storage for durable organization records."""

    root: Path = field(default_factory=get_worker_agents_organization_dir)

    @property
    def active_path(self) -> Path:
        return self.root / "active.json"

    @property
    def proposals_dir(self) -> Path:
        return self.root / "proposals"

    @property
    def history_dir(self) -> Path:
        return self.root / "history"

    def initialize(self) -> Path:
        """Create organization directories without creating organization data."""
        self.proposals_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir.mkdir(parents=True, exist_ok=True)
        return self.root

    def load_active_organization(self) -> OrgTree | None:
        """Load the active organization tree, returning ``None`` when absent."""
        if not self.active_path.exists():
            return None
        return load_org_tree_json(self.active_path.read_text(encoding="utf-8"))

    def save_active_organization(
        self, tree: OrgTree, *, expected_revision: int | None = None
    ) -> Path:
        """Atomically save the active tree after validating revision expectations."""
        current_tree = self.load_active_organization()
        current_revision = current_tree.revision if current_tree is not None else None
        if expected_revision is not None and current_revision != expected_revision:
            raise OrganizationError(
                "active organization revision conflict: "
                f"expected {expected_revision!r}, found {current_revision!r}"
            )
        if expected_revision is not None and tree.revision <= expected_revision:
            raise OrganizationError("active organization revision must advance")

        data = org_tree_to_dict(tree)
        org_tree_from_dict(data)
        self.initialize()
        atomic_json_write(self.active_path, data)
        return self.active_path

    def proposal_summary_path(self, proposal_id: str) -> Path:
        """Return the durable proposal summary path for one safe id."""
        safe_id = validate_single_path_segment(proposal_id, "proposal id")
        return self.proposals_dir / f"{safe_id}.json"

    def history_summary_path(self, change_id: str) -> Path:
        """Return the durable history summary path for one safe id."""
        safe_id = validate_single_path_segment(change_id, "change id")
        return self.history_dir / f"{safe_id}.json"

    def save_proposal_summary(self, proposal: OrganizationProposalSummary) -> Path:
        """Atomically save one organization proposal summary."""
        path = self.proposal_summary_path(proposal.proposal_id)
        self.initialize()
        atomic_json_write(path, organization_proposal_summary_to_dict(proposal))
        return path

    def load_proposal_summary(self, proposal_id: str) -> OrganizationProposalSummary:
        """Load one organization proposal summary."""
        path = self.proposal_summary_path(proposal_id)
        if not path.exists():
            raise OrganizationError(f"Organization proposal does not exist: {proposal_id!r}")
        return organization_proposal_summary_from_dict(_load_json_object(path, "proposal"))

    def list_proposal_summaries(self) -> list[OrganizationProposalSummary]:
        """Return stored proposal summaries sorted by creation time and id."""
        return sorted(
            (
                organization_proposal_summary_from_dict(
                    _load_json_object(path, "proposal")
                )
                for path in self.proposals_dir.glob("*.json")
            ),
            key=lambda proposal: (proposal.created_at, proposal.proposal_id),
        )

    def save_history_summary(self, history: OrganizationHistorySummary) -> Path:
        """Atomically save one organization history summary."""
        path = self.history_summary_path(history.change_id)
        self.initialize()
        atomic_json_write(path, organization_history_summary_to_dict(history))
        return path

    def load_history_summary(self, change_id: str) -> OrganizationHistorySummary:
        """Load one organization history summary."""
        path = self.history_summary_path(change_id)
        if not path.exists():
            raise OrganizationError(f"Organization history does not exist: {change_id!r}")
        return organization_history_summary_from_dict(_load_json_object(path, "history"))

    def list_history_summaries(self) -> list[OrganizationHistorySummary]:
        """Return stored history summaries sorted by creation time and id."""
        return sorted(
            (
                organization_history_summary_from_dict(
                    _load_json_object(path, "history")
                )
                for path in self.history_dir.glob("*.json")
            ),
            key=lambda history: (history.created_at, history.change_id),
        )


_PROPOSAL_FIELDS = {
    "proposal_id",
    "schema_version",
    "created_at",
    "updated_at",
    "submitted_by",
    "target_node_id",
    "summary",
    "status",
}
_HISTORY_FIELDS = {
    "change_id",
    "schema_version",
    "created_at",
    "actor",
    "affected_node_ids",
    "previous_revision",
    "new_revision",
    "summary",
}


def organization_proposal_summary_to_dict(
    proposal: OrganizationProposalSummary,
) -> dict[str, Any]:
    return {
        "proposal_id": proposal.proposal_id,
        "schema_version": proposal.schema_version,
        "created_at": proposal.created_at,
        "updated_at": proposal.updated_at,
        "submitted_by": proposal.submitted_by,
        "target_node_id": proposal.target_node_id,
        "summary": proposal.summary,
        "status": proposal.status.value,
    }


def organization_proposal_summary_from_dict(
    data: Mapping[str, Any],
) -> OrganizationProposalSummary:
    data = _require_mapping(data, "organization proposal")
    _reject_unknown_fields(data, _PROPOSAL_FIELDS, "organization proposal")
    return OrganizationProposalSummary(
        proposal_id=_require_non_empty_string(data.get("proposal_id"), "proposal_id"),
        schema_version=data.get("schema_version", ORGANIZATION_SCHEMA_VERSION),
        created_at=_require_non_empty_string(data.get("created_at"), "created_at"),
        updated_at=_optional_string(data.get("updated_at"), "updated_at"),
        submitted_by=_require_non_empty_string(data.get("submitted_by"), "submitted_by"),
        target_node_id=_optional_string(data.get("target_node_id"), "target_node_id"),
        summary=_require_non_empty_string(data.get("summary"), "summary"),
        status=_proposal_status(data.get("status", OrganizationProposalStatus.PROPOSED)),
    )


def organization_history_summary_to_dict(
    history: OrganizationHistorySummary,
) -> dict[str, Any]:
    return {
        "change_id": history.change_id,
        "schema_version": history.schema_version,
        "created_at": history.created_at,
        "actor": history.actor,
        "affected_node_ids": list(history.affected_node_ids),
        "previous_revision": history.previous_revision,
        "new_revision": history.new_revision,
        "summary": history.summary,
    }


def organization_history_summary_from_dict(
    data: Mapping[str, Any],
) -> OrganizationHistorySummary:
    data = _require_mapping(data, "organization history")
    _reject_unknown_fields(data, _HISTORY_FIELDS, "organization history")
    return OrganizationHistorySummary(
        change_id=_require_non_empty_string(data.get("change_id"), "change_id"),
        schema_version=data.get("schema_version", ORGANIZATION_SCHEMA_VERSION),
        created_at=_require_non_empty_string(data.get("created_at"), "created_at"),
        actor=_require_non_empty_string(data.get("actor"), "actor"),
        affected_node_ids=_string_tuple(
            data.get("affected_node_ids", ()), "affected_node_ids"
        ),
        previous_revision=_optional_non_negative_int(
            data.get("previous_revision"), "previous_revision"
        ),
        new_revision=_optional_non_negative_int(data.get("new_revision"), "new_revision"),
        summary=_require_non_empty_string(data.get("summary"), "summary"),
    )


def _load_json_object(path: Path, record_name: str) -> Mapping[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise OrganizationError(f"Invalid organization {record_name} JSON: {exc.msg}") from exc
    return _require_mapping(data, f"organization {record_name}")


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise OrganizationError(f"{field_name} must be an object")
    return value


def _require_non_empty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise OrganizationError(f"{field_name} must be a non-empty string")
    return value


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_non_empty_string(value, field_name)


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise OrganizationError(f"{field_name} must be a list of strings")
    result = tuple(value)
    if any(not isinstance(item, str) or not item for item in result):
        raise OrganizationError(f"{field_name} must be a list of non-empty strings")
    return result


def _require_non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise OrganizationError(f"{field_name} must be a non-negative integer")
    return value


def _optional_non_negative_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    return _require_non_negative_int(value, field_name)


def _validate_schema_version(value: int) -> None:
    if value != ORGANIZATION_SCHEMA_VERSION:
        raise OrganizationError(f"Unsupported organization schema_version: {value!r}")


def _proposal_status(value: OrganizationProposalStatus | str) -> OrganizationProposalStatus:
    if isinstance(value, OrganizationProposalStatus):
        return value
    if not isinstance(value, str) or not value:
        raise OrganizationError("proposal status must be a non-empty string")
    try:
        return OrganizationProposalStatus(value)
    except ValueError as exc:
        raise OrganizationError(f"Unknown organization proposal status: {value!r}") from exc


def _reject_unknown_fields(
    data: Mapping[str, Any], allowed_fields: set[str], field_name: str
) -> None:
    unknown_fields = sorted(set(data) - allowed_fields)
    if unknown_fields:
        joined = ", ".join(unknown_fields)
        raise OrganizationError(f"{field_name} has unknown fields: {joined}")


def get_default_organization_store() -> OrganizationStore:
    """Return an organization store rooted at the active profile home."""
    return OrganizationStore(root=get_worker_agents_organization_dir())


def get_default_active_organization_path() -> Path:
    """Return the active organization file path for callers that only need a path."""
    return get_active_organization_path()


def get_default_organization_proposals_dir() -> Path:
    """Return the default proposal summary directory."""
    return get_organization_proposals_dir()


def get_default_organization_history_dir() -> Path:
    """Return the default history summary directory."""
    return get_organization_history_dir()

"""Proposal contract for long-lived managed-worker organization changes."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Mapping

from .organization import OrganizationError, validate_org_node_id
from .profile import WorkerProfileError, validate_worker_id


EVOLUTION_PROPOSAL_SCHEMA_VERSION = 1

SENSITIVE_EVOLUTION_PROPOSAL_FIELDS = frozenset(
    {
        "credential",
        "credentials",
        "private_memory_text",
        "raw_stderr",
        "raw_stdout",
        "raw_transcript",
        "secret",
    }
)


class OrganizationEvolutionError(ValueError):
    """Raised when an organization evolution proposal is invalid."""


class EvolutionProposalType(StrEnum):
    """Supported long-lived organization evolution proposal types."""

    CREATE_CHILD_AGENT = "create_child_agent"
    DELETE_CHILD_AGENT = "delete_child_agent"
    MERGE_DEPARTMENT = "merge_department"
    TRANSFER_ASSETS = "transfer_assets"
    ARCHIVE_ORG_NODE = "archive_org_node"


class EvolutionProposalStatus(StrEnum):
    """Review and execution lifecycle for organization evolution proposals."""

    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    EXECUTED = "executed"
    FAILED = "failed"


class EvolutionInitiatorKind(StrEnum):
    """Actors allowed to submit a proposal without executing it."""

    MAIN_AGENT = "main_agent"
    WORKER = "worker"
    RUNTIME_RESULT = "runtime_result"
    MANAGEMENT_COMMAND = "management_command"
    POLICY_SERVICE = "policy_service"


class EvolutionRiskFlag(StrEnum):
    """Stable risk codes used before any organization evolution is executed."""

    PERMISSION_EXPANSION = "permission_expansion"
    BUDGET_INCREASE = "budget_increase"
    MODEL_TIER_INCREASE = "model_tier_increase"
    EXTERNAL_AGENT = "external_agent"
    SENSITIVE_MEMORY = "sensitive_memory"
    ACTIVE_TASKS = "active_tasks"
    PENDING_HIGH_RISK_APPROVALS = "pending_high_risk_approvals"
    GROUP_CHAT_CLOSURE = "group_chat_closure"
    RESPONSIBILITY_CHANGE = "responsibility_change"


class EvolutionApprovalLevel(StrEnum):
    """Highest approval authority required for an evolution proposal."""

    POLICY_APPROVED = "policy_approved"
    MAIN_AGENT_APPROVAL = "main_agent_approval"
    USER_APPROVAL = "user_approval"


@dataclass(frozen=True)
class EvolutionProposalInitiator:
    """Low-sensitivity reference to the proposal source."""

    kind: EvolutionInitiatorKind | str
    initiator_id: str
    display_name: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _initiator_kind(self.kind))
        _validate_identifier(self.initiator_id, "initiator_id")
        if not isinstance(self.display_name, str):
            raise OrganizationEvolutionError("display_name must be a string")


@dataclass(frozen=True)
class EvolutionRiskContext:
    """Observed risk inputs for policy classification."""

    permission_expands: bool = False
    budget_increases: bool = False
    model_tier_increases: bool = False
    external_agent_involved: bool = False
    sensitive_memory_moves: bool = False
    active_task_refs: tuple[str, ...] = ()
    pending_high_risk_approval_refs: tuple[str, ...] = ()
    group_chat_closes: bool = False
    responsibilities_change: bool = False
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.permission_expands, "permission_expands"),
            (self.budget_increases, "budget_increases"),
            (self.model_tier_increases, "model_tier_increases"),
            (self.external_agent_involved, "external_agent_involved"),
            (self.sensitive_memory_moves, "sensitive_memory_moves"),
            (self.group_chat_closes, "group_chat_closes"),
            (self.responsibilities_change, "responsibilities_change"),
        ):
            if not isinstance(value, bool):
                raise OrganizationEvolutionError(f"{field_name} must be a boolean")
        object.__setattr__(
            self,
            "active_task_refs",
            _relative_ref_tuple(self.active_task_refs, "active_task_refs"),
        )
        object.__setattr__(
            self,
            "pending_high_risk_approval_refs",
            _relative_ref_tuple(
                self.pending_high_risk_approval_refs,
                "pending_high_risk_approval_refs",
            ),
        )
        object.__setattr__(
            self, "source_refs", _relative_ref_tuple(self.source_refs, "source_refs")
        )


@dataclass(frozen=True)
class EvolutionRiskFinding:
    """One audit-safe risk finding with the source that triggered it."""

    flag: EvolutionRiskFlag | str
    reason: str
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "flag", _risk_flag(self.flag))
        _require_string(self.reason, "reason")
        object.__setattr__(
            self, "source_refs", _relative_ref_tuple(self.source_refs, "source_refs")
        )


@dataclass(frozen=True)
class EvolutionApprovalRequirement:
    """Approval requirement summary for UI, audit, or later executors."""

    level: EvolutionApprovalLevel | str
    reasons: tuple[str, ...]
    required_approvers: tuple[str, ...] = ()
    risk_flags: tuple[EvolutionRiskFlag, ...] = ()
    blocking_flags: tuple[EvolutionRiskFlag, ...] = ()
    manual_override_by: str | None = None
    manual_override_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "level", _approval_level(self.level))
        object.__setattr__(self, "reasons", _string_tuple(self.reasons, "reasons"))
        object.__setattr__(
            self,
            "required_approvers",
            _string_tuple(self.required_approvers, "required_approvers"),
        )
        object.__setattr__(
            self,
            "risk_flags",
            tuple(_risk_flag(flag) for flag in self.risk_flags),
        )
        object.__setattr__(
            self,
            "blocking_flags",
            tuple(_risk_flag(flag) for flag in self.blocking_flags),
        )
        if self.manual_override_by is not None:
            _require_string(self.manual_override_by, "manual_override_by")
        if self.manual_override_reason is not None:
            _require_string(self.manual_override_reason, "manual_override_reason")


@dataclass(frozen=True)
class OrganizationEvolutionProposal:
    """Auditable plan for a future organization change.

    The contract stores summaries and references only. It deliberately excludes
    private memory text, raw transcripts, credentials, and direct active-tree
    writes so later executors can consume an approved proposal safely.
    """

    proposal_id: str
    proposal_type: EvolutionProposalType | str
    initiator: EvolutionProposalInitiator
    target_node_ids: tuple[str, ...]
    affected_worker_ids: tuple[str, ...]
    reason: str
    before_summary: str
    after_summary: str
    rollback_summary_ref: str
    status: EvolutionProposalStatus | str = EvolutionProposalStatus.DRAFT
    risk_flags: tuple[str, ...] = ()
    approval_policy: str = "unresolved"
    asset_disposition_refs: tuple[str, ...] = ()
    chat_disposition_refs: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    created_at: str | None = None
    updated_at: str | None = None
    schema_version: int = EVOLUTION_PROPOSAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_schema_version(self.schema_version)
        _validate_identifier(self.proposal_id, "proposal_id")
        object.__setattr__(self, "proposal_type", _proposal_type(self.proposal_type))
        object.__setattr__(self, "status", _proposal_status(self.status))
        if not isinstance(self.initiator, EvolutionProposalInitiator):
            raise OrganizationEvolutionError(
                "initiator must be an EvolutionProposalInitiator"
            )
        object.__setattr__(
            self,
            "target_node_ids",
            tuple(_validate_org_node_reference(node_id) for node_id in self.target_node_ids),
        )
        if not self.target_node_ids:
            raise OrganizationEvolutionError("target_node_ids must not be empty")
        object.__setattr__(
            self,
            "affected_worker_ids",
            tuple(
                _validate_worker_reference(worker_id)
                for worker_id in self.affected_worker_ids
            ),
        )
        for value, field_name in (
            (self.reason, "reason"),
            (self.before_summary, "before_summary"),
            (self.after_summary, "after_summary"),
            (self.rollback_summary_ref, "rollback_summary_ref"),
        ):
            _require_string(value, field_name)
        object.__setattr__(
            self, "risk_flags", _string_tuple(self.risk_flags, "risk_flags")
        )
        _require_string(self.approval_policy, "approval_policy")
        object.__setattr__(
            self,
            "asset_disposition_refs",
            _relative_ref_tuple(self.asset_disposition_refs, "asset_disposition_refs"),
        )
        object.__setattr__(
            self,
            "chat_disposition_refs",
            _relative_ref_tuple(self.chat_disposition_refs, "chat_disposition_refs"),
        )
        object.__setattr__(
            self, "source_refs", _relative_ref_tuple(self.source_refs, "source_refs")
        )
        object.__setattr__(
            self,
            "rollback_summary_ref",
            _validate_relative_ref(self.rollback_summary_ref, "rollback_summary_ref"),
        )
        if self.proposal_type is EvolutionProposalType.TRANSFER_ASSETS:
            if not self.asset_disposition_refs:
                raise OrganizationEvolutionError(
                    "transfer_assets proposals require asset_disposition_refs"
                )
        for value, field_name in (
            (self.created_at, "created_at"),
            (self.updated_at, "updated_at"),
        ):
            if value is not None:
                _require_string(value, field_name)


_INITIATOR_FIELDS = {"kind", "initiator_id", "display_name"}
_PROPOSAL_FIELDS = {
    "proposal_id",
    "proposal_type",
    "schema_version",
    "status",
    "initiator",
    "target_node_ids",
    "affected_worker_ids",
    "reason",
    "before_summary",
    "after_summary",
    "risk_flags",
    "approval_policy",
    "asset_disposition_refs",
    "chat_disposition_refs",
    "rollback_summary_ref",
    "source_refs",
    "created_at",
    "updated_at",
}


def validate_evolution_proposal(
    proposal: OrganizationEvolutionProposal | Mapping[str, Any],
) -> OrganizationEvolutionProposal:
    """Return a validated proposal, rejecting sensitive or malformed payloads."""
    if isinstance(proposal, OrganizationEvolutionProposal):
        data = organization_evolution_proposal_to_dict(proposal)
    else:
        data = proposal
    _reject_sensitive_payload(data, "proposal")
    return organization_evolution_proposal_from_dict(data)


def classify_evolution_risks(
    proposal: OrganizationEvolutionProposal | Mapping[str, Any],
    context: EvolutionRiskContext | None = None,
) -> tuple[EvolutionRiskFinding, ...]:
    """Return risk findings without mutating proposal state."""
    validated = validate_evolution_proposal(proposal)
    risk_context = context or EvolutionRiskContext()
    findings: list[EvolutionRiskFinding] = []

    if risk_context.permission_expands:
        findings.append(
            EvolutionRiskFinding(
                flag=EvolutionRiskFlag.PERMISSION_EXPANSION,
                reason="proposal expands tool or organization permissions",
                source_refs=risk_context.source_refs,
            )
        )
    if risk_context.budget_increases:
        findings.append(
            EvolutionRiskFinding(
                flag=EvolutionRiskFlag.BUDGET_INCREASE,
                reason="proposal increases runtime or spending budget",
                source_refs=risk_context.source_refs,
            )
        )
    if risk_context.model_tier_increases:
        findings.append(
            EvolutionRiskFinding(
                flag=EvolutionRiskFlag.MODEL_TIER_INCREASE,
                reason="proposal increases model capability tier",
                source_refs=risk_context.source_refs,
            )
        )
    if risk_context.external_agent_involved:
        findings.append(
            EvolutionRiskFinding(
                flag=EvolutionRiskFlag.EXTERNAL_AGENT,
                reason="proposal creates or expands an external agent",
                source_refs=risk_context.source_refs,
            )
        )
    if risk_context.sensitive_memory_moves:
        findings.append(
            EvolutionRiskFinding(
                flag=EvolutionRiskFlag.SENSITIVE_MEMORY,
                reason="proposal moves sensitive memory summaries",
                source_refs=risk_context.source_refs,
            )
        )
    if risk_context.active_task_refs:
        findings.append(
            EvolutionRiskFinding(
                flag=EvolutionRiskFlag.ACTIVE_TASKS,
                reason="proposal affects workers or nodes with active tasks",
                source_refs=risk_context.active_task_refs,
            )
        )
    if risk_context.pending_high_risk_approval_refs:
        findings.append(
            EvolutionRiskFinding(
                flag=EvolutionRiskFlag.PENDING_HIGH_RISK_APPROVALS,
                reason="proposal depends on unfinished high-risk approvals",
                source_refs=risk_context.pending_high_risk_approval_refs,
            )
        )
    if risk_context.group_chat_closes:
        findings.append(
            EvolutionRiskFinding(
                flag=EvolutionRiskFlag.GROUP_CHAT_CLOSURE,
                reason="proposal closes or archives an organization group chat",
                source_refs=risk_context.source_refs,
            )
        )
    if risk_context.responsibilities_change:
        findings.append(
            EvolutionRiskFinding(
                flag=EvolutionRiskFlag.RESPONSIBILITY_CHANGE,
                reason="proposal changes durable organization responsibilities",
                source_refs=risk_context.source_refs,
            )
        )

    return tuple(_merge_explicit_risk_flags(validated, findings))


def resolve_approval_requirement(
    proposal: OrganizationEvolutionProposal | Mapping[str, Any],
    risks: tuple[EvolutionRiskFinding, ...],
) -> EvolutionApprovalRequirement:
    """Resolve the highest approval level and execution blockers."""
    validated = validate_evolution_proposal(proposal)
    risk_flags = tuple(finding.flag for finding in risks)
    reasons = tuple(finding.reason for finding in risks)
    blocking_flags = tuple(
        flag for flag in risk_flags if flag in _BLOCKING_RISK_FLAGS
    )
    level = _approval_level_for(validated.proposal_type, risk_flags)
    required_approvers = _required_approvers(level)
    if blocking_flags:
        required_approvers = tuple(dict.fromkeys((*required_approvers, "main_agent")))

    return EvolutionApprovalRequirement(
        level=level,
        reasons=reasons or (_default_approval_reason(validated.proposal_type),),
        required_approvers=required_approvers,
        risk_flags=risk_flags,
        blocking_flags=blocking_flags,
    )


def apply_manual_approval_override(
    requirement: EvolutionApprovalRequirement,
    *,
    level: EvolutionApprovalLevel | str,
    actor: str,
    reason: str,
) -> EvolutionApprovalRequirement:
    """Apply an audit-visible manual override without lowering high-risk reviews."""
    override_level = _approval_level(level)
    if _approval_rank(override_level) < _approval_rank(requirement.level):
        raise OrganizationEvolutionError("manual override cannot lower approval level")
    return replace(
        requirement,
        level=override_level,
        required_approvers=_required_approvers(override_level),
        manual_override_by=_require_string(actor, "actor"),
        manual_override_reason=_require_string(reason, "reason"),
    )


def evolution_proposal_initiator_to_dict(
    initiator: EvolutionProposalInitiator,
) -> dict[str, Any]:
    return {
        "kind": initiator.kind.value,
        "initiator_id": initiator.initiator_id,
        "display_name": initiator.display_name,
    }


def evolution_proposal_initiator_from_dict(
    data: Mapping[str, Any],
) -> EvolutionProposalInitiator:
    data = _require_mapping(data, "initiator")
    _reject_unknown_fields(data, _INITIATOR_FIELDS, "initiator")
    return EvolutionProposalInitiator(
        kind=_require_string(data.get("kind"), "initiator.kind"),
        initiator_id=_require_string(data.get("initiator_id"), "initiator_id"),
        display_name=_string_value(data.get("display_name", ""), "display_name"),
    )


def organization_evolution_proposal_to_dict(
    proposal: OrganizationEvolutionProposal,
) -> dict[str, Any]:
    return {
        "proposal_id": proposal.proposal_id,
        "proposal_type": proposal.proposal_type.value,
        "schema_version": proposal.schema_version,
        "status": proposal.status.value,
        "initiator": evolution_proposal_initiator_to_dict(proposal.initiator),
        "target_node_ids": list(proposal.target_node_ids),
        "affected_worker_ids": list(proposal.affected_worker_ids),
        "reason": proposal.reason,
        "before_summary": proposal.before_summary,
        "after_summary": proposal.after_summary,
        "risk_flags": list(proposal.risk_flags),
        "approval_policy": proposal.approval_policy,
        "asset_disposition_refs": list(proposal.asset_disposition_refs),
        "chat_disposition_refs": list(proposal.chat_disposition_refs),
        "rollback_summary_ref": proposal.rollback_summary_ref,
        "source_refs": list(proposal.source_refs),
        "created_at": proposal.created_at,
        "updated_at": proposal.updated_at,
    }


def organization_evolution_proposal_from_dict(
    data: Mapping[str, Any],
) -> OrganizationEvolutionProposal:
    data = _require_mapping(data, "organization evolution proposal")
    _reject_sensitive_payload(data, "proposal")
    _reject_unknown_fields(data, _PROPOSAL_FIELDS, "organization evolution proposal")
    return OrganizationEvolutionProposal(
        proposal_id=_require_string(data.get("proposal_id"), "proposal_id"),
        proposal_type=_require_string(data.get("proposal_type"), "proposal_type"),
        schema_version=data.get(
            "schema_version", EVOLUTION_PROPOSAL_SCHEMA_VERSION
        ),
        status=data.get("status", EvolutionProposalStatus.DRAFT.value),
        initiator=evolution_proposal_initiator_from_dict(
            _require_mapping(data.get("initiator"), "initiator")
        ),
        target_node_ids=_string_tuple(
            data.get("target_node_ids"), "target_node_ids"
        ),
        affected_worker_ids=_string_tuple(
            data.get("affected_worker_ids", ()), "affected_worker_ids"
        ),
        reason=_require_string(data.get("reason"), "reason"),
        before_summary=_require_string(data.get("before_summary"), "before_summary"),
        after_summary=_require_string(data.get("after_summary"), "after_summary"),
        risk_flags=_string_tuple(data.get("risk_flags", ()), "risk_flags"),
        approval_policy=_require_string(
            data.get("approval_policy", "unresolved"), "approval_policy"
        ),
        asset_disposition_refs=_string_tuple(
            data.get("asset_disposition_refs", ()), "asset_disposition_refs"
        ),
        chat_disposition_refs=_string_tuple(
            data.get("chat_disposition_refs", ()), "chat_disposition_refs"
        ),
        rollback_summary_ref=_require_string(
            data.get("rollback_summary_ref"), "rollback_summary_ref"
        ),
        source_refs=_string_tuple(data.get("source_refs", ()), "source_refs"),
        created_at=_optional_string(data.get("created_at"), "created_at"),
        updated_at=_optional_string(data.get("updated_at"), "updated_at"),
    )


def dump_organization_evolution_proposal_json(
    proposal: OrganizationEvolutionProposal,
) -> str:
    """Dump one evolution proposal as stable, newline-terminated JSON."""
    return json.dumps(organization_evolution_proposal_to_dict(proposal), indent=2) + "\n"


def load_organization_evolution_proposal_json(
    text: str,
) -> OrganizationEvolutionProposal:
    """Load one evolution proposal from JSON text."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OrganizationEvolutionError(
            f"Invalid organization evolution proposal JSON: {exc.msg}"
        ) from exc
    return organization_evolution_proposal_from_dict(data)


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


def _proposal_status(value: EvolutionProposalStatus | str) -> EvolutionProposalStatus:
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


def _initiator_kind(value: EvolutionInitiatorKind | str) -> EvolutionInitiatorKind:
    try:
        return (
            value
            if isinstance(value, EvolutionInitiatorKind)
            else EvolutionInitiatorKind(value)
        )
    except ValueError as exc:
        raise OrganizationEvolutionError(
            f"Unknown evolution initiator kind: {value!r}"
        ) from exc


def _risk_flag(value: EvolutionRiskFlag | str) -> EvolutionRiskFlag:
    try:
        return value if isinstance(value, EvolutionRiskFlag) else EvolutionRiskFlag(value)
    except ValueError as exc:
        raise OrganizationEvolutionError(f"Unknown evolution risk flag: {value!r}") from exc


def _approval_level(value: EvolutionApprovalLevel | str) -> EvolutionApprovalLevel:
    try:
        return (
            value
            if isinstance(value, EvolutionApprovalLevel)
            else EvolutionApprovalLevel(value)
        )
    except ValueError as exc:
        raise OrganizationEvolutionError(
            f"Unknown evolution approval level: {value!r}"
        ) from exc


def _validate_schema_version(value: int) -> None:
    if value != EVOLUTION_PROPOSAL_SCHEMA_VERSION:
        raise OrganizationEvolutionError(
            f"Unsupported evolution proposal schema_version: {value!r}"
        )


def _validate_identifier(value: str, field_name: str) -> str:
    _require_string(value, field_name)
    if _is_path_like(value):
        raise OrganizationEvolutionError(f"{field_name} must be a single path segment")
    return value


def _validate_worker_reference(worker_id: str) -> str:
    try:
        return validate_worker_id(worker_id)
    except WorkerProfileError as exc:
        raise OrganizationEvolutionError(f"affected_worker_ids is invalid: {exc}") from exc


def _validate_org_node_reference(node_id: str) -> str:
    try:
        return validate_org_node_id(node_id)
    except OrganizationError as exc:
        raise OrganizationEvolutionError(f"target_node_ids is invalid: {exc}") from exc


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
        raise OrganizationEvolutionError(f"{field_name} must be a relative reference")
    return value


def _relative_ref_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    return tuple(
        _validate_relative_ref(item, field_name)
        for item in _string_tuple(value, field_name)
    )


def _is_path_like(value: str) -> bool:
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    return (
        value in {".", ".."}
        or "/" in value
        or "\\" in value
        or posix.is_absolute()
        or windows.is_absolute()
        or ".." in posix.parts
        or ".." in windows.parts
    )


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise OrganizationEvolutionError(f"{field_name} must be an object")
    return value


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise OrganizationEvolutionError(f"{field_name} must be a non-empty string")
    return value


def _string_value(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise OrganizationEvolutionError(f"{field_name} must be a string")
    return value


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, field_name)


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


def _reject_sensitive_payload(value: Any, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in SENSITIVE_EVOLUTION_PROPOSAL_FIELDS:
                raise OrganizationEvolutionError(f"{path}.{key_text} contains sensitive data")
            _reject_sensitive_payload(item, f"{path}.{key_text}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_sensitive_payload(item, f"{path}[{index}]")


_USER_APPROVAL_RISK_FLAGS = frozenset(
    {
        EvolutionRiskFlag.PERMISSION_EXPANSION,
        EvolutionRiskFlag.BUDGET_INCREASE,
        EvolutionRiskFlag.MODEL_TIER_INCREASE,
        EvolutionRiskFlag.EXTERNAL_AGENT,
        EvolutionRiskFlag.SENSITIVE_MEMORY,
    }
)
_MAIN_AGENT_REVIEW_RISK_FLAGS = frozenset(
    {
        EvolutionRiskFlag.GROUP_CHAT_CLOSURE,
        EvolutionRiskFlag.RESPONSIBILITY_CHANGE,
    }
)
_BLOCKING_RISK_FLAGS = frozenset(
    {
        EvolutionRiskFlag.ACTIVE_TASKS,
        EvolutionRiskFlag.PENDING_HIGH_RISK_APPROVALS,
    }
)
_MAIN_AGENT_PROPOSAL_TYPES = frozenset(
    {
        EvolutionProposalType.DELETE_CHILD_AGENT,
        EvolutionProposalType.MERGE_DEPARTMENT,
        EvolutionProposalType.TRANSFER_ASSETS,
        EvolutionProposalType.ARCHIVE_ORG_NODE,
    }
)
_APPROVAL_RANK = {
    EvolutionApprovalLevel.POLICY_APPROVED: 0,
    EvolutionApprovalLevel.MAIN_AGENT_APPROVAL: 1,
    EvolutionApprovalLevel.USER_APPROVAL: 2,
}


def _merge_explicit_risk_flags(
    proposal: OrganizationEvolutionProposal,
    findings: list[EvolutionRiskFinding],
) -> tuple[EvolutionRiskFinding, ...]:
    existing = {finding.flag for finding in findings}
    for raw_flag in proposal.risk_flags:
        flag = _risk_flag(raw_flag)
        if flag not in existing:
            findings.append(
                EvolutionRiskFinding(
                    flag=flag,
                    reason=f"proposal declares {flag.value}",
                    source_refs=proposal.source_refs,
                )
            )
            existing.add(flag)
    return tuple(findings)


def _approval_level_for(
    proposal_type: EvolutionProposalType,
    risk_flags: tuple[EvolutionRiskFlag, ...],
) -> EvolutionApprovalLevel:
    if any(flag in _USER_APPROVAL_RISK_FLAGS for flag in risk_flags):
        return EvolutionApprovalLevel.USER_APPROVAL
    if any(flag in _MAIN_AGENT_REVIEW_RISK_FLAGS for flag in risk_flags):
        return EvolutionApprovalLevel.MAIN_AGENT_APPROVAL
    if proposal_type in _MAIN_AGENT_PROPOSAL_TYPES:
        return EvolutionApprovalLevel.MAIN_AGENT_APPROVAL
    return EvolutionApprovalLevel.POLICY_APPROVED


def _required_approvers(level: EvolutionApprovalLevel) -> tuple[str, ...]:
    if level is EvolutionApprovalLevel.USER_APPROVAL:
        return ("user",)
    if level is EvolutionApprovalLevel.MAIN_AGENT_APPROVAL:
        return ("main_agent",)
    return ("policy",)


def _default_approval_reason(proposal_type: EvolutionProposalType) -> str:
    return f"{proposal_type.value} proposal has no high-risk findings"


def _approval_rank(level: EvolutionApprovalLevel) -> int:
    return _APPROVAL_RANK[level]

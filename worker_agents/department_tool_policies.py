"""Department tool policy contracts and safe policy helpers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping

from .organization import validate_org_node_id


DEPARTMENT_TOOL_POLICY_SCHEMA_VERSION = 1

_SENSITIVE_FIELD_NAMES = frozenset(
    {
        "api_key",
        "authorization",
        "complete_transcript",
        "cookie",
        "credential",
        "credentials",
        "env",
        "environment",
        "external_raw_output",
        "full_env",
        "full_transcript",
        "private_key",
        "raw_stderr",
        "raw_stdout",
        "raw_transcript",
        "refresh_token",
        "secret",
        "sensitive_path_content",
        "token",
    }
)


class DepartmentToolPolicyError(ValueError):
    """Raised when a department tool policy crosses a safe boundary."""


class DepartmentToolPolicyState(StrEnum):
    """Lifecycle state of one durable department tool policy."""

    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    DISABLED = "disabled"
    ARCHIVED = "archived"


class DepartmentToolPolicyVisibility(StrEnum):
    """How far a department tool policy can be inherited."""

    DEPARTMENT_ONLY = "department_only"
    INHERITABLE_POLICY = "inheritable_policy"
    ORGANIZATION_POLICY = "organization_policy"


class DepartmentToolRiskLevel(StrEnum):
    """Risk label used before profile checks and approval routing."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    RESTRICTED = "restricted"


class DepartmentToolRuleEffect(StrEnum):
    """Policy effect requested for one tool or tool group."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRES_APPROVAL = "requires_approval"
    REQUIRES_USER_CONFIRMATION = "requires_user_confirmation"


class DepartmentToolInheritanceMode(StrEnum):
    """How a local policy relates to inherited policy decisions."""

    INHERIT = "inherit"
    OVERRIDE_STRICTER = "override_stricter"
    EXTEND_REQUIRES_APPROVAL = "extend_requires_approval"
    LOCAL_ONLY = "local_only"


class DepartmentToolPolicyProposalAction(StrEnum):
    """Requested change carried by a department tool policy proposal."""

    ADD_POLICY = "add_policy"
    TIGHTEN_POLICY = "tighten_policy"
    RELAX_POLICY = "relax_policy"
    DISABLE_POLICY = "disable_policy"
    DEPRECATE_POLICY = "deprecate_policy"


class DepartmentToolPolicyProposalState(StrEnum):
    """Review lifecycle for policy proposals."""

    PENDING = "pending"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


class DepartmentToolPolicyConflictReason(StrEnum):
    """Stable reason codes for policy inheritance and resolution conflicts."""

    APPROVAL_MISSING = "approval_missing"
    LOCAL_RELAXES_PARENT = "local_relaxes_parent"
    PARENT_DENIES_TOOL = "parent_denies_tool"
    WORKSPACE_SCOPE_EXPANDED = "workspace_scope_expanded"
    BUDGET_INCREASED = "budget_increased"
    RISK_LEVEL_LOWERED = "risk_level_lowered"
    APPROVAL_REQUIREMENT_REMOVED = "approval_requirement_removed"


@dataclass(frozen=True)
class DepartmentToolPolicyRecord:
    """Approved or active department tool policy.

    The record intentionally stores only tool references, workspace templates,
    budget hints, and audit metadata. Credentials and live environment details
    must stay outside durable department assets.
    """

    department_id: str
    policy_id: str
    tool_refs: tuple[str, ...]
    effect: DepartmentToolRuleEffect | str
    risk_level: DepartmentToolRiskLevel | str = DepartmentToolRiskLevel.LOW
    state: DepartmentToolPolicyState | str = DepartmentToolPolicyState.ACTIVE
    visibility: DepartmentToolPolicyVisibility | str = (
        DepartmentToolPolicyVisibility.DEPARTMENT_ONLY
    )
    inheritance_mode: DepartmentToolInheritanceMode | str = (
        DepartmentToolInheritanceMode.INHERIT
    )
    workspace_read_roots: tuple[str, ...] = ()
    workspace_write_roots: tuple[str, ...] = ()
    max_task_tokens: int | None = None
    max_turn_tokens: int | None = None
    max_task_cost_usd: float | None = None
    approval_requirement: str = ""
    disabled_conditions: tuple[str, ...] = ()
    owner: str = ""
    source_refs: tuple[str, ...] = ()
    revision: int = 1
    active: bool = True
    accepted_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    audit_summary: str = ""
    schema_version: int = DEPARTMENT_TOOL_POLICY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        validate_org_node_id(self.department_id)
        _validate_identifier(self.policy_id, "policy_id")
        object.__setattr__(
            self,
            "tool_refs",
            tuple(_validate_identifier(value, "tool_refs") for value in self.tool_refs),
        )
        if not self.tool_refs:
            raise DepartmentToolPolicyError("tool_refs must not be empty")
        object.__setattr__(self, "effect", _rule_effect(self.effect))
        object.__setattr__(self, "risk_level", _risk_level(self.risk_level))
        object.__setattr__(self, "state", _policy_state(self.state))
        object.__setattr__(self, "visibility", _visibility(self.visibility))
        object.__setattr__(
            self, "inheritance_mode", _inheritance_mode(self.inheritance_mode)
        )
        object.__setattr__(
            self,
            "workspace_read_roots",
            tuple(
                _validate_relative_ref(value, "workspace_read_roots")
                for value in self.workspace_read_roots
            ),
        )
        object.__setattr__(
            self,
            "workspace_write_roots",
            tuple(
                _validate_relative_ref(value, "workspace_write_roots")
                for value in self.workspace_write_roots
            ),
        )
        _optional_non_negative_int(self.max_task_tokens, "max_task_tokens")
        _optional_non_negative_int(self.max_turn_tokens, "max_turn_tokens")
        _optional_non_negative_float(self.max_task_cost_usd, "max_task_cost_usd")
        _coerce_string_tuple(self, "disabled_conditions")
        object.__setattr__(
            self,
            "source_refs",
            tuple(_validate_relative_ref(value, "source_refs") for value in self.source_refs),
        )
        _require_positive_int(self.revision, "revision")
        if not isinstance(self.active, bool):
            raise DepartmentToolPolicyError("active must be a boolean")
        for value, field_name in (
            (self.approval_requirement, "approval_requirement"),
            (self.owner, "owner"),
            (self.audit_summary, "audit_summary"),
        ):
            _string_value(value, field_name)
        for value, field_name in (
            (self.accepted_at, "accepted_at"),
            (self.created_at, "created_at"),
            (self.updated_at, "updated_at"),
        ):
            if value is not None:
                _require_string(value, field_name)


@dataclass(frozen=True)
class DepartmentToolPolicyProposal:
    """Reviewable candidate for department tool policy changes."""

    proposal_id: str
    department_id: str
    proposed_action: DepartmentToolPolicyProposalAction | str
    tool_refs: tuple[str, ...]
    candidate_effect: DepartmentToolRuleEffect | str
    source_actor: str
    rationale: str
    risk_level: DepartmentToolRiskLevel | str = DepartmentToolRiskLevel.MEDIUM
    visibility: DepartmentToolPolicyVisibility | str = (
        DepartmentToolPolicyVisibility.DEPARTMENT_ONLY
    )
    inheritance_mode: DepartmentToolInheritanceMode | str = (
        DepartmentToolInheritanceMode.INHERIT
    )
    workspace_read_roots: tuple[str, ...] = ()
    workspace_write_roots: tuple[str, ...] = ()
    max_task_tokens: int | None = None
    max_turn_tokens: int | None = None
    max_task_cost_usd: float | None = None
    approval_requirement: str = "department_tool_policy_review"
    disabled_conditions: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    source_hash: str | None = None
    owner: str = ""
    state: DepartmentToolPolicyProposalState | str = (
        DepartmentToolPolicyProposalState.PENDING
    )
    created_at: str | None = None
    updated_at: str | None = None
    audit_summary: str = ""
    schema_version: int = DEPARTMENT_TOOL_POLICY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        _validate_identifier(self.proposal_id, "proposal_id")
        validate_org_node_id(self.department_id)
        object.__setattr__(
            self, "proposed_action", _proposal_action(self.proposed_action)
        )
        object.__setattr__(
            self,
            "tool_refs",
            tuple(_validate_identifier(value, "tool_refs") for value in self.tool_refs),
        )
        if not self.tool_refs:
            raise DepartmentToolPolicyError("tool_refs must not be empty")
        object.__setattr__(self, "candidate_effect", _rule_effect(self.candidate_effect))
        _require_string(self.source_actor, "source_actor")
        _require_string(self.rationale, "rationale")
        object.__setattr__(self, "risk_level", _risk_level(self.risk_level))
        object.__setattr__(self, "visibility", _visibility(self.visibility))
        object.__setattr__(
            self, "inheritance_mode", _inheritance_mode(self.inheritance_mode)
        )
        object.__setattr__(
            self,
            "workspace_read_roots",
            tuple(
                _validate_relative_ref(value, "workspace_read_roots")
                for value in self.workspace_read_roots
            ),
        )
        object.__setattr__(
            self,
            "workspace_write_roots",
            tuple(
                _validate_relative_ref(value, "workspace_write_roots")
                for value in self.workspace_write_roots
            ),
        )
        _optional_non_negative_int(self.max_task_tokens, "max_task_tokens")
        _optional_non_negative_int(self.max_turn_tokens, "max_turn_tokens")
        _optional_non_negative_float(self.max_task_cost_usd, "max_task_cost_usd")
        _coerce_string_tuple(self, "disabled_conditions")
        object.__setattr__(
            self,
            "source_refs",
            tuple(_validate_relative_ref(value, "source_refs") for value in self.source_refs),
        )
        if self.source_hash is not None:
            _require_string(self.source_hash, "source_hash")
        _string_value(self.owner, "owner")
        object.__setattr__(self, "state", _proposal_state(self.state))
        for value, field_name in (
            (self.created_at, "created_at"),
            (self.updated_at, "updated_at"),
        ):
            if value is not None:
                _require_string(value, field_name)
        _string_value(self.audit_summary, "audit_summary")


@dataclass(frozen=True)
class DepartmentToolPolicySnapshot:
    """Credential-free tool policy view for runtime context callers."""

    department_id: str
    allowed_tools: tuple[str, ...] = ()
    denied_tools: tuple[str, ...] = ()
    approval_required_tools: tuple[str, ...] = ()
    user_confirmation_required_tools: tuple[str, ...] = ()
    workspace_read_roots: tuple[str, ...] = ()
    workspace_write_roots: tuple[str, ...] = ()
    max_task_tokens: int | None = None
    max_turn_tokens: int | None = None
    max_task_cost_usd: float | None = None
    policy_refs: tuple[str, ...] = ()
    denial_reasons: tuple[str, ...] = ()
    audit_summary: str = ""
    schema_version: int = DEPARTMENT_TOOL_POLICY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        validate_org_node_id(self.department_id)
        for field_name in (
            "allowed_tools",
            "denied_tools",
            "approval_required_tools",
            "user_confirmation_required_tools",
            "denial_reasons",
        ):
            _coerce_string_tuple(self, field_name)
        object.__setattr__(
            self,
            "workspace_read_roots",
            tuple(
                _validate_relative_ref(value, "workspace_read_roots")
                for value in self.workspace_read_roots
            ),
        )
        object.__setattr__(
            self,
            "workspace_write_roots",
            tuple(
                _validate_relative_ref(value, "workspace_write_roots")
                for value in self.workspace_write_roots
            ),
        )
        _optional_non_negative_int(self.max_task_tokens, "max_task_tokens")
        _optional_non_negative_int(self.max_turn_tokens, "max_turn_tokens")
        _optional_non_negative_float(self.max_task_cost_usd, "max_task_cost_usd")
        object.__setattr__(
            self,
            "policy_refs",
            tuple(_validate_relative_ref(value, "policy_refs") for value in self.policy_refs),
        )
        _string_value(self.audit_summary, "audit_summary")


@dataclass(frozen=True)
class DepartmentToolPolicyResolutionInput:
    """Read-only policy inputs for one department policy resolution."""

    target_department_id: str
    policies: tuple[DepartmentToolPolicyRecord, ...]
    inherited_department_ids: tuple[str, ...] = ()
    task_constraints: tuple[DepartmentToolPolicyRecord, ...] = ()
    approved_relaxation_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        validate_org_node_id(self.target_department_id)
        if any(not isinstance(policy, DepartmentToolPolicyRecord) for policy in self.policies):
            raise DepartmentToolPolicyError(
                "policies must contain DepartmentToolPolicyRecord values"
            )
        if any(
            not isinstance(policy, DepartmentToolPolicyRecord)
            for policy in self.task_constraints
        ):
            raise DepartmentToolPolicyError(
                "task_constraints must contain DepartmentToolPolicyRecord values"
            )
        object.__setattr__(
            self,
            "inherited_department_ids",
            tuple(
                validate_org_node_id(department_id)
                for department_id in self.inherited_department_ids
            ),
        )
        object.__setattr__(
            self,
            "approved_relaxation_refs",
            tuple(
                _validate_relative_ref(ref, "approved_relaxation_refs")
                for ref in self.approved_relaxation_refs
            ),
        )


@dataclass(frozen=True)
class DepartmentToolPolicyConflict:
    """Audit-safe conflict produced during inheritance resolution."""

    tool_ref: str
    policy_id: str
    reason: DepartmentToolPolicyConflictReason | str
    audit_summary: str

    def __post_init__(self) -> None:
        _validate_identifier(self.tool_ref, "tool_ref")
        _validate_identifier(self.policy_id, "policy_id")
        object.__setattr__(self, "reason", _conflict_reason(self.reason))
        _require_string(self.audit_summary, "audit_summary")


@dataclass(frozen=True)
class ResolvedDepartmentToolPolicy:
    """Resolved department policy before worker profile cross-checking."""

    snapshot: DepartmentToolPolicySnapshot
    conflicts: tuple[DepartmentToolPolicyConflict, ...] = ()
    blocked_relaxation_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, DepartmentToolPolicySnapshot):
            raise DepartmentToolPolicyError("snapshot must be a DepartmentToolPolicySnapshot")
        if any(not isinstance(conflict, DepartmentToolPolicyConflict) for conflict in self.conflicts):
            raise DepartmentToolPolicyError(
                "conflicts must contain DepartmentToolPolicyConflict values"
            )
        object.__setattr__(
            self,
            "blocked_relaxation_refs",
            tuple(
                _validate_relative_ref(ref, "blocked_relaxation_refs")
                for ref in self.blocked_relaxation_refs
            ),
        )


def validate_department_tool_policy_payload(payload: Mapping[str, Any]) -> None:
    """Reject secrets, credentials, raw transcripts, and raw external output."""

    _reject_sensitive_payload(payload, "payload")


def department_tool_policy_dir(
    worker_agents_home: str | Path, department_id: str
) -> Path:
    """Return the durable department tool policy root without creating it."""

    validate_org_node_id(department_id)
    return (
        Path(worker_agents_home)
        / "organization"
        / "departments"
        / department_id
        / "policies"
        / "tools"
    )


def department_tool_policy_to_dict(
    policy: DepartmentToolPolicyRecord,
) -> dict[str, Any]:
    """Return a deterministic JSON-ready active department tool policy."""

    return {
        "department_id": policy.department_id,
        "policy_id": policy.policy_id,
        "schema_version": policy.schema_version,
        "tool_refs": list(policy.tool_refs),
        "effect": policy.effect.value,
        "risk_level": policy.risk_level.value,
        "state": policy.state.value,
        "visibility": policy.visibility.value,
        "inheritance_mode": policy.inheritance_mode.value,
        "workspace_read_roots": list(policy.workspace_read_roots),
        "workspace_write_roots": list(policy.workspace_write_roots),
        "max_task_tokens": policy.max_task_tokens,
        "max_turn_tokens": policy.max_turn_tokens,
        "max_task_cost_usd": policy.max_task_cost_usd,
        "approval_requirement": policy.approval_requirement,
        "disabled_conditions": list(policy.disabled_conditions),
        "owner": policy.owner,
        "source_refs": list(policy.source_refs),
        "revision": policy.revision,
        "active": policy.active,
        "accepted_at": policy.accepted_at,
        "created_at": policy.created_at,
        "updated_at": policy.updated_at,
        "audit_summary": policy.audit_summary,
    }


def department_tool_policy_from_dict(
    data: Mapping[str, Any],
) -> DepartmentToolPolicyRecord:
    """Load an active department tool policy after boundary validation."""

    data = _require_mapping(data, "department tool policy")
    _reject_unknown_fields(data, _POLICY_FIELDS, "department tool policy")
    return DepartmentToolPolicyRecord(
        department_id=_require_string(data.get("department_id"), "department_id"),
        policy_id=_require_string(data.get("policy_id"), "policy_id"),
        schema_version=data.get(
            "schema_version", DEPARTMENT_TOOL_POLICY_SCHEMA_VERSION
        ),
        tool_refs=_string_tuple(data.get("tool_refs", ()), "tool_refs"),
        effect=_require_string(data.get("effect"), "effect"),
        risk_level=data.get("risk_level", DepartmentToolRiskLevel.LOW),
        state=data.get("state", DepartmentToolPolicyState.ACTIVE),
        visibility=data.get(
            "visibility", DepartmentToolPolicyVisibility.DEPARTMENT_ONLY
        ),
        inheritance_mode=data.get(
            "inheritance_mode", DepartmentToolInheritanceMode.INHERIT
        ),
        workspace_read_roots=_string_tuple(
            data.get("workspace_read_roots", ()), "workspace_read_roots"
        ),
        workspace_write_roots=_string_tuple(
            data.get("workspace_write_roots", ()), "workspace_write_roots"
        ),
        max_task_tokens=_optional_int(data.get("max_task_tokens"), "max_task_tokens"),
        max_turn_tokens=_optional_int(data.get("max_turn_tokens"), "max_turn_tokens"),
        max_task_cost_usd=_optional_float(
            data.get("max_task_cost_usd"), "max_task_cost_usd"
        ),
        approval_requirement=_string_value(
            data.get("approval_requirement", ""), "approval_requirement"
        ),
        disabled_conditions=_string_tuple(
            data.get("disabled_conditions", ()), "disabled_conditions"
        ),
        owner=_string_value(data.get("owner", ""), "owner"),
        source_refs=_string_tuple(data.get("source_refs", ()), "source_refs"),
        revision=data.get("revision", 1),
        active=data.get("active", True),
        accepted_at=_optional_string(data.get("accepted_at"), "accepted_at"),
        created_at=_optional_string(data.get("created_at"), "created_at"),
        updated_at=_optional_string(data.get("updated_at"), "updated_at"),
        audit_summary=_string_value(data.get("audit_summary", ""), "audit_summary"),
    )


def department_tool_policy_proposal_to_dict(
    proposal: DepartmentToolPolicyProposal,
) -> dict[str, Any]:
    """Return a deterministic JSON-ready department tool policy proposal."""

    return {
        "proposal_id": proposal.proposal_id,
        "department_id": proposal.department_id,
        "schema_version": proposal.schema_version,
        "proposed_action": proposal.proposed_action.value,
        "tool_refs": list(proposal.tool_refs),
        "candidate_effect": proposal.candidate_effect.value,
        "source_actor": proposal.source_actor,
        "rationale": proposal.rationale,
        "risk_level": proposal.risk_level.value,
        "visibility": proposal.visibility.value,
        "inheritance_mode": proposal.inheritance_mode.value,
        "workspace_read_roots": list(proposal.workspace_read_roots),
        "workspace_write_roots": list(proposal.workspace_write_roots),
        "max_task_tokens": proposal.max_task_tokens,
        "max_turn_tokens": proposal.max_turn_tokens,
        "max_task_cost_usd": proposal.max_task_cost_usd,
        "approval_requirement": proposal.approval_requirement,
        "disabled_conditions": list(proposal.disabled_conditions),
        "source_refs": list(proposal.source_refs),
        "source_hash": proposal.source_hash,
        "owner": proposal.owner,
        "state": proposal.state.value,
        "created_at": proposal.created_at,
        "updated_at": proposal.updated_at,
        "audit_summary": proposal.audit_summary,
    }


def department_tool_policy_proposal_from_dict(
    data: Mapping[str, Any],
) -> DepartmentToolPolicyProposal:
    """Load a department tool policy proposal after boundary validation."""

    data = _require_mapping(data, "department tool policy proposal")
    _reject_unknown_fields(data, _PROPOSAL_FIELDS, "department tool policy proposal")
    return DepartmentToolPolicyProposal(
        proposal_id=_require_string(data.get("proposal_id"), "proposal_id"),
        department_id=_require_string(data.get("department_id"), "department_id"),
        schema_version=data.get(
            "schema_version", DEPARTMENT_TOOL_POLICY_SCHEMA_VERSION
        ),
        proposed_action=_require_string(data.get("proposed_action"), "proposed_action"),
        tool_refs=_string_tuple(data.get("tool_refs", ()), "tool_refs"),
        candidate_effect=_require_string(data.get("candidate_effect"), "candidate_effect"),
        source_actor=_require_string(data.get("source_actor"), "source_actor"),
        rationale=_require_string(data.get("rationale"), "rationale"),
        risk_level=data.get("risk_level", DepartmentToolRiskLevel.MEDIUM),
        visibility=data.get(
            "visibility", DepartmentToolPolicyVisibility.DEPARTMENT_ONLY
        ),
        inheritance_mode=data.get(
            "inheritance_mode", DepartmentToolInheritanceMode.INHERIT
        ),
        workspace_read_roots=_string_tuple(
            data.get("workspace_read_roots", ()), "workspace_read_roots"
        ),
        workspace_write_roots=_string_tuple(
            data.get("workspace_write_roots", ()), "workspace_write_roots"
        ),
        max_task_tokens=_optional_int(data.get("max_task_tokens"), "max_task_tokens"),
        max_turn_tokens=_optional_int(data.get("max_turn_tokens"), "max_turn_tokens"),
        max_task_cost_usd=_optional_float(
            data.get("max_task_cost_usd"), "max_task_cost_usd"
        ),
        approval_requirement=_require_string(
            data.get("approval_requirement"), "approval_requirement"
        ),
        disabled_conditions=_string_tuple(
            data.get("disabled_conditions", ()), "disabled_conditions"
        ),
        source_refs=_string_tuple(data.get("source_refs", ()), "source_refs"),
        source_hash=_optional_string(data.get("source_hash"), "source_hash"),
        owner=_string_value(data.get("owner", ""), "owner"),
        state=data.get("state", DepartmentToolPolicyProposalState.PENDING),
        created_at=_optional_string(data.get("created_at"), "created_at"),
        updated_at=_optional_string(data.get("updated_at"), "updated_at"),
        audit_summary=_string_value(data.get("audit_summary", ""), "audit_summary"),
    )


def department_tool_policy_snapshot_to_dict(
    snapshot: DepartmentToolPolicySnapshot,
) -> dict[str, Any]:
    """Return a credential-free tool policy snapshot for context builders."""

    return {
        "department_id": snapshot.department_id,
        "schema_version": snapshot.schema_version,
        "allowed_tools": list(snapshot.allowed_tools),
        "denied_tools": list(snapshot.denied_tools),
        "approval_required_tools": list(snapshot.approval_required_tools),
        "user_confirmation_required_tools": list(
            snapshot.user_confirmation_required_tools
        ),
        "workspace_read_roots": list(snapshot.workspace_read_roots),
        "workspace_write_roots": list(snapshot.workspace_write_roots),
        "max_task_tokens": snapshot.max_task_tokens,
        "max_turn_tokens": snapshot.max_turn_tokens,
        "max_task_cost_usd": snapshot.max_task_cost_usd,
        "policy_refs": list(snapshot.policy_refs),
        "denial_reasons": list(snapshot.denial_reasons),
        "audit_summary": snapshot.audit_summary,
    }


def resolve_department_tool_policies(
    request: DepartmentToolPolicyResolutionInput,
) -> ResolvedDepartmentToolPolicy:
    """Resolve department policies with conservative inheritance rules."""

    decisions: dict[str, _ResolvedToolDecision] = {}
    conflicts: list[DepartmentToolPolicyConflict] = []
    blocked_relaxation_refs: list[str] = []
    policy_refs: list[str] = []

    for policy in _resolution_order(request):
        if not _policy_participates(policy, request):
            continue
        policy_refs.append(_policy_ref(policy))
        for tool_ref in policy.tool_refs:
            existing = decisions.get(tool_ref)
            if existing is None:
                decisions[tool_ref] = _decision_from_policy(policy)
                continue
            if _is_relaxation(existing.policy, policy):
                if _policy_is_approved(policy, request.approved_relaxation_refs):
                    decisions[tool_ref] = _decision_from_policy(policy)
                    continue
                reasons = _relaxation_reasons(existing.policy, policy)
                blocked_relaxation_refs.append(_policy_ref(policy))
                for reason in reasons:
                    conflicts.append(
                        DepartmentToolPolicyConflict(
                            tool_ref=tool_ref,
                            policy_id=policy.policy_id,
                            reason=reason,
                            audit_summary=(
                                f"Policy {policy.policy_id} relaxes "
                                f"{existing.policy.policy_id} without approval."
                            ),
                        )
                    )
                continue
            if _is_stricter(policy, existing.policy):
                decisions[tool_ref] = _decision_from_policy(policy)

    allowed: list[str] = []
    denied: list[str] = []
    approval_required: list[str] = []
    user_confirmation_required: list[str] = []
    read_roots: list[str] = []
    write_roots: list[str] = []
    max_task_tokens: int | None = None
    max_turn_tokens: int | None = None
    max_task_cost_usd: float | None = None

    for tool_ref, decision in sorted(decisions.items()):
        if decision.effect is DepartmentToolRuleEffect.DENY:
            denied.append(tool_ref)
        elif decision.effect is DepartmentToolRuleEffect.REQUIRES_APPROVAL:
            approval_required.append(tool_ref)
        elif decision.effect is DepartmentToolRuleEffect.REQUIRES_USER_CONFIRMATION:
            user_confirmation_required.append(tool_ref)
        else:
            allowed.append(tool_ref)
        read_roots.extend(decision.policy.workspace_read_roots)
        write_roots.extend(decision.policy.workspace_write_roots)
        max_task_tokens = _strictest_optional_int(
            max_task_tokens, decision.policy.max_task_tokens
        )
        max_turn_tokens = _strictest_optional_int(
            max_turn_tokens, decision.policy.max_turn_tokens
        )
        max_task_cost_usd = _strictest_optional_float(
            max_task_cost_usd, decision.policy.max_task_cost_usd
        )

    snapshot = DepartmentToolPolicySnapshot(
        department_id=request.target_department_id,
        allowed_tools=tuple(allowed),
        denied_tools=tuple(denied),
        approval_required_tools=tuple(approval_required),
        user_confirmation_required_tools=tuple(user_confirmation_required),
        workspace_read_roots=_unique_tuple(read_roots),
        workspace_write_roots=_unique_tuple(write_roots),
        max_task_tokens=max_task_tokens,
        max_turn_tokens=max_turn_tokens,
        max_task_cost_usd=max_task_cost_usd,
        policy_refs=_unique_tuple(policy_refs),
        denial_reasons=tuple(conflict.reason.value for conflict in conflicts),
        audit_summary="Resolved department tool policies without executing tools.",
    )
    return ResolvedDepartmentToolPolicy(
        snapshot=snapshot,
        conflicts=tuple(conflicts),
        blocked_relaxation_refs=_unique_tuple(blocked_relaxation_refs),
    )


def resolved_department_tool_policy_to_dict(
    resolved: ResolvedDepartmentToolPolicy,
) -> dict[str, Any]:
    """Return a JSON-safe resolved policy with stable conflict reasons."""

    return {
        "snapshot": department_tool_policy_snapshot_to_dict(resolved.snapshot),
        "conflicts": [
            {
                "tool_ref": conflict.tool_ref,
                "policy_id": conflict.policy_id,
                "reason": conflict.reason.value,
                "audit_summary": conflict.audit_summary,
            }
            for conflict in resolved.conflicts
        ],
        "blocked_relaxation_refs": list(resolved.blocked_relaxation_refs),
    }


_POLICY_FIELDS = {
    "department_id",
    "policy_id",
    "schema_version",
    "tool_refs",
    "effect",
    "risk_level",
    "state",
    "visibility",
    "inheritance_mode",
    "workspace_read_roots",
    "workspace_write_roots",
    "max_task_tokens",
    "max_turn_tokens",
    "max_task_cost_usd",
    "approval_requirement",
    "disabled_conditions",
    "owner",
    "source_refs",
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
    "proposed_action",
    "tool_refs",
    "candidate_effect",
    "source_actor",
    "rationale",
    "risk_level",
    "visibility",
    "inheritance_mode",
    "workspace_read_roots",
    "workspace_write_roots",
    "max_task_tokens",
    "max_turn_tokens",
    "max_task_cost_usd",
    "approval_requirement",
    "disabled_conditions",
    "source_refs",
    "source_hash",
    "owner",
    "state",
    "created_at",
    "updated_at",
    "audit_summary",
}


def _require_schema_version(schema_version: int) -> None:
    if schema_version != DEPARTMENT_TOOL_POLICY_SCHEMA_VERSION:
        raise DepartmentToolPolicyError(
            f"Unsupported department tool policy schema_version: {schema_version!r}"
        )


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise DepartmentToolPolicyError(f"{field_name} must be a non-empty string")
    return value


def _string_value(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise DepartmentToolPolicyError(f"{field_name} must be a string")
    return value


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, field_name)


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise DepartmentToolPolicyError(f"{field_name} must be a list of strings")
    return tuple(_require_string(item, field_name) for item in value)


def _coerce_string_tuple(instance: object, field_name: str) -> None:
    object.__setattr__(
        instance,
        field_name,
        tuple(_require_string(item, field_name) for item in getattr(instance, field_name)),
    )


def _optional_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    return _optional_non_negative_int(value, field_name)


def _optional_float(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    return _optional_non_negative_float(value, field_name)


def _optional_non_negative_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DepartmentToolPolicyError(f"{field_name} must be a non-negative integer")
    return value


def _optional_non_negative_float(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise DepartmentToolPolicyError(f"{field_name} must be a non-negative number")
    return float(value)


def _require_positive_int(value: Any, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DepartmentToolPolicyError(f"{field_name} must be a positive integer")


def _validate_identifier(value: str, field_name: str) -> str:
    _require_string(value, field_name)
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise DepartmentToolPolicyError(f"{field_name} must be a single path segment")
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
        raise DepartmentToolPolicyError(f"{field_name} must stay within allowed storage")
    return value


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DepartmentToolPolicyError(f"{field_name} must be an object")
    return value


def _reject_unknown_fields(
    data: Mapping[str, Any], allowed_fields: set[str], field_name: str
) -> None:
    unknown_fields = sorted(set(data) - allowed_fields)
    if unknown_fields:
        joined = ", ".join(unknown_fields)
        raise DepartmentToolPolicyError(f"{field_name} has unknown fields: {joined}")


def _policy_state(value: DepartmentToolPolicyState | str) -> DepartmentToolPolicyState:
    try:
        return (
            value
            if isinstance(value, DepartmentToolPolicyState)
            else DepartmentToolPolicyState(value)
        )
    except ValueError as exc:
        raise DepartmentToolPolicyError(
            f"Unknown department tool policy state: {value!r}"
        ) from exc


def _visibility(
    value: DepartmentToolPolicyVisibility | str,
) -> DepartmentToolPolicyVisibility:
    try:
        return (
            value
            if isinstance(value, DepartmentToolPolicyVisibility)
            else DepartmentToolPolicyVisibility(value)
        )
    except ValueError as exc:
        raise DepartmentToolPolicyError(
            f"Unknown department tool policy visibility: {value!r}"
        ) from exc


def _risk_level(value: DepartmentToolRiskLevel | str) -> DepartmentToolRiskLevel:
    try:
        return (
            value
            if isinstance(value, DepartmentToolRiskLevel)
            else DepartmentToolRiskLevel(value)
        )
    except ValueError as exc:
        raise DepartmentToolPolicyError(
            f"Unknown department tool risk level: {value!r}"
        ) from exc


def _rule_effect(value: DepartmentToolRuleEffect | str) -> DepartmentToolRuleEffect:
    try:
        return (
            value
            if isinstance(value, DepartmentToolRuleEffect)
            else DepartmentToolRuleEffect(value)
        )
    except ValueError as exc:
        raise DepartmentToolPolicyError(
            f"Unknown department tool rule effect: {value!r}"
        ) from exc


def _inheritance_mode(
    value: DepartmentToolInheritanceMode | str,
) -> DepartmentToolInheritanceMode:
    try:
        return (
            value
            if isinstance(value, DepartmentToolInheritanceMode)
            else DepartmentToolInheritanceMode(value)
        )
    except ValueError as exc:
        raise DepartmentToolPolicyError(
            f"Unknown department tool inheritance mode: {value!r}"
        ) from exc


def _proposal_action(
    value: DepartmentToolPolicyProposalAction | str,
) -> DepartmentToolPolicyProposalAction:
    try:
        return (
            value
            if isinstance(value, DepartmentToolPolicyProposalAction)
            else DepartmentToolPolicyProposalAction(value)
        )
    except ValueError as exc:
        raise DepartmentToolPolicyError(
            f"Unknown department tool proposal action: {value!r}"
        ) from exc


def _proposal_state(
    value: DepartmentToolPolicyProposalState | str,
) -> DepartmentToolPolicyProposalState:
    try:
        return (
            value
            if isinstance(value, DepartmentToolPolicyProposalState)
            else DepartmentToolPolicyProposalState(value)
        )
    except ValueError as exc:
        raise DepartmentToolPolicyError(
            f"Unknown department tool proposal state: {value!r}"
        ) from exc


def _conflict_reason(
    value: DepartmentToolPolicyConflictReason | str,
) -> DepartmentToolPolicyConflictReason:
    try:
        return (
            value
            if isinstance(value, DepartmentToolPolicyConflictReason)
            else DepartmentToolPolicyConflictReason(value)
        )
    except ValueError as exc:
        raise DepartmentToolPolicyError(
            f"Unknown department tool policy conflict reason: {value!r}"
        ) from exc


def _reject_sensitive_payload(value: Any, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in _SENSITIVE_FIELD_NAMES:
                raise DepartmentToolPolicyError(
                    f"{path}.{key_text} contains sensitive data"
                )
            _reject_sensitive_payload(item, f"{path}.{key_text}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_sensitive_payload(item, f"{path}[{index}]")


@dataclass(frozen=True)
class _ResolvedToolDecision:
    policy: DepartmentToolPolicyRecord
    effect: DepartmentToolRuleEffect


_EFFECT_STRICTNESS = {
    DepartmentToolRuleEffect.ALLOW: 0,
    DepartmentToolRuleEffect.REQUIRES_APPROVAL: 1,
    DepartmentToolRuleEffect.REQUIRES_USER_CONFIRMATION: 2,
    DepartmentToolRuleEffect.DENY: 3,
}

_RISK_STRICTNESS = {
    DepartmentToolRiskLevel.LOW: 0,
    DepartmentToolRiskLevel.MEDIUM: 1,
    DepartmentToolRiskLevel.HIGH: 2,
    DepartmentToolRiskLevel.RESTRICTED: 3,
}


def _resolution_order(
    request: DepartmentToolPolicyResolutionInput,
) -> tuple[DepartmentToolPolicyRecord, ...]:
    inherited = tuple(
        policy
        for department_id in request.inherited_department_ids
        for policy in request.policies
        if policy.department_id == department_id
    )
    local = tuple(
        policy
        for policy in request.policies
        if policy.department_id == request.target_department_id
    )
    return inherited + local + request.task_constraints


def _policy_participates(
    policy: DepartmentToolPolicyRecord, request: DepartmentToolPolicyResolutionInput
) -> bool:
    if not policy.active or policy.state in {
        DepartmentToolPolicyState.ARCHIVED,
        DepartmentToolPolicyState.DRAFT,
    }:
        return False
    if policy.state is DepartmentToolPolicyState.DISABLED:
        return True
    if policy.department_id == request.target_department_id:
        return True
    return policy.visibility in {
        DepartmentToolPolicyVisibility.INHERITABLE_POLICY,
        DepartmentToolPolicyVisibility.ORGANIZATION_POLICY,
    }


def _decision_from_policy(policy: DepartmentToolPolicyRecord) -> _ResolvedToolDecision:
    effect = (
        DepartmentToolRuleEffect.DENY
        if policy.state is DepartmentToolPolicyState.DISABLED
        else policy.effect
    )
    return _ResolvedToolDecision(policy=policy, effect=effect)


def _is_relaxation(
    current: DepartmentToolPolicyRecord, candidate: DepartmentToolPolicyRecord
) -> bool:
    return bool(_relaxation_reasons(current, candidate))


def _relaxation_reasons(
    current: DepartmentToolPolicyRecord, candidate: DepartmentToolPolicyRecord
) -> tuple[DepartmentToolPolicyConflictReason, ...]:
    reasons: list[DepartmentToolPolicyConflictReason] = []
    if (
        current.effect is DepartmentToolRuleEffect.DENY
        and candidate.effect is not DepartmentToolRuleEffect.DENY
    ):
        reasons.append(DepartmentToolPolicyConflictReason.PARENT_DENIES_TOOL)
    if _EFFECT_STRICTNESS[candidate.effect] < _EFFECT_STRICTNESS[current.effect]:
        reasons.append(DepartmentToolPolicyConflictReason.APPROVAL_REQUIREMENT_REMOVED)
    if _RISK_STRICTNESS[candidate.risk_level] < _RISK_STRICTNESS[current.risk_level]:
        reasons.append(DepartmentToolPolicyConflictReason.RISK_LEVEL_LOWERED)
    if _expands_scope(candidate.workspace_read_roots, current.workspace_read_roots):
        reasons.append(DepartmentToolPolicyConflictReason.WORKSPACE_SCOPE_EXPANDED)
    if _expands_scope(candidate.workspace_write_roots, current.workspace_write_roots):
        reasons.append(DepartmentToolPolicyConflictReason.WORKSPACE_SCOPE_EXPANDED)
    if _raises_optional_int(candidate.max_task_tokens, current.max_task_tokens):
        reasons.append(DepartmentToolPolicyConflictReason.BUDGET_INCREASED)
    if _raises_optional_int(candidate.max_turn_tokens, current.max_turn_tokens):
        reasons.append(DepartmentToolPolicyConflictReason.BUDGET_INCREASED)
    if _raises_optional_float(candidate.max_task_cost_usd, current.max_task_cost_usd):
        reasons.append(DepartmentToolPolicyConflictReason.BUDGET_INCREASED)
    if reasons and DepartmentToolPolicyConflictReason.PARENT_DENIES_TOOL not in reasons:
        reasons.insert(0, DepartmentToolPolicyConflictReason.LOCAL_RELAXES_PARENT)
    if reasons:
        reasons.append(DepartmentToolPolicyConflictReason.APPROVAL_MISSING)
    return tuple(dict.fromkeys(reasons))


def _is_stricter(
    candidate: DepartmentToolPolicyRecord, current: DepartmentToolPolicyRecord
) -> bool:
    if _EFFECT_STRICTNESS[candidate.effect] > _EFFECT_STRICTNESS[current.effect]:
        return True
    if _RISK_STRICTNESS[candidate.risk_level] > _RISK_STRICTNESS[current.risk_level]:
        return True
    if _narrows_scope(candidate.workspace_read_roots, current.workspace_read_roots):
        return True
    if _narrows_scope(candidate.workspace_write_roots, current.workspace_write_roots):
        return True
    return (
        _lowers_optional_int(candidate.max_task_tokens, current.max_task_tokens)
        or _lowers_optional_int(candidate.max_turn_tokens, current.max_turn_tokens)
        or _lowers_optional_float(
            candidate.max_task_cost_usd, current.max_task_cost_usd
        )
    )


def _policy_is_approved(
    policy: DepartmentToolPolicyRecord, approved_refs: tuple[str, ...]
) -> bool:
    refs = {_policy_ref(policy), policy.policy_id}
    return bool(refs.intersection(approved_refs))


def _policy_ref(policy: DepartmentToolPolicyRecord) -> str:
    return f"{policy.department_id}/{policy.policy_id}"


def _expands_scope(candidate: tuple[str, ...], current: tuple[str, ...]) -> bool:
    return bool(candidate) and not set(candidate).issubset(set(current))


def _narrows_scope(candidate: tuple[str, ...], current: tuple[str, ...]) -> bool:
    return bool(current) and bool(candidate) and set(candidate).issubset(set(current))


def _raises_optional_int(candidate: int | None, current: int | None) -> bool:
    if candidate is None:
        return False
    return current is None or candidate > current


def _raises_optional_float(candidate: float | None, current: float | None) -> bool:
    if candidate is None:
        return False
    return current is None or candidate > current


def _lowers_optional_int(candidate: int | None, current: int | None) -> bool:
    return candidate is not None and current is not None and candidate < current


def _lowers_optional_float(candidate: float | None, current: float | None) -> bool:
    return candidate is not None and current is not None and candidate < current


def _strictest_optional_int(current: int | None, candidate: int | None) -> int | None:
    if current is None:
        return candidate
    if candidate is None:
        return current
    return min(current, candidate)


def _strictest_optional_float(
    current: float | None, candidate: float | None
) -> float | None:
    if current is None:
        return candidate
    if candidate is None:
        return current
    return min(current, candidate)


def _unique_tuple(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))

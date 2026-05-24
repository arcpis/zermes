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
CHILD_AGENT_LIFECYCLE_SCHEMA_VERSION = 1

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


class ChildAgentNodeKind(StrEnum):
    """Durable organization node kinds that can be proposed for creation."""

    WORKER = "worker"
    DEPARTMENT = "department"
    TEAM = "team"
    ROLE = "role"


class ChildAgentRuntimeKind(StrEnum):
    """Runtime identity for a proposed durable child agent."""

    INTERNAL_WORKER = "internal_worker"
    EXTERNAL_AGENT = "external_agent"
    ORGANIZATION_ONLY = "organization_only"


class ChildAgentChatPolicy(StrEnum):
    """Default chat handling for a proposed child agent or node."""

    DIRECT_USER_CHAT = "direct_user_chat"
    PARENT_GROUP_CHAT = "parent_group_chat"
    DEPARTMENT_GROUP_CANDIDATE = "department_group_candidate"
    NONE = "none"


class ChildAgentDeletionMode(StrEnum):
    """Allowed non-destructive lifecycle outcomes for a child agent deletion plan."""

    ARCHIVE = "archive"
    REMOVE_FROM_ACTIVE_TREE = "remove_from_active_tree"
    DEPRECATE = "deprecate"


class ChildAgentDeleteBlockingCheck(StrEnum):
    """Pre-execution blockers that must be cleared before deletion."""

    ACTIVE_TASKS = "active_tasks"
    PENDING_APPROVALS = "pending_approvals"
    CHILD_NODES = "child_nodes"
    RUNNING_SESSIONS = "running_sessions"
    ASSET_DISPOSITION_MISSING = "asset_disposition_missing"
    CHAT_DISPOSITION_MISSING = "chat_disposition_missing"


class ChildAgentPrivateAssetDisposition(StrEnum):
    """Permitted private asset disposition for a removed durable child agent."""

    ARCHIVE = "archive"
    TRANSFER_BY_PROPOSAL = "transfer_by_proposal"


class ChildAgentReplacementOwnerKind(StrEnum):
    """Where responsibility moves after a child agent or org node is removed."""

    ORG_NODE = "org_node"
    WORKER = "worker"
    MAIN_AGENT = "main_agent"
    USER = "user"
    NO_REPLACEMENT = "no_replacement"


class DepartmentMergePlanStatus(StrEnum):
    """Review and execution state for a department merge plan."""

    DRAFT = "draft"
    BLOCKED = "blocked"
    READY_FOR_APPROVAL = "ready_for_approval"
    APPROVED = "approved"
    EXECUTED = "executed"


class DepartmentContractionMode(StrEnum):
    """Post-deletion organization contraction outcome."""

    KEEP_DEPARTMENT = "keep_department"
    KEEP_SINGLE_WORKER_DEPARTMENT = "keep_single_worker_department"
    REMOVE_EMPTY_CHILD_DEPARTMENT = "remove_empty_child_department"
    ARCHIVE_NODE = "archive_node"
    REBIND_CHAT_TO_PARENT = "rebind_chat_to_parent"


class DepartmentCollaborationSurface(StrEnum):
    """Where remaining department collaboration should happen after contraction."""

    DEPARTMENT_GROUP_CHAT = "department_group_chat"
    DIRECT_WORKER_CHAT = "direct_worker_chat"
    PARENT_GROUP_CHAT = "parent_group_chat"
    NONE = "none"


@dataclass(frozen=True)
class ChildAgentPermissionBoundary:
    """Requested tool permissions plus the parent/main policy ceilings."""

    requested_tools: tuple[str, ...]
    parent_policy_allowed_tools: tuple[str, ...]
    main_policy_allowed_tools: tuple[str, ...]
    policy_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "requested_tools",
            _string_tuple(self.requested_tools, "requested_tools"),
        )
        object.__setattr__(
            self,
            "parent_policy_allowed_tools",
            _string_tuple(
                self.parent_policy_allowed_tools,
                "parent_policy_allowed_tools",
            ),
        )
        object.__setattr__(
            self,
            "main_policy_allowed_tools",
            _string_tuple(self.main_policy_allowed_tools, "main_policy_allowed_tools"),
        )
        object.__setattr__(
            self,
            "policy_ref",
            _validate_relative_ref(self.policy_ref, "policy_ref"),
        )
        requested = set(self.requested_tools)
        if not requested <= set(self.parent_policy_allowed_tools):
            raise OrganizationEvolutionError(
                "requested_tools must not exceed parent_policy_allowed_tools"
            )
        if not requested <= set(self.main_policy_allowed_tools):
            raise OrganizationEvolutionError(
                "requested_tools must not exceed main_policy_allowed_tools"
            )


@dataclass(frozen=True)
class ChildAgentBudgetPolicy:
    """Explicit finite budget limits for a proposed durable child agent."""

    max_task_tokens: int
    max_turn_tokens: int
    max_task_cost_usd: float | None
    budget_ref: str

    def __post_init__(self) -> None:
        _positive_int(self.max_task_tokens, "max_task_tokens")
        _positive_int(self.max_turn_tokens, "max_turn_tokens")
        if self.max_task_cost_usd is None:
            raise OrganizationEvolutionError("max_task_cost_usd must be explicit")
        _non_negative_number(self.max_task_cost_usd, "max_task_cost_usd")
        object.__setattr__(
            self,
            "budget_ref",
            _validate_relative_ref(self.budget_ref, "budget_ref"),
        )


@dataclass(frozen=True)
class ChildAgentModelPolicy:
    """Explicit model allow-list for a proposed durable child agent."""

    default_model: str
    allowed_models: tuple[str, ...]
    model_policy_ref: str

    def __post_init__(self) -> None:
        _require_string(self.default_model, "default_model")
        object.__setattr__(
            self,
            "allowed_models",
            _string_tuple(self.allowed_models, "allowed_models"),
        )
        if self.default_model not in self.allowed_models:
            raise OrganizationEvolutionError(
                "default_model must be listed in allowed_models"
            )
        object.__setattr__(
            self,
            "model_policy_ref",
            _validate_relative_ref(self.model_policy_ref, "model_policy_ref"),
        )


@dataclass(frozen=True)
class ChildAgentExternalAdapterRequirement:
    """Low-sensitivity external adapter requirements without credentials."""

    adapter_type: str
    health_check_requirement: str
    credential_requirement_summary: str

    def __post_init__(self) -> None:
        _require_string(self.adapter_type, "adapter_type")
        _require_string(
            self.health_check_requirement,
            "health_check_requirement",
        )
        _require_string(
            self.credential_requirement_summary,
            "credential_requirement_summary",
        )


@dataclass(frozen=True)
class ChildAgentCreatePlan:
    """Proposal sub-plan for creating a durable child agent or org node.

    This is a contract only: it records the intended child node, policy ceilings,
    profile references, and chat strategy. It does not create profiles, registry
    records, active organization nodes, or chat bindings.
    """

    plan_id: str
    child_node_id: str
    child_name: str
    node_kind: ChildAgentNodeKind | str
    runtime_kind: ChildAgentRuntimeKind | str
    parent_node_id: str
    responsibility_summary: str
    capability_boundaries: tuple[str, ...]
    permission_boundary: ChildAgentPermissionBoundary
    budget_policy: ChildAgentBudgetPolicy
    model_policy: ChildAgentModelPolicy
    chat_policy: ChildAgentChatPolicy | str
    leader_worker_id: str | None = None
    child_worker_id: str | None = None
    initial_profile_ref: str | None = None
    initial_profile_template_summary: str | None = None
    external_adapter: ChildAgentExternalAdapterRequirement | None = None
    source_refs: tuple[str, ...] = ()
    schema_version: int = CHILD_AGENT_LIFECYCLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_schema_version_value(
            self.schema_version,
            CHILD_AGENT_LIFECYCLE_SCHEMA_VERSION,
            "child agent lifecycle",
        )
        _validate_identifier(self.plan_id, "plan_id")
        _reject_temporary_child_identifier(self.plan_id, "plan_id")
        object.__setattr__(
            self,
            "child_node_id",
            _validate_org_node_reference(self.child_node_id),
        )
        _reject_temporary_child_identifier(self.child_node_id, "child_node_id")
        _require_string(self.child_name, "child_name")
        object.__setattr__(self, "node_kind", _child_node_kind(self.node_kind))
        object.__setattr__(self, "runtime_kind", _child_runtime_kind(self.runtime_kind))
        object.__setattr__(
            self,
            "parent_node_id",
            _validate_org_node_reference(self.parent_node_id),
        )
        _require_string(self.responsibility_summary, "responsibility_summary")
        object.__setattr__(
            self,
            "capability_boundaries",
            _string_tuple(self.capability_boundaries, "capability_boundaries"),
        )
        if not self.capability_boundaries:
            raise OrganizationEvolutionError(
                "capability_boundaries must not be empty"
            )
        if not isinstance(self.permission_boundary, ChildAgentPermissionBoundary):
            raise OrganizationEvolutionError(
                "permission_boundary must be a ChildAgentPermissionBoundary"
            )
        if not isinstance(self.budget_policy, ChildAgentBudgetPolicy):
            raise OrganizationEvolutionError(
                "budget_policy must be a ChildAgentBudgetPolicy"
            )
        if not isinstance(self.model_policy, ChildAgentModelPolicy):
            raise OrganizationEvolutionError(
                "model_policy must be a ChildAgentModelPolicy"
            )
        object.__setattr__(self, "chat_policy", _child_chat_policy(self.chat_policy))
        if self.leader_worker_id is not None:
            object.__setattr__(
                self,
                "leader_worker_id",
                _validate_worker_reference(self.leader_worker_id),
            )
        if self.child_worker_id is not None:
            object.__setattr__(
                self,
                "child_worker_id",
                _validate_worker_reference(self.child_worker_id),
            )
            _reject_temporary_child_identifier(self.child_worker_id, "child_worker_id")
        if self.initial_profile_ref is not None:
            object.__setattr__(
                self,
                "initial_profile_ref",
                _validate_relative_ref(self.initial_profile_ref, "initial_profile_ref"),
            )
            _reject_temporary_child_identifier(
                self.initial_profile_ref,
                "initial_profile_ref",
            )
        if self.initial_profile_template_summary is not None:
            _require_string(
                self.initial_profile_template_summary,
                "initial_profile_template_summary",
            )
        if self.initial_profile_ref is None and self.initial_profile_template_summary is None:
            raise OrganizationEvolutionError(
                "initial_profile_ref or initial_profile_template_summary is required"
            )
        if self.runtime_kind is ChildAgentRuntimeKind.EXTERNAL_AGENT:
            if self.external_adapter is None:
                raise OrganizationEvolutionError(
                    "external_agent create plans require external_adapter"
                )
        elif self.external_adapter is not None:
            raise OrganizationEvolutionError(
                "external_adapter is only valid for external_agent plans"
            )
        if self.node_kind is ChildAgentNodeKind.WORKER and self.child_worker_id is None:
            raise OrganizationEvolutionError("worker create plans require child_worker_id")
        if self.node_kind is not ChildAgentNodeKind.WORKER and self.child_worker_id is not None:
            raise OrganizationEvolutionError(
                "child_worker_id is only valid for worker create plans"
            )
        object.__setattr__(
            self,
            "source_refs",
            _relative_ref_tuple(self.source_refs, "source_refs"),
        )


@dataclass(frozen=True)
class ChildAgentReplacementOwner:
    """Low-sensitivity replacement owner reference for a delete plan."""

    kind: ChildAgentReplacementOwnerKind | str
    org_node_id: str | None = None
    worker_id: str | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _replacement_owner_kind(self.kind))
        if self.kind is ChildAgentReplacementOwnerKind.ORG_NODE:
            if self.org_node_id is None:
                raise OrganizationEvolutionError(
                    "replacement owner org_node_id is required"
                )
            object.__setattr__(
                self,
                "org_node_id",
                _validate_org_node_reference(self.org_node_id),
            )
            if self.worker_id is not None:
                raise OrganizationEvolutionError(
                    "worker_id is only valid for worker replacement owners"
                )
        elif self.kind is ChildAgentReplacementOwnerKind.WORKER:
            if self.worker_id is None:
                raise OrganizationEvolutionError(
                    "replacement owner worker_id is required"
                )
            object.__setattr__(
                self,
                "worker_id",
                _validate_worker_reference(self.worker_id),
            )
            if self.org_node_id is not None:
                raise OrganizationEvolutionError(
                    "org_node_id is only valid for org_node replacement owners"
                )
        else:
            if self.org_node_id is not None or self.worker_id is not None:
                raise OrganizationEvolutionError(
                    "replacement owner id is only valid for org_node or worker"
                )
        if self.kind is ChildAgentReplacementOwnerKind.NO_REPLACEMENT:
            _require_string(self.reason, "replacement owner reason")
        elif not isinstance(self.reason, str):
            raise OrganizationEvolutionError("replacement owner reason must be a string")


@dataclass(frozen=True)
class ChildAgentDeleteCheckSummary:
    """Preflight summary for proposal approval and later executor gates."""

    blocking_checks: tuple[ChildAgentDeleteBlockingCheck, ...]
    can_enter_pending_approval: bool
    can_execute: bool
    summary: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "blocking_checks",
            tuple(_delete_blocking_check(item) for item in self.blocking_checks),
        )
        if not isinstance(self.can_enter_pending_approval, bool):
            raise OrganizationEvolutionError(
                "can_enter_pending_approval must be a boolean"
            )
        if not isinstance(self.can_execute, bool):
            raise OrganizationEvolutionError("can_execute must be a boolean")
        _require_string(self.summary, "summary")


@dataclass(frozen=True)
class ChildAgentDeletePlan:
    """Proposal sub-plan for removing a durable child agent or org node.

    The plan records blockers and disposition references only. It never deletes
    files, mutates registry lifecycle state, closes chats, or migrates assets.
    """

    plan_id: str
    target_node_id: str
    deletion_mode: ChildAgentDeletionMode | str
    reason: str
    replacement_owner: ChildAgentReplacementOwner
    asset_disposition_refs: tuple[str, ...]
    chat_disposition_refs: tuple[str, ...]
    target_worker_id: str | None = None
    private_asset_disposition: ChildAgentPrivateAssetDisposition | str = (
        ChildAgentPrivateAssetDisposition.ARCHIVE
    )
    active_task_refs: tuple[str, ...] = ()
    pending_approval_refs: tuple[str, ...] = ()
    child_node_ids: tuple[str, ...] = ()
    running_session_refs: tuple[str, ...] = ()
    downstream_disposition_refs: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    schema_version: int = CHILD_AGENT_LIFECYCLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_schema_version_value(
            self.schema_version,
            CHILD_AGENT_LIFECYCLE_SCHEMA_VERSION,
            "child agent lifecycle",
        )
        _validate_identifier(self.plan_id, "plan_id")
        object.__setattr__(
            self,
            "target_node_id",
            _validate_org_node_reference(self.target_node_id),
        )
        object.__setattr__(
            self,
            "deletion_mode",
            _child_deletion_mode(self.deletion_mode),
        )
        _require_string(self.reason, "reason")
        if not isinstance(self.replacement_owner, ChildAgentReplacementOwner):
            raise OrganizationEvolutionError(
                "replacement_owner must be a ChildAgentReplacementOwner"
            )
        if self.target_worker_id is not None:
            object.__setattr__(
                self,
                "target_worker_id",
                _validate_worker_reference(self.target_worker_id),
            )
        object.__setattr__(
            self,
            "private_asset_disposition",
            _private_asset_disposition(self.private_asset_disposition),
        )
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
        # Missing disposition refs are preflight blockers, not schema errors.
        # Keeping them representable lets proposal review show the full cleanup gap.
        object.__setattr__(
            self,
            "active_task_refs",
            _relative_ref_tuple(self.active_task_refs, "active_task_refs"),
        )
        object.__setattr__(
            self,
            "pending_approval_refs",
            _relative_ref_tuple(self.pending_approval_refs, "pending_approval_refs"),
        )
        object.__setattr__(
            self,
            "child_node_ids",
            tuple(_validate_org_node_reference(node_id) for node_id in self.child_node_ids),
        )
        object.__setattr__(
            self,
            "running_session_refs",
            _relative_ref_tuple(self.running_session_refs, "running_session_refs"),
        )
        object.__setattr__(
            self,
            "downstream_disposition_refs",
            _relative_ref_tuple(
                self.downstream_disposition_refs,
                "downstream_disposition_refs",
            ),
        )
        if self.child_node_ids and not self.downstream_disposition_refs:
            raise OrganizationEvolutionError(
                "child_node_ids require downstream_disposition_refs"
            )
        object.__setattr__(
            self,
            "source_refs",
            _relative_ref_tuple(self.source_refs, "source_refs"),
        )

    @property
    def check_summary(self) -> ChildAgentDeleteCheckSummary:
        """Return a deterministic summary of current pre-execution blockers."""
        blockers = child_agent_delete_blocking_checks(self)
        if blockers:
            summary = "Deletion is blocked by: " + ", ".join(
                blocker.value for blocker in blockers
            )
        else:
            summary = "Deletion plan has no blocking preflight checks."
        return ChildAgentDeleteCheckSummary(
            blocking_checks=blockers,
            can_enter_pending_approval=not blockers,
            can_execute=not blockers,
            summary=summary,
        )


@dataclass(frozen=True)
class DepartmentMergeDepartmentSummary:
    """Low-sensitivity department summary captured before merge planning."""

    department_id: str
    name: str
    responsibility_summary: str
    leader_worker_id: str | None = None
    member_worker_ids: tuple[str, ...] = ()
    child_node_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "department_id",
            _validate_org_node_reference(self.department_id),
        )
        _require_string(self.name, "name")
        _require_string(self.responsibility_summary, "responsibility_summary")
        if self.leader_worker_id is not None:
            object.__setattr__(
                self,
                "leader_worker_id",
                _validate_worker_reference(self.leader_worker_id),
            )
        object.__setattr__(
            self,
            "member_worker_ids",
            tuple(
                _validate_worker_reference(worker_id)
                for worker_id in self.member_worker_ids
            ),
        )
        object.__setattr__(
            self,
            "child_node_ids",
            tuple(
                _validate_org_node_reference(node_id)
                for node_id in self.child_node_ids
            ),
        )


@dataclass(frozen=True)
class DepartmentMergeRequest:
    """Request contract for merging one or more departments into one target."""

    request_id: str
    initiator: EvolutionProposalInitiator
    source_department_ids: tuple[str, ...]
    target_department_id: str
    reason: str
    source_summaries: tuple[DepartmentMergeDepartmentSummary, ...]
    target_summary: DepartmentMergeDepartmentSummary
    responsibility_change_summary: str
    member_migration_intent: str
    source_refs: tuple[str, ...] = ()
    schema_version: int = CHILD_AGENT_LIFECYCLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_schema_version_value(
            self.schema_version,
            CHILD_AGENT_LIFECYCLE_SCHEMA_VERSION,
            "department merge",
        )
        _validate_identifier(self.request_id, "request_id")
        if not isinstance(self.initiator, EvolutionProposalInitiator):
            raise OrganizationEvolutionError(
                "initiator must be an EvolutionProposalInitiator"
            )
        object.__setattr__(
            self,
            "source_department_ids",
            tuple(
                _validate_org_node_reference(department_id)
                for department_id in self.source_department_ids
            ),
        )
        if not self.source_department_ids:
            raise OrganizationEvolutionError(
                "source_department_ids must not be empty"
            )
        object.__setattr__(
            self,
            "target_department_id",
            _validate_org_node_reference(self.target_department_id),
        )
        if self.target_department_id in self.source_department_ids:
            raise OrganizationEvolutionError(
                "source_department_ids must not include target_department_id"
            )
        _require_string(self.reason, "reason")
        object.__setattr__(
            self,
            "source_summaries",
            _department_summary_tuple(self.source_summaries, "source_summaries"),
        )
        if {summary.department_id for summary in self.source_summaries} != set(
            self.source_department_ids
        ):
            raise OrganizationEvolutionError(
                "source_summaries must match source_department_ids"
            )
        if not isinstance(self.target_summary, DepartmentMergeDepartmentSummary):
            raise OrganizationEvolutionError(
                "target_summary must be a DepartmentMergeDepartmentSummary"
            )
        if self.target_summary.department_id != self.target_department_id:
            raise OrganizationEvolutionError(
                "target_summary must match target_department_id"
            )
        _require_string(
            self.responsibility_change_summary,
            "responsibility_change_summary",
        )
        _require_string(self.member_migration_intent, "member_migration_intent")
        object.__setattr__(
            self,
            "source_refs",
            _relative_ref_tuple(self.source_refs, "source_refs"),
        )


@dataclass(frozen=True)
class DepartmentMergePlan:
    """Reviewable department merge plan with references to sub-plans only."""

    plan_id: str
    request: DepartmentMergeRequest
    status: DepartmentMergePlanStatus | str
    task_transfer_plan_ref: str
    chat_freeze_plan_ref: str
    memory_merge_report_ref: str
    skill_disposition_plan_ref: str
    tool_disposition_plan_ref: str
    rollback_plan_ref: str
    proposal_ref: str | None = None
    source_refs: tuple[str, ...] = ()
    schema_version: int = CHILD_AGENT_LIFECYCLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_schema_version_value(
            self.schema_version,
            CHILD_AGENT_LIFECYCLE_SCHEMA_VERSION,
            "department merge",
        )
        _validate_identifier(self.plan_id, "plan_id")
        if not isinstance(self.request, DepartmentMergeRequest):
            raise OrganizationEvolutionError(
                "request must be a DepartmentMergeRequest"
            )
        object.__setattr__(self, "status", _department_merge_plan_status(self.status))
        for field_name in (
            "task_transfer_plan_ref",
            "chat_freeze_plan_ref",
            "memory_merge_report_ref",
            "skill_disposition_plan_ref",
            "tool_disposition_plan_ref",
            "rollback_plan_ref",
        ):
            object.__setattr__(
                self,
                field_name,
                _validate_relative_ref(getattr(self, field_name), field_name),
            )
        if self.proposal_ref is not None:
            object.__setattr__(
                self,
                "proposal_ref",
                _validate_relative_ref(self.proposal_ref, "proposal_ref"),
            )
        object.__setattr__(
            self,
            "source_refs",
            _relative_ref_tuple(self.source_refs, "source_refs"),
        )


@dataclass(frozen=True)
class DepartmentContractionPlan:
    """Plan for parent/child department shape after deleting a child agent.

    The plan records the desired organization and chat-binding outcome only.
    It does not mutate the active tree, close chats, or archive assets.
    """

    plan_id: str
    department_node_id: str
    parent_node_id: str | None
    remaining_worker_ids: tuple[str, ...]
    remaining_child_node_ids: tuple[str, ...]
    responsibilities_remain: bool
    contraction_mode: DepartmentContractionMode | str
    collaboration_surface: DepartmentCollaborationSurface | str
    reason: str
    chat_disposition_ref: str | None = None
    asset_disposition_ref: str | None = None
    source_refs: tuple[str, ...] = ()
    schema_version: int = CHILD_AGENT_LIFECYCLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_schema_version_value(
            self.schema_version,
            CHILD_AGENT_LIFECYCLE_SCHEMA_VERSION,
            "department contraction",
        )
        _validate_identifier(self.plan_id, "plan_id")
        object.__setattr__(
            self,
            "department_node_id",
            _validate_org_node_reference(self.department_node_id),
        )
        if self.parent_node_id is not None:
            object.__setattr__(
                self,
                "parent_node_id",
                _validate_org_node_reference(self.parent_node_id),
            )
        object.__setattr__(
            self,
            "remaining_worker_ids",
            tuple(
                _validate_worker_reference(worker_id)
                for worker_id in self.remaining_worker_ids
            ),
        )
        object.__setattr__(
            self,
            "remaining_child_node_ids",
            tuple(
                _validate_org_node_reference(node_id)
                for node_id in self.remaining_child_node_ids
            ),
        )
        if not isinstance(self.responsibilities_remain, bool):
            raise OrganizationEvolutionError("responsibilities_remain must be a boolean")
        object.__setattr__(
            self,
            "contraction_mode",
            _department_contraction_mode(self.contraction_mode),
        )
        object.__setattr__(
            self,
            "collaboration_surface",
            _department_collaboration_surface(self.collaboration_surface),
        )
        _require_string(self.reason, "reason")
        if self.chat_disposition_ref is not None:
            object.__setattr__(
                self,
                "chat_disposition_ref",
                _validate_relative_ref(self.chat_disposition_ref, "chat_disposition_ref"),
            )
        if self.asset_disposition_ref is not None:
            object.__setattr__(
                self,
                "asset_disposition_ref",
                _validate_relative_ref(
                    self.asset_disposition_ref,
                    "asset_disposition_ref",
                ),
            )
        if (
            self.collaboration_surface
            is DepartmentCollaborationSurface.DEPARTMENT_GROUP_CHAT
            and len(self.remaining_worker_ids) < 2
        ):
            raise OrganizationEvolutionError(
                "department group chat requires at least two remaining workers"
            )
        if self.contraction_mode is DepartmentContractionMode.ARCHIVE_NODE:
            if self.responsibilities_remain or self.remaining_worker_ids:
                raise OrganizationEvolutionError(
                    "archive_node requires no responsibilities and no remaining workers"
                )
            if self.asset_disposition_ref is None:
                raise OrganizationEvolutionError(
                    "archive_node requires asset_disposition_ref"
                )
        if self.contraction_mode in {
            DepartmentContractionMode.REBIND_CHAT_TO_PARENT,
            DepartmentContractionMode.REMOVE_EMPTY_CHILD_DEPARTMENT,
            DepartmentContractionMode.ARCHIVE_NODE,
        } and self.chat_disposition_ref is None:
            raise OrganizationEvolutionError(
                f"{self.contraction_mode.value} requires chat_disposition_ref"
            )
        object.__setattr__(
            self,
            "source_refs",
            _relative_ref_tuple(self.source_refs, "source_refs"),
        )


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
_CHILD_PERMISSION_BOUNDARY_FIELDS = {
    "requested_tools",
    "parent_policy_allowed_tools",
    "main_policy_allowed_tools",
    "policy_ref",
}
_CHILD_BUDGET_POLICY_FIELDS = {
    "max_task_tokens",
    "max_turn_tokens",
    "max_task_cost_usd",
    "budget_ref",
}
_CHILD_MODEL_POLICY_FIELDS = {
    "default_model",
    "allowed_models",
    "model_policy_ref",
}
_CHILD_EXTERNAL_ADAPTER_FIELDS = {
    "adapter_type",
    "health_check_requirement",
    "credential_requirement_summary",
}
_CHILD_CREATE_PLAN_FIELDS = {
    "plan_id",
    "schema_version",
    "child_node_id",
    "child_name",
    "node_kind",
    "runtime_kind",
    "parent_node_id",
    "responsibility_summary",
    "capability_boundaries",
    "permission_boundary",
    "budget_policy",
    "model_policy",
    "chat_policy",
    "leader_worker_id",
    "child_worker_id",
    "initial_profile_ref",
    "initial_profile_template_summary",
    "external_adapter",
    "source_refs",
}
_REPLACEMENT_OWNER_FIELDS = {"kind", "org_node_id", "worker_id", "reason"}
_DELETE_CHECK_SUMMARY_FIELDS = {
    "blocking_checks",
    "can_enter_pending_approval",
    "can_execute",
    "summary",
}
_CHILD_DELETE_PLAN_FIELDS = {
    "plan_id",
    "schema_version",
    "target_node_id",
    "target_worker_id",
    "deletion_mode",
    "reason",
    "replacement_owner",
    "private_asset_disposition",
    "asset_disposition_refs",
    "chat_disposition_refs",
    "active_task_refs",
    "pending_approval_refs",
    "child_node_ids",
    "running_session_refs",
    "downstream_disposition_refs",
    "source_refs",
}
_DEPARTMENT_MERGE_SUMMARY_FIELDS = {
    "department_id",
    "name",
    "responsibility_summary",
    "leader_worker_id",
    "member_worker_ids",
    "child_node_ids",
}
_DEPARTMENT_MERGE_REQUEST_FIELDS = {
    "request_id",
    "schema_version",
    "initiator",
    "source_department_ids",
    "target_department_id",
    "reason",
    "source_summaries",
    "target_summary",
    "responsibility_change_summary",
    "member_migration_intent",
    "source_refs",
}
_DEPARTMENT_MERGE_PLAN_FIELDS = {
    "plan_id",
    "schema_version",
    "request",
    "status",
    "task_transfer_plan_ref",
    "chat_freeze_plan_ref",
    "memory_merge_report_ref",
    "skill_disposition_plan_ref",
    "tool_disposition_plan_ref",
    "rollback_plan_ref",
    "proposal_ref",
    "source_refs",
}
_DEPARTMENT_CONTRACTION_PLAN_FIELDS = {
    "plan_id",
    "schema_version",
    "department_node_id",
    "parent_node_id",
    "remaining_worker_ids",
    "remaining_child_node_ids",
    "responsibilities_remain",
    "contraction_mode",
    "collaboration_surface",
    "reason",
    "chat_disposition_ref",
    "asset_disposition_ref",
    "source_refs",
}
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


def validate_child_agent_create_plan(
    plan: ChildAgentCreatePlan | Mapping[str, Any],
) -> ChildAgentCreatePlan:
    """Return a validated durable child-agent create plan."""
    if isinstance(plan, ChildAgentCreatePlan):
        data = child_agent_create_plan_to_dict(plan)
    else:
        data = plan
    _reject_sensitive_payload(data, "child_agent_create_plan")
    return child_agent_create_plan_from_dict(data)


def validate_child_agent_delete_plan(
    plan: ChildAgentDeletePlan | Mapping[str, Any],
) -> ChildAgentDeletePlan:
    """Return a validated durable child-agent delete plan."""
    if isinstance(plan, ChildAgentDeletePlan):
        data = child_agent_delete_plan_to_dict(plan)
    else:
        data = plan
    _reject_sensitive_payload(data, "child_agent_delete_plan")
    return child_agent_delete_plan_from_dict(data)


def validate_department_merge_request(
    request: DepartmentMergeRequest | Mapping[str, Any],
) -> DepartmentMergeRequest:
    """Return a validated department merge request."""
    if isinstance(request, DepartmentMergeRequest):
        data = department_merge_request_to_dict(request)
    else:
        data = request
    _reject_sensitive_payload(data, "department_merge_request")
    return department_merge_request_from_dict(data)


def validate_department_merge_plan(
    plan: DepartmentMergePlan | Mapping[str, Any],
) -> DepartmentMergePlan:
    """Return a validated department merge plan."""
    if isinstance(plan, DepartmentMergePlan):
        data = department_merge_plan_to_dict(plan)
    else:
        data = plan
    _reject_sensitive_payload(data, "department_merge_plan")
    return department_merge_plan_from_dict(data)


def validate_department_contraction_plan(
    plan: DepartmentContractionPlan | Mapping[str, Any],
) -> DepartmentContractionPlan:
    """Return a validated department contraction plan."""
    if isinstance(plan, DepartmentContractionPlan):
        data = department_contraction_plan_to_dict(plan)
    else:
        data = plan
    _reject_sensitive_payload(data, "department_contraction_plan")
    return department_contraction_plan_from_dict(data)


def plan_department_contraction(
    *,
    plan_id: str,
    department_node_id: str,
    parent_node_id: str | None,
    remaining_worker_ids: tuple[str, ...],
    remaining_child_node_ids: tuple[str, ...],
    responsibilities_remain: bool,
    chat_disposition_ref: str | None = None,
    asset_disposition_ref: str | None = None,
    source_refs: tuple[str, ...] = (),
) -> DepartmentContractionPlan:
    """Plan organization contraction after child-agent deletion.

    Collaboration participants are durable workers only. User and main-agent
    presence are required for chat execution later, but they do not make a
    one-worker department eligible for its own group chat.
    """
    worker_count = len(tuple(remaining_worker_ids))
    child_count = len(tuple(remaining_child_node_ids))

    if worker_count >= 2:
        mode = DepartmentContractionMode.KEEP_DEPARTMENT
        surface = DepartmentCollaborationSurface.DEPARTMENT_GROUP_CHAT
        reason = "department still has multiple workers"
    elif worker_count == 1 and responsibilities_remain:
        if parent_node_id is not None and chat_disposition_ref is not None:
            mode = DepartmentContractionMode.REBIND_CHAT_TO_PARENT
            surface = DepartmentCollaborationSurface.PARENT_GROUP_CHAT
            reason = "single-worker department uses parent group chat"
        else:
            mode = DepartmentContractionMode.KEEP_SINGLE_WORKER_DEPARTMENT
            surface = DepartmentCollaborationSurface.DIRECT_WORKER_CHAT
            reason = "single-worker department keeps node but not a group chat"
    elif child_count == 0 and not responsibilities_remain and worker_count == 0:
        mode = DepartmentContractionMode.ARCHIVE_NODE
        surface = DepartmentCollaborationSurface.NONE
        reason = "empty department with no responsibilities should archive"
    elif child_count == 0 and worker_count == 0:
        mode = DepartmentContractionMode.REMOVE_EMPTY_CHILD_DEPARTMENT
        surface = DepartmentCollaborationSurface.NONE
        reason = "empty child department should be removed from active tree"
    else:
        mode = DepartmentContractionMode.KEEP_DEPARTMENT
        surface = DepartmentCollaborationSurface.NONE
        reason = "department keeps downstream nodes without a direct group chat"

    return DepartmentContractionPlan(
        plan_id=plan_id,
        department_node_id=department_node_id,
        parent_node_id=parent_node_id,
        remaining_worker_ids=remaining_worker_ids,
        remaining_child_node_ids=remaining_child_node_ids,
        responsibilities_remain=responsibilities_remain,
        contraction_mode=mode,
        collaboration_surface=surface,
        reason=reason,
        chat_disposition_ref=chat_disposition_ref,
        asset_disposition_ref=asset_disposition_ref,
        source_refs=source_refs,
    )


def child_agent_delete_blocking_checks(
    plan: ChildAgentDeletePlan | Mapping[str, Any],
) -> tuple[ChildAgentDeleteBlockingCheck, ...]:
    """Return execution blockers without mutating organization or registry state."""
    validated = (
        plan if isinstance(plan, ChildAgentDeletePlan) else validate_child_agent_delete_plan(plan)
    )
    blockers: list[ChildAgentDeleteBlockingCheck] = []
    if validated.active_task_refs:
        blockers.append(ChildAgentDeleteBlockingCheck.ACTIVE_TASKS)
    if validated.pending_approval_refs:
        blockers.append(ChildAgentDeleteBlockingCheck.PENDING_APPROVALS)
    if validated.child_node_ids:
        blockers.append(ChildAgentDeleteBlockingCheck.CHILD_NODES)
    if validated.running_session_refs:
        blockers.append(ChildAgentDeleteBlockingCheck.RUNNING_SESSIONS)
    if not validated.asset_disposition_refs:
        blockers.append(ChildAgentDeleteBlockingCheck.ASSET_DISPOSITION_MISSING)
    if not validated.chat_disposition_refs:
        blockers.append(ChildAgentDeleteBlockingCheck.CHAT_DISPOSITION_MISSING)
    return tuple(blockers)


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


def child_agent_permission_boundary_to_dict(
    boundary: ChildAgentPermissionBoundary,
) -> dict[str, Any]:
    return {
        "requested_tools": list(boundary.requested_tools),
        "parent_policy_allowed_tools": list(boundary.parent_policy_allowed_tools),
        "main_policy_allowed_tools": list(boundary.main_policy_allowed_tools),
        "policy_ref": boundary.policy_ref,
    }


def child_agent_permission_boundary_from_dict(
    data: Mapping[str, Any],
) -> ChildAgentPermissionBoundary:
    data = _require_mapping(data, "permission_boundary")
    _reject_unknown_fields(
        data,
        _CHILD_PERMISSION_BOUNDARY_FIELDS,
        "permission_boundary",
    )
    return ChildAgentPermissionBoundary(
        requested_tools=_string_tuple(
            data.get("requested_tools"), "requested_tools"
        ),
        parent_policy_allowed_tools=_string_tuple(
            data.get("parent_policy_allowed_tools"),
            "parent_policy_allowed_tools",
        ),
        main_policy_allowed_tools=_string_tuple(
            data.get("main_policy_allowed_tools"),
            "main_policy_allowed_tools",
        ),
        policy_ref=_require_string(data.get("policy_ref"), "policy_ref"),
    )


def child_agent_budget_policy_to_dict(
    policy: ChildAgentBudgetPolicy,
) -> dict[str, Any]:
    return {
        "max_task_tokens": policy.max_task_tokens,
        "max_turn_tokens": policy.max_turn_tokens,
        "max_task_cost_usd": policy.max_task_cost_usd,
        "budget_ref": policy.budget_ref,
    }


def child_agent_budget_policy_from_dict(
    data: Mapping[str, Any],
) -> ChildAgentBudgetPolicy:
    data = _require_mapping(data, "budget_policy")
    _reject_unknown_fields(data, _CHILD_BUDGET_POLICY_FIELDS, "budget_policy")
    return ChildAgentBudgetPolicy(
        max_task_tokens=_positive_int(data.get("max_task_tokens"), "max_task_tokens"),
        max_turn_tokens=_positive_int(data.get("max_turn_tokens"), "max_turn_tokens"),
        max_task_cost_usd=_non_negative_number(
            data.get("max_task_cost_usd"),
            "max_task_cost_usd",
        ),
        budget_ref=_require_string(data.get("budget_ref"), "budget_ref"),
    )


def child_agent_model_policy_to_dict(
    policy: ChildAgentModelPolicy,
) -> dict[str, Any]:
    return {
        "default_model": policy.default_model,
        "allowed_models": list(policy.allowed_models),
        "model_policy_ref": policy.model_policy_ref,
    }


def child_agent_model_policy_from_dict(
    data: Mapping[str, Any],
) -> ChildAgentModelPolicy:
    data = _require_mapping(data, "model_policy")
    _reject_unknown_fields(data, _CHILD_MODEL_POLICY_FIELDS, "model_policy")
    return ChildAgentModelPolicy(
        default_model=_require_string(data.get("default_model"), "default_model"),
        allowed_models=_string_tuple(data.get("allowed_models"), "allowed_models"),
        model_policy_ref=_require_string(
            data.get("model_policy_ref"), "model_policy_ref"
        ),
    )


def child_agent_external_adapter_to_dict(
    requirement: ChildAgentExternalAdapterRequirement,
) -> dict[str, Any]:
    return {
        "adapter_type": requirement.adapter_type,
        "health_check_requirement": requirement.health_check_requirement,
        "credential_requirement_summary": requirement.credential_requirement_summary,
    }


def child_agent_external_adapter_from_dict(
    data: Mapping[str, Any],
) -> ChildAgentExternalAdapterRequirement:
    data = _require_mapping(data, "external_adapter")
    _reject_unknown_fields(
        data,
        _CHILD_EXTERNAL_ADAPTER_FIELDS,
        "external_adapter",
    )
    return ChildAgentExternalAdapterRequirement(
        adapter_type=_require_string(data.get("adapter_type"), "adapter_type"),
        health_check_requirement=_require_string(
            data.get("health_check_requirement"),
            "health_check_requirement",
        ),
        credential_requirement_summary=_require_string(
            data.get("credential_requirement_summary"),
            "credential_requirement_summary",
        ),
    )


def child_agent_create_plan_to_dict(plan: ChildAgentCreatePlan) -> dict[str, Any]:
    return {
        "plan_id": plan.plan_id,
        "schema_version": plan.schema_version,
        "child_node_id": plan.child_node_id,
        "child_name": plan.child_name,
        "node_kind": plan.node_kind.value,
        "runtime_kind": plan.runtime_kind.value,
        "parent_node_id": plan.parent_node_id,
        "responsibility_summary": plan.responsibility_summary,
        "capability_boundaries": list(plan.capability_boundaries),
        "permission_boundary": child_agent_permission_boundary_to_dict(
            plan.permission_boundary
        ),
        "budget_policy": child_agent_budget_policy_to_dict(plan.budget_policy),
        "model_policy": child_agent_model_policy_to_dict(plan.model_policy),
        "chat_policy": plan.chat_policy.value,
        "leader_worker_id": plan.leader_worker_id,
        "child_worker_id": plan.child_worker_id,
        "initial_profile_ref": plan.initial_profile_ref,
        "initial_profile_template_summary": plan.initial_profile_template_summary,
        "external_adapter": (
            child_agent_external_adapter_to_dict(plan.external_adapter)
            if plan.external_adapter is not None
            else None
        ),
        "source_refs": list(plan.source_refs),
    }


def child_agent_create_plan_from_dict(
    data: Mapping[str, Any],
) -> ChildAgentCreatePlan:
    data = _require_mapping(data, "child agent create plan")
    _reject_sensitive_payload(data, "child_agent_create_plan")
    _reject_unknown_fields(
        data,
        _CHILD_CREATE_PLAN_FIELDS,
        "child agent create plan",
    )
    return ChildAgentCreatePlan(
        plan_id=_require_string(data.get("plan_id"), "plan_id"),
        schema_version=data.get(
            "schema_version", CHILD_AGENT_LIFECYCLE_SCHEMA_VERSION
        ),
        child_node_id=_require_string(data.get("child_node_id"), "child_node_id"),
        child_name=_require_string(data.get("child_name"), "child_name"),
        node_kind=_require_string(data.get("node_kind"), "node_kind"),
        runtime_kind=_require_string(data.get("runtime_kind"), "runtime_kind"),
        parent_node_id=_require_string(data.get("parent_node_id"), "parent_node_id"),
        responsibility_summary=_require_string(
            data.get("responsibility_summary"),
            "responsibility_summary",
        ),
        capability_boundaries=_string_tuple(
            data.get("capability_boundaries"), "capability_boundaries"
        ),
        permission_boundary=child_agent_permission_boundary_from_dict(
            _require_mapping(data.get("permission_boundary"), "permission_boundary")
        ),
        budget_policy=child_agent_budget_policy_from_dict(
            _require_mapping(data.get("budget_policy"), "budget_policy")
        ),
        model_policy=child_agent_model_policy_from_dict(
            _require_mapping(data.get("model_policy"), "model_policy")
        ),
        chat_policy=_require_string(data.get("chat_policy"), "chat_policy"),
        leader_worker_id=_optional_string(
            data.get("leader_worker_id"), "leader_worker_id"
        ),
        child_worker_id=_optional_string(
            data.get("child_worker_id"), "child_worker_id"
        ),
        initial_profile_ref=_optional_string(
            data.get("initial_profile_ref"),
            "initial_profile_ref",
        ),
        initial_profile_template_summary=_optional_string(
            data.get("initial_profile_template_summary"),
            "initial_profile_template_summary",
        ),
        external_adapter=(
            child_agent_external_adapter_from_dict(
                _require_mapping(data.get("external_adapter"), "external_adapter")
            )
            if data.get("external_adapter") is not None
            else None
        ),
        source_refs=_string_tuple(data.get("source_refs", ()), "source_refs"),
    )


def child_agent_replacement_owner_to_dict(
    owner: ChildAgentReplacementOwner,
) -> dict[str, Any]:
    return {
        "kind": owner.kind.value,
        "org_node_id": owner.org_node_id,
        "worker_id": owner.worker_id,
        "reason": owner.reason,
    }


def child_agent_replacement_owner_from_dict(
    data: Mapping[str, Any],
) -> ChildAgentReplacementOwner:
    data = _require_mapping(data, "replacement_owner")
    _reject_unknown_fields(data, _REPLACEMENT_OWNER_FIELDS, "replacement_owner")
    return ChildAgentReplacementOwner(
        kind=_require_string(data.get("kind"), "replacement_owner.kind"),
        org_node_id=_optional_string(
            data.get("org_node_id"),
            "replacement_owner.org_node_id",
        ),
        worker_id=_optional_string(
            data.get("worker_id"),
            "replacement_owner.worker_id",
        ),
        reason=_string_value(data.get("reason", ""), "replacement_owner.reason"),
    )


def child_agent_delete_check_summary_to_dict(
    summary: ChildAgentDeleteCheckSummary,
) -> dict[str, Any]:
    return {
        "blocking_checks": [check.value for check in summary.blocking_checks],
        "can_enter_pending_approval": summary.can_enter_pending_approval,
        "can_execute": summary.can_execute,
        "summary": summary.summary,
    }


def child_agent_delete_check_summary_from_dict(
    data: Mapping[str, Any],
) -> ChildAgentDeleteCheckSummary:
    data = _require_mapping(data, "delete check summary")
    _reject_unknown_fields(
        data,
        _DELETE_CHECK_SUMMARY_FIELDS,
        "delete check summary",
    )
    return ChildAgentDeleteCheckSummary(
        blocking_checks=tuple(
            _delete_blocking_check(item)
            for item in _string_tuple(
                data.get("blocking_checks"),
                "blocking_checks",
            )
        ),
        can_enter_pending_approval=_bool_value(
            data.get("can_enter_pending_approval"),
            "can_enter_pending_approval",
        ),
        can_execute=_bool_value(data.get("can_execute"), "can_execute"),
        summary=_require_string(data.get("summary"), "summary"),
    )


def child_agent_delete_plan_to_dict(plan: ChildAgentDeletePlan) -> dict[str, Any]:
    return {
        "plan_id": plan.plan_id,
        "schema_version": plan.schema_version,
        "target_node_id": plan.target_node_id,
        "target_worker_id": plan.target_worker_id,
        "deletion_mode": plan.deletion_mode.value,
        "reason": plan.reason,
        "replacement_owner": child_agent_replacement_owner_to_dict(
            plan.replacement_owner
        ),
        "private_asset_disposition": plan.private_asset_disposition.value,
        "asset_disposition_refs": list(plan.asset_disposition_refs),
        "chat_disposition_refs": list(plan.chat_disposition_refs),
        "active_task_refs": list(plan.active_task_refs),
        "pending_approval_refs": list(plan.pending_approval_refs),
        "child_node_ids": list(plan.child_node_ids),
        "running_session_refs": list(plan.running_session_refs),
        "downstream_disposition_refs": list(plan.downstream_disposition_refs),
        "source_refs": list(plan.source_refs),
    }


def child_agent_delete_plan_from_dict(
    data: Mapping[str, Any],
) -> ChildAgentDeletePlan:
    data = _require_mapping(data, "child agent delete plan")
    _reject_sensitive_payload(data, "child_agent_delete_plan")
    _reject_unknown_fields(
        data,
        _CHILD_DELETE_PLAN_FIELDS,
        "child agent delete plan",
    )
    return ChildAgentDeletePlan(
        plan_id=_require_string(data.get("plan_id"), "plan_id"),
        schema_version=data.get(
            "schema_version", CHILD_AGENT_LIFECYCLE_SCHEMA_VERSION
        ),
        target_node_id=_require_string(data.get("target_node_id"), "target_node_id"),
        target_worker_id=_optional_string(
            data.get("target_worker_id"),
            "target_worker_id",
        ),
        deletion_mode=_require_string(data.get("deletion_mode"), "deletion_mode"),
        reason=_require_string(data.get("reason"), "reason"),
        replacement_owner=child_agent_replacement_owner_from_dict(
            _require_mapping(data.get("replacement_owner"), "replacement_owner")
        ),
        private_asset_disposition=data.get(
            "private_asset_disposition",
            ChildAgentPrivateAssetDisposition.ARCHIVE.value,
        ),
        asset_disposition_refs=_string_tuple(
            data.get("asset_disposition_refs"),
            "asset_disposition_refs",
        ),
        chat_disposition_refs=_string_tuple(
            data.get("chat_disposition_refs"),
            "chat_disposition_refs",
        ),
        active_task_refs=_string_tuple(
            data.get("active_task_refs", ()),
            "active_task_refs",
        ),
        pending_approval_refs=_string_tuple(
            data.get("pending_approval_refs", ()),
            "pending_approval_refs",
        ),
        child_node_ids=_string_tuple(data.get("child_node_ids", ()), "child_node_ids"),
        running_session_refs=_string_tuple(
            data.get("running_session_refs", ()),
            "running_session_refs",
        ),
        downstream_disposition_refs=_string_tuple(
            data.get("downstream_disposition_refs", ()),
            "downstream_disposition_refs",
        ),
        source_refs=_string_tuple(data.get("source_refs", ()), "source_refs"),
    )


def department_merge_department_summary_to_dict(
    summary: DepartmentMergeDepartmentSummary,
) -> dict[str, Any]:
    return {
        "department_id": summary.department_id,
        "name": summary.name,
        "responsibility_summary": summary.responsibility_summary,
        "leader_worker_id": summary.leader_worker_id,
        "member_worker_ids": list(summary.member_worker_ids),
        "child_node_ids": list(summary.child_node_ids),
    }


def department_merge_department_summary_from_dict(
    data: Mapping[str, Any],
) -> DepartmentMergeDepartmentSummary:
    data = _require_mapping(data, "department merge department summary")
    _reject_unknown_fields(
        data,
        _DEPARTMENT_MERGE_SUMMARY_FIELDS,
        "department merge department summary",
    )
    return DepartmentMergeDepartmentSummary(
        department_id=_require_string(data.get("department_id"), "department_id"),
        name=_require_string(data.get("name"), "name"),
        responsibility_summary=_require_string(
            data.get("responsibility_summary"),
            "responsibility_summary",
        ),
        leader_worker_id=_optional_string(
            data.get("leader_worker_id"),
            "leader_worker_id",
        ),
        member_worker_ids=_string_tuple(
            data.get("member_worker_ids", ()),
            "member_worker_ids",
        ),
        child_node_ids=_string_tuple(data.get("child_node_ids", ()), "child_node_ids"),
    )


def department_merge_request_to_dict(
    request: DepartmentMergeRequest,
) -> dict[str, Any]:
    return {
        "request_id": request.request_id,
        "schema_version": request.schema_version,
        "initiator": evolution_proposal_initiator_to_dict(request.initiator),
        "source_department_ids": list(request.source_department_ids),
        "target_department_id": request.target_department_id,
        "reason": request.reason,
        "source_summaries": [
            department_merge_department_summary_to_dict(summary)
            for summary in request.source_summaries
        ],
        "target_summary": department_merge_department_summary_to_dict(
            request.target_summary
        ),
        "responsibility_change_summary": request.responsibility_change_summary,
        "member_migration_intent": request.member_migration_intent,
        "source_refs": list(request.source_refs),
    }


def department_merge_request_from_dict(
    data: Mapping[str, Any],
) -> DepartmentMergeRequest:
    data = _require_mapping(data, "department merge request")
    _reject_sensitive_payload(data, "department_merge_request")
    _reject_unknown_fields(
        data,
        _DEPARTMENT_MERGE_REQUEST_FIELDS,
        "department merge request",
    )
    return DepartmentMergeRequest(
        request_id=_require_string(data.get("request_id"), "request_id"),
        schema_version=data.get(
            "schema_version", CHILD_AGENT_LIFECYCLE_SCHEMA_VERSION
        ),
        initiator=evolution_proposal_initiator_from_dict(
            _require_mapping(data.get("initiator"), "initiator")
        ),
        source_department_ids=_string_tuple(
            data.get("source_department_ids"),
            "source_department_ids",
        ),
        target_department_id=_require_string(
            data.get("target_department_id"),
            "target_department_id",
        ),
        reason=_require_string(data.get("reason"), "reason"),
        source_summaries=tuple(
            department_merge_department_summary_from_dict(
                _require_mapping(item, "source_summaries item")
            )
            for item in data.get("source_summaries", ())
        ),
        target_summary=department_merge_department_summary_from_dict(
            _require_mapping(data.get("target_summary"), "target_summary")
        ),
        responsibility_change_summary=_require_string(
            data.get("responsibility_change_summary"),
            "responsibility_change_summary",
        ),
        member_migration_intent=_require_string(
            data.get("member_migration_intent"),
            "member_migration_intent",
        ),
        source_refs=_string_tuple(data.get("source_refs", ()), "source_refs"),
    )


def department_merge_plan_to_dict(plan: DepartmentMergePlan) -> dict[str, Any]:
    return {
        "plan_id": plan.plan_id,
        "schema_version": plan.schema_version,
        "request": department_merge_request_to_dict(plan.request),
        "status": plan.status.value,
        "task_transfer_plan_ref": plan.task_transfer_plan_ref,
        "chat_freeze_plan_ref": plan.chat_freeze_plan_ref,
        "memory_merge_report_ref": plan.memory_merge_report_ref,
        "skill_disposition_plan_ref": plan.skill_disposition_plan_ref,
        "tool_disposition_plan_ref": plan.tool_disposition_plan_ref,
        "rollback_plan_ref": plan.rollback_plan_ref,
        "proposal_ref": plan.proposal_ref,
        "source_refs": list(plan.source_refs),
    }


def department_merge_plan_from_dict(data: Mapping[str, Any]) -> DepartmentMergePlan:
    data = _require_mapping(data, "department merge plan")
    _reject_sensitive_payload(data, "department_merge_plan")
    _reject_unknown_fields(
        data,
        _DEPARTMENT_MERGE_PLAN_FIELDS,
        "department merge plan",
    )
    return DepartmentMergePlan(
        plan_id=_require_string(data.get("plan_id"), "plan_id"),
        schema_version=data.get(
            "schema_version", CHILD_AGENT_LIFECYCLE_SCHEMA_VERSION
        ),
        request=department_merge_request_from_dict(
            _require_mapping(data.get("request"), "request")
        ),
        status=_require_string(data.get("status"), "status"),
        task_transfer_plan_ref=_require_string(
            data.get("task_transfer_plan_ref"),
            "task_transfer_plan_ref",
        ),
        chat_freeze_plan_ref=_require_string(
            data.get("chat_freeze_plan_ref"),
            "chat_freeze_plan_ref",
        ),
        memory_merge_report_ref=_require_string(
            data.get("memory_merge_report_ref"),
            "memory_merge_report_ref",
        ),
        skill_disposition_plan_ref=_require_string(
            data.get("skill_disposition_plan_ref"),
            "skill_disposition_plan_ref",
        ),
        tool_disposition_plan_ref=_require_string(
            data.get("tool_disposition_plan_ref"),
            "tool_disposition_plan_ref",
        ),
        rollback_plan_ref=_require_string(
            data.get("rollback_plan_ref"),
            "rollback_plan_ref",
        ),
        proposal_ref=_optional_string(data.get("proposal_ref"), "proposal_ref"),
        source_refs=_string_tuple(data.get("source_refs", ()), "source_refs"),
    )


def department_contraction_plan_to_dict(
    plan: DepartmentContractionPlan,
) -> dict[str, Any]:
    return {
        "plan_id": plan.plan_id,
        "schema_version": plan.schema_version,
        "department_node_id": plan.department_node_id,
        "parent_node_id": plan.parent_node_id,
        "remaining_worker_ids": list(plan.remaining_worker_ids),
        "remaining_child_node_ids": list(plan.remaining_child_node_ids),
        "responsibilities_remain": plan.responsibilities_remain,
        "contraction_mode": plan.contraction_mode.value,
        "collaboration_surface": plan.collaboration_surface.value,
        "reason": plan.reason,
        "chat_disposition_ref": plan.chat_disposition_ref,
        "asset_disposition_ref": plan.asset_disposition_ref,
        "source_refs": list(plan.source_refs),
    }


def department_contraction_plan_from_dict(
    data: Mapping[str, Any],
) -> DepartmentContractionPlan:
    data = _require_mapping(data, "department contraction plan")
    _reject_sensitive_payload(data, "department_contraction_plan")
    _reject_unknown_fields(
        data,
        _DEPARTMENT_CONTRACTION_PLAN_FIELDS,
        "department contraction plan",
    )
    return DepartmentContractionPlan(
        plan_id=_require_string(data.get("plan_id"), "plan_id"),
        schema_version=data.get(
            "schema_version", CHILD_AGENT_LIFECYCLE_SCHEMA_VERSION
        ),
        department_node_id=_require_string(
            data.get("department_node_id"),
            "department_node_id",
        ),
        parent_node_id=_optional_string(data.get("parent_node_id"), "parent_node_id"),
        remaining_worker_ids=_string_tuple(
            data.get("remaining_worker_ids", ()),
            "remaining_worker_ids",
        ),
        remaining_child_node_ids=_string_tuple(
            data.get("remaining_child_node_ids", ()),
            "remaining_child_node_ids",
        ),
        responsibilities_remain=_bool_value(
            data.get("responsibilities_remain"),
            "responsibilities_remain",
        ),
        contraction_mode=_require_string(
            data.get("contraction_mode"),
            "contraction_mode",
        ),
        collaboration_surface=_require_string(
            data.get("collaboration_surface"),
            "collaboration_surface",
        ),
        reason=_require_string(data.get("reason"), "reason"),
        chat_disposition_ref=_optional_string(
            data.get("chat_disposition_ref"),
            "chat_disposition_ref",
        ),
        asset_disposition_ref=_optional_string(
            data.get("asset_disposition_ref"),
            "asset_disposition_ref",
        ),
        source_refs=_string_tuple(data.get("source_refs", ()), "source_refs"),
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


def _child_node_kind(value: ChildAgentNodeKind | str) -> ChildAgentNodeKind:
    try:
        return (
            value
            if isinstance(value, ChildAgentNodeKind)
            else ChildAgentNodeKind(value)
        )
    except ValueError as exc:
        raise OrganizationEvolutionError(
            f"Unknown child agent node kind: {value!r}"
        ) from exc


def _child_runtime_kind(
    value: ChildAgentRuntimeKind | str,
) -> ChildAgentRuntimeKind:
    try:
        return (
            value
            if isinstance(value, ChildAgentRuntimeKind)
            else ChildAgentRuntimeKind(value)
        )
    except ValueError as exc:
        raise OrganizationEvolutionError(
            f"Unknown child agent runtime kind: {value!r}"
        ) from exc


def _child_chat_policy(value: ChildAgentChatPolicy | str) -> ChildAgentChatPolicy:
    try:
        return (
            value
            if isinstance(value, ChildAgentChatPolicy)
            else ChildAgentChatPolicy(value)
        )
    except ValueError as exc:
        raise OrganizationEvolutionError(
            f"Unknown child agent chat policy: {value!r}"
        ) from exc


def _child_deletion_mode(
    value: ChildAgentDeletionMode | str,
) -> ChildAgentDeletionMode:
    try:
        return (
            value
            if isinstance(value, ChildAgentDeletionMode)
            else ChildAgentDeletionMode(value)
        )
    except ValueError as exc:
        raise OrganizationEvolutionError(
            f"Unknown child agent deletion mode: {value!r}"
        ) from exc


def _delete_blocking_check(
    value: ChildAgentDeleteBlockingCheck | str,
) -> ChildAgentDeleteBlockingCheck:
    try:
        return (
            value
            if isinstance(value, ChildAgentDeleteBlockingCheck)
            else ChildAgentDeleteBlockingCheck(value)
        )
    except ValueError as exc:
        raise OrganizationEvolutionError(
            f"Unknown child agent delete blocking check: {value!r}"
        ) from exc


def _private_asset_disposition(
    value: ChildAgentPrivateAssetDisposition | str,
) -> ChildAgentPrivateAssetDisposition:
    try:
        return (
            value
            if isinstance(value, ChildAgentPrivateAssetDisposition)
            else ChildAgentPrivateAssetDisposition(value)
        )
    except ValueError as exc:
        raise OrganizationEvolutionError(
            f"Unknown private asset disposition: {value!r}"
        ) from exc


def _replacement_owner_kind(
    value: ChildAgentReplacementOwnerKind | str,
) -> ChildAgentReplacementOwnerKind:
    try:
        return (
            value
            if isinstance(value, ChildAgentReplacementOwnerKind)
            else ChildAgentReplacementOwnerKind(value)
        )
    except ValueError as exc:
        raise OrganizationEvolutionError(
            f"Unknown replacement owner kind: {value!r}"
        ) from exc


def _department_merge_plan_status(
    value: DepartmentMergePlanStatus | str,
) -> DepartmentMergePlanStatus:
    try:
        return (
            value
            if isinstance(value, DepartmentMergePlanStatus)
            else DepartmentMergePlanStatus(value)
        )
    except ValueError as exc:
        raise OrganizationEvolutionError(
            f"Unknown department merge plan status: {value!r}"
        ) from exc


def _department_contraction_mode(
    value: DepartmentContractionMode | str,
) -> DepartmentContractionMode:
    try:
        return (
            value
            if isinstance(value, DepartmentContractionMode)
            else DepartmentContractionMode(value)
        )
    except ValueError as exc:
        raise OrganizationEvolutionError(
            f"Unknown department contraction mode: {value!r}"
        ) from exc


def _department_collaboration_surface(
    value: DepartmentCollaborationSurface | str,
) -> DepartmentCollaborationSurface:
    try:
        return (
            value
            if isinstance(value, DepartmentCollaborationSurface)
            else DepartmentCollaborationSurface(value)
        )
    except ValueError as exc:
        raise OrganizationEvolutionError(
            f"Unknown department collaboration surface: {value!r}"
        ) from exc


def _validate_schema_version(value: int) -> None:
    _validate_schema_version_value(
        value,
        EVOLUTION_PROPOSAL_SCHEMA_VERSION,
        "evolution proposal",
    )


def _validate_schema_version_value(
    value: int,
    expected: int,
    contract_name: str,
) -> None:
    if value != expected:
        raise OrganizationEvolutionError(
            f"Unsupported {contract_name} schema_version: {value!r}"
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


def _bool_value(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise OrganizationEvolutionError(f"{field_name} must be a boolean")
    return value


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise OrganizationEvolutionError(f"{field_name} must be a positive integer")
    return value


def _non_negative_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise OrganizationEvolutionError(f"{field_name} must be a non-negative number")
    return float(value)


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise OrganizationEvolutionError(f"{field_name} must be a list of strings")
    result = tuple(value)
    if any(not isinstance(item, str) or not item for item in result):
        raise OrganizationEvolutionError(
            f"{field_name} must be a list of non-empty strings"
        )
    return result


def _department_summary_tuple(
    value: Any,
    field_name: str,
) -> tuple[DepartmentMergeDepartmentSummary, ...]:
    if not isinstance(value, (list, tuple)):
        raise OrganizationEvolutionError(
            f"{field_name} must be a list of department summaries"
        )
    result = tuple(value)
    if any(not isinstance(item, DepartmentMergeDepartmentSummary) for item in result):
        raise OrganizationEvolutionError(
            f"{field_name} must contain DepartmentMergeDepartmentSummary values"
        )
    if not result:
        raise OrganizationEvolutionError(f"{field_name} must not be empty")
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


def _reject_temporary_child_identifier(value: str, field_name: str) -> None:
    lowered = value.lower()
    if (
        lowered.startswith(("temporary-", "temp-", "delegation-"))
        or "temporary-subagents" in lowered
        or "temporary_subagent" in lowered
        or lowered.startswith("temporary_")
    ):
        raise OrganizationEvolutionError(
            f"{field_name} must not reference a temporary subagent delegation"
        )


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

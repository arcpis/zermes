"""Department skill binding contracts and policy-ready helpers."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
from enum import StrEnum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping

from .organization import validate_org_node_id
from .private_skill_experience import SkillExperienceProposalInput
from .storage import get_worker_agents_home
from utils import atomic_json_write


DEPARTMENT_SKILL_SCHEMA_VERSION = 1

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
        "private_experience_text",
        "raw_skill_instruction",
        "raw_output",
        "raw_stderr",
        "raw_stdout",
        "raw_transcript",
        "refresh_token",
        "secret",
        "skill_source_code",
        "stderr",
        "stdout",
        "token",
    }
)


class DepartmentSkillError(ValueError):
    """Raised when a department skill binding crosses a safe asset boundary."""


class DepartmentSkillBindingState(StrEnum):
    """Reviewable state of a department's relationship to one skill."""

    RECOMMENDED = "recommended"
    DEFAULT = "default"
    RESTRICTED = "restricted"
    DEPRECATED = "deprecated"
    DISABLED = "disabled"


class DepartmentSkillBindingVisibility(StrEnum):
    """How far low-sensitivity binding guidance may be reused."""

    PRIVATE_TO_DEPARTMENT = "private_to_department"
    INHERITABLE_GUIDANCE = "inheritable_guidance"
    ORGANIZATION_GUIDANCE = "organization_guidance"


class DepartmentSkillBindingSensitivity(StrEnum):
    """Sensitivity labels for department skill guidance."""

    LOW = "low"
    INTERNAL = "internal"
    RESTRICTED = "restricted"
    USER_CONFIRMATION_REQUIRED = "user_confirmation_required"


class DepartmentSkillProposalState(StrEnum):
    """Review lifecycle for department skill binding proposals."""

    PENDING = "pending"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


class DepartmentSkillProposalAction(StrEnum):
    """Requested action carried by a department skill proposal."""

    ADD_BINDING = "add_binding"
    UPDATE_GUIDANCE = "update_guidance"
    RESTRICT_BINDING = "restrict_binding"
    DEPRECATE_BINDING = "deprecate_binding"
    DISABLE_BINDING = "disable_binding"


class DepartmentSkillProposalCreateStatus(StrEnum):
    """Whether proposal creation wrote a new record or found a duplicate."""

    CREATED = "created"
    EXISTING = "existing"


class DepartmentSkillReviewerRole(StrEnum):
    """Roles allowed to review department skill proposals."""

    DEPARTMENT_LEAD = "department_lead"
    MAIN_AGENT = "main_agent"
    USER = "user"
    GOVERNANCE_SERVICE = "governance_service"


class DepartmentSkillReviewDecision(StrEnum):
    """Supported review decisions for a department skill proposal."""

    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_CHANGES = "request_changes"
    EXPIRE = "expire"


class DepartmentSkillApplicabilityDecision(StrEnum):
    """Whether a binding may be presented for one task context."""

    ALLOWED = "allowed"
    CANDIDATE_ONLY = "candidate_only"
    NEEDS_REVIEW = "needs_review"
    BLOCKED = "blocked"


class DepartmentSkillGuardrailDecision(StrEnum):
    """Final guardrail outcome before context injection considers a skill."""

    ALLOWED_CANDIDATE = "allowed_candidate"
    BLOCKED = "blocked"
    NEEDS_USER_CONFIRMATION = "needs_user_confirmation"
    NEEDS_OWNER_REVIEW = "needs_owner_review"
    WARNING_ONLY = "warning_only"


class DepartmentSkillGuardrailReason(StrEnum):
    """Stable reason codes shared by context policy, audit, and UI callers."""

    DEPRECATED_BINDING = "deprecated_binding"
    DISABLED_BINDING = "disabled_binding"
    EXTERNAL_RUNTIME_SUMMARY_ONLY = "external_runtime_summary_only"
    MISSING_PERMISSION = "missing_permission"
    OWNER_REVIEW_REQUIRED = "owner_review_required"
    PROFILE_DISALLOWS_SKILL = "profile_disallows_skill"
    RESTRICTED_BINDING = "restricted_binding"
    SENSITIVE_TASK_BLOCKED = "sensitive_task_blocked"
    UNSUPPORTED_TASK_TYPE = "unsupported_task_type"
    USER_CONFIRMATION_REQUIRED = "user_confirmation_required"
    WRONG_DEPARTMENT = "wrong_department"
    WRONG_WORKER_ROLE = "wrong_worker_role"


_STATE_RANK = {
    DepartmentSkillBindingState.RECOMMENDED: 10,
    DepartmentSkillBindingState.DEFAULT: 20,
    DepartmentSkillBindingState.RESTRICTED: 30,
    DepartmentSkillBindingState.DEPRECATED: 40,
    DepartmentSkillBindingState.DISABLED: 50,
}

_SENSITIVITY_RANK = {
    DepartmentSkillBindingSensitivity.LOW: 0,
    DepartmentSkillBindingSensitivity.INTERNAL: 1,
    DepartmentSkillBindingSensitivity.RESTRICTED: 2,
    DepartmentSkillBindingSensitivity.USER_CONFIRMATION_REQUIRED: 3,
}

_BLOCKING_APPLICABILITY_REASONS = frozenset(
    {
        "deprecated_binding",
        "disabled_binding",
        "missing_permission",
        "profile_disallows_skill",
        "sensitive_task_blocked",
        "unsupported_task_type",
        "wrong_department",
        "wrong_worker_role",
    }
)

_USER_CONFIRMATION_REASONS = frozenset(
    {DepartmentSkillGuardrailReason.USER_CONFIRMATION_REQUIRED.value}
)

_OWNER_REVIEW_REASONS = frozenset(
    {DepartmentSkillGuardrailReason.RESTRICTED_BINDING.value}
)


@dataclass(frozen=True)
class DepartmentSkillBindingRecord:
    """Approved department skill guidance; pending proposals use another record."""

    department_id: str
    binding_id: str
    skill_id: str
    skill_source: str
    usage_guidance: str
    state: DepartmentSkillBindingState | str = DepartmentSkillBindingState.RECOMMENDED
    visibility: DepartmentSkillBindingVisibility | str = (
        DepartmentSkillBindingVisibility.PRIVATE_TO_DEPARTMENT
    )
    sensitivity: DepartmentSkillBindingSensitivity | str = (
        DepartmentSkillBindingSensitivity.LOW
    )
    version_constraint: str = ""
    applicability: tuple[str, ...] = ()
    disabled_conditions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    risk_notes: tuple[str, ...] = ()
    tool_assumptions: tuple[str, ...] = ()
    owner: str = ""
    source_refs: tuple[str, ...] = ()
    revision: int = 1
    active: bool = True
    accepted_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    audit_summary: str = ""
    replacement_skill_id: str | None = None
    schema_version: int = DEPARTMENT_SKILL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        validate_org_node_id(self.department_id)
        _validate_identifier(self.binding_id, "binding_id")
        _validate_identifier(self.skill_id, "skill_id")
        _require_string(self.skill_source, "skill_source")
        _require_string(self.usage_guidance, "usage_guidance")
        object.__setattr__(self, "state", _binding_state(self.state))
        object.__setattr__(self, "visibility", _binding_visibility(self.visibility))
        object.__setattr__(self, "sensitivity", _binding_sensitivity(self.sensitivity))
        _require_positive_int(self.revision, "revision")
        if not isinstance(self.active, bool):
            raise DepartmentSkillError("active must be a boolean")
        if self.replacement_skill_id is not None:
            _validate_identifier(self.replacement_skill_id, "replacement_skill_id")
        for value, field_name in (
            (self.version_constraint, "version_constraint"),
            (self.owner, "owner"),
            (self.audit_summary, "audit_summary"),
        ):
            if not isinstance(value, str):
                raise DepartmentSkillError(f"{field_name} must be a string")
        for value, field_name in (
            (self.accepted_at, "accepted_at"),
            (self.created_at, "created_at"),
            (self.updated_at, "updated_at"),
        ):
            if value is not None:
                _require_string(value, field_name)
        _coerce_string_tuple(self, "applicability")
        _coerce_string_tuple(self, "disabled_conditions")
        _coerce_string_tuple(self, "limitations")
        _coerce_string_tuple(self, "risk_notes")
        _coerce_string_tuple(self, "tool_assumptions")
        object.__setattr__(
            self,
            "source_refs",
            tuple(_validate_relative_ref(ref, "source_refs") for ref in self.source_refs),
        )


@dataclass(frozen=True)
class DepartmentSkillBindingProposal:
    """Reviewable candidate for a department skill binding change."""

    proposal_id: str
    department_id: str
    proposed_action: DepartmentSkillProposalAction | str
    skill_id: str
    candidate_guidance: str
    source_actor: str
    source_refs: tuple[str, ...] = ()
    rationale: str = ""
    source_hash: str | None = None
    skill_source: str = "profile_skill_registry"
    version_constraint: str = ""
    candidate_state: DepartmentSkillBindingState | str = (
        DepartmentSkillBindingState.RECOMMENDED
    )
    visibility: DepartmentSkillBindingVisibility | str = (
        DepartmentSkillBindingVisibility.PRIVATE_TO_DEPARTMENT
    )
    sensitivity: DepartmentSkillBindingSensitivity | str = (
        DepartmentSkillBindingSensitivity.INTERNAL
    )
    applicability: tuple[str, ...] = ()
    disabled_conditions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    risk_notes: tuple[str, ...] = ()
    tool_assumptions: tuple[str, ...] = ()
    owner: str = ""
    review_requirement: str = "department_skill_review"
    state: DepartmentSkillProposalState | str = DepartmentSkillProposalState.PENDING
    created_at: str | None = None
    updated_at: str | None = None
    audit_summary: str = ""
    replacement_skill_id: str | None = None
    schema_version: int = DEPARTMENT_SKILL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        _validate_identifier(self.proposal_id, "proposal_id")
        validate_org_node_id(self.department_id)
        object.__setattr__(
            self, "proposed_action", _proposal_action(self.proposed_action)
        )
        _validate_identifier(self.skill_id, "skill_id")
        _require_string(self.candidate_guidance, "candidate_guidance")
        _require_string(self.source_actor, "source_actor")
        _require_string(self.skill_source, "skill_source")
        object.__setattr__(self, "candidate_state", _binding_state(self.candidate_state))
        object.__setattr__(self, "visibility", _binding_visibility(self.visibility))
        object.__setattr__(self, "sensitivity", _binding_sensitivity(self.sensitivity))
        object.__setattr__(self, "state", _proposal_state(self.state))
        if self.replacement_skill_id is not None:
            _validate_identifier(self.replacement_skill_id, "replacement_skill_id")
        for value, field_name in (
            (self.rationale, "rationale"),
            (self.version_constraint, "version_constraint"),
            (self.owner, "owner"),
            (self.audit_summary, "audit_summary"),
        ):
            if not isinstance(value, str):
                raise DepartmentSkillError(f"{field_name} must be a string")
        for value, field_name in (
            (self.source_hash, "source_hash"),
            (self.created_at, "created_at"),
            (self.updated_at, "updated_at"),
        ):
            if value is not None:
                _require_string(value, field_name)
        _require_string(self.review_requirement, "review_requirement")
        _coerce_string_tuple(self, "applicability")
        _coerce_string_tuple(self, "disabled_conditions")
        _coerce_string_tuple(self, "limitations")
        _coerce_string_tuple(self, "risk_notes")
        _coerce_string_tuple(self, "tool_assumptions")
        object.__setattr__(
            self,
            "source_refs",
            tuple(_validate_relative_ref(ref, "source_refs") for ref in self.source_refs),
        )


@dataclass(frozen=True)
class DepartmentSkillProposalCreateResult:
    """Result of creating a department skill proposal."""

    proposal: DepartmentSkillBindingProposal
    status: DepartmentSkillProposalCreateStatus = (
        DepartmentSkillProposalCreateStatus.CREATED
    )

    def __post_init__(self) -> None:
        if not isinstance(self.proposal, DepartmentSkillBindingProposal):
            raise DepartmentSkillError("proposal must be a DepartmentSkillBindingProposal")
        object.__setattr__(self, "status", _proposal_create_status(self.status))


@dataclass(frozen=True)
class DepartmentSkillReviewAction:
    """One explicit review decision made by an authorized actor."""

    proposal_id: str
    decision: DepartmentSkillReviewDecision | str
    actor_id: str
    actor_role: DepartmentSkillReviewerRole | str
    reason: str
    reviewed_at: str
    user_confirmation_ref: str | None = None
    supersede_binding_id: str | None = None
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
        if self.supersede_binding_id is not None:
            _validate_identifier(self.supersede_binding_id, "supersede_binding_id")
        object.__setattr__(
            self,
            "audit_refs",
            tuple(_validate_relative_ref(ref, "audit_refs") for ref in self.audit_refs),
        )


@dataclass(frozen=True)
class DepartmentSkillResolvedBinding:
    """Resolved binding after department inheritance and conservative conflicts."""

    binding: DepartmentSkillBindingRecord
    inherited: bool = False
    source_department_id: str | None = None
    audit_summary: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.binding, DepartmentSkillBindingRecord):
            raise DepartmentSkillError("binding must be a DepartmentSkillBindingRecord")
        if not isinstance(self.inherited, bool):
            raise DepartmentSkillError("inherited must be a boolean")
        if self.source_department_id is not None:
            validate_org_node_id(self.source_department_id)
        if not isinstance(self.audit_summary, str):
            raise DepartmentSkillError("audit_summary must be a string")


@dataclass(frozen=True)
class DepartmentSkillApplicabilityRequest:
    """Task and worker context used to filter department skill guidance."""

    task_type: str
    worker_id: str
    worker_role: str
    department_id: str
    runtime_type: str
    allowed_skill_ids: tuple[str, ...] = ()
    permission_names: tuple[str, ...] = ()
    sensitivity: DepartmentSkillBindingSensitivity | str = (
        DepartmentSkillBindingSensitivity.INTERNAL
    )
    context_purpose: str = "runtime_context"
    confirmation_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_string(self.task_type, "task_type")
        _validate_identifier(self.worker_id, "worker_id")
        _require_string(self.worker_role, "worker_role")
        validate_org_node_id(self.department_id)
        _require_string(self.runtime_type, "runtime_type")
        object.__setattr__(
            self,
            "allowed_skill_ids",
            tuple(
                _validate_identifier(value, "allowed_skill_ids")
                for value in self.allowed_skill_ids
            ),
        )
        object.__setattr__(
            self,
            "permission_names",
            tuple(
                _require_string(value, "permission_names")
                for value in self.permission_names
            ),
        )
        object.__setattr__(self, "sensitivity", _binding_sensitivity(self.sensitivity))
        _require_string(self.context_purpose, "context_purpose")
        object.__setattr__(
            self,
            "confirmation_refs",
            tuple(
                _validate_relative_ref(ref, "confirmation_refs")
                for ref in self.confirmation_refs
            ),
        )


@dataclass(frozen=True)
class DepartmentSkillApplicabilityResult:
    """Applicability decision with stable reasons for audit and guardrails."""

    skill_id: str
    binding_id: str
    decision: DepartmentSkillApplicabilityDecision | str
    reasons: tuple[str, ...] = ()
    safe_guidance_summary: str = ""
    required_review_refs: tuple[str, ...] = ()
    audit_summary: str = ""

    def __post_init__(self) -> None:
        _validate_identifier(self.skill_id, "skill_id")
        _validate_identifier(self.binding_id, "binding_id")
        object.__setattr__(
            self, "decision", _applicability_decision(self.decision)
        )
        object.__setattr__(
            self,
            "reasons",
            tuple(_require_string(value, "reasons") for value in self.reasons),
        )
        if not isinstance(self.safe_guidance_summary, str):
            raise DepartmentSkillError("safe_guidance_summary must be a string")
        object.__setattr__(
            self,
            "required_review_refs",
            tuple(
                _validate_relative_ref(ref, "required_review_refs")
                for ref in self.required_review_refs
            ),
        )
        if not isinstance(self.audit_summary, str):
            raise DepartmentSkillError("audit_summary must be a string")


@dataclass(frozen=True)
class DepartmentSkillSafeCandidate:
    """Minimal skill guidance that may be consumed by context policy."""

    skill_id: str
    binding_id: str
    title: str
    guidance_summary: str
    constraints: tuple[str, ...] = ()
    audit_refs: tuple[str, ...] = ()
    replacement_skill_id: str | None = None

    def __post_init__(self) -> None:
        _validate_identifier(self.skill_id, "skill_id")
        _validate_identifier(self.binding_id, "binding_id")
        _require_string(self.title, "title")
        _require_string(self.guidance_summary, "guidance_summary")
        object.__setattr__(
            self,
            "constraints",
            tuple(_require_string(value, "constraints") for value in self.constraints),
        )
        object.__setattr__(
            self,
            "audit_refs",
            tuple(_validate_relative_ref(ref, "audit_refs") for ref in self.audit_refs),
        )
        if self.replacement_skill_id is not None:
            _validate_identifier(self.replacement_skill_id, "replacement_skill_id")


@dataclass(frozen=True)
class DepartmentSkillGuardrailResult:
    """Guardrail result consumed before any skill guidance reaches context."""

    skill_id: str
    binding_id: str
    decision: DepartmentSkillGuardrailDecision | str
    reasons: tuple[str, ...] = ()
    safe_candidate: DepartmentSkillSafeCandidate | None = None
    review_requirement: str = ""
    audit_summary: str = ""

    def __post_init__(self) -> None:
        _validate_identifier(self.skill_id, "skill_id")
        _validate_identifier(self.binding_id, "binding_id")
        object.__setattr__(self, "decision", _guardrail_decision(self.decision))
        object.__setattr__(
            self,
            "reasons",
            tuple(_require_string(value, "reasons") for value in self.reasons),
        )
        if self.safe_candidate is not None and not isinstance(
            self.safe_candidate, DepartmentSkillSafeCandidate
        ):
            raise DepartmentSkillError(
                "safe_candidate must be a DepartmentSkillSafeCandidate"
            )
        if not isinstance(self.review_requirement, str):
            raise DepartmentSkillError("review_requirement must be a string")
        if not isinstance(self.audit_summary, str):
            raise DepartmentSkillError("audit_summary must be a string")


@dataclass
class DepartmentSkillBindingStore:
    """Profile-home store for department skill proposals and active bindings."""

    root: Path = field(default_factory=get_worker_agents_home)

    def department_skill_root(self, department_id: str) -> Path:
        return department_skill_dir(self.root, department_id)

    def proposals_dir(self, department_id: str) -> Path:
        return self.department_skill_root(department_id) / "proposals"

    def active_dir(self, department_id: str) -> Path:
        return self.department_skill_root(department_id) / "active"

    def history_dir(self, department_id: str, binding_id: str) -> Path:
        _validate_identifier(binding_id, "binding_id")
        return self.department_skill_root(department_id) / "history" / binding_id

    def proposal_path(self, department_id: str, proposal_id: str) -> Path:
        _validate_identifier(proposal_id, "proposal_id")
        return self.proposals_dir(department_id) / f"{proposal_id}.json"

    def binding_path(self, department_id: str, binding_id: str) -> Path:
        _validate_identifier(binding_id, "binding_id")
        return self.active_dir(department_id) / f"{binding_id}.json"

    def history_path(self, department_id: str, binding_id: str, revision: int) -> Path:
        _require_positive_int(revision, "revision")
        return self.history_dir(department_id, binding_id) / f"{revision}.json"

    def create_proposal(
        self, proposal: DepartmentSkillBindingProposal
    ) -> DepartmentSkillProposalCreateResult:
        """Persist one pending proposal, returning an existing duplicate if found."""

        if proposal.state is not DepartmentSkillProposalState.PENDING:
            raise DepartmentSkillError("new department skill proposals must be pending")
        existing = self.find_pending_duplicate(
            department_id=proposal.department_id,
            skill_id=proposal.skill_id,
            source_hash=proposal.source_hash,
        )
        if existing is not None:
            return DepartmentSkillProposalCreateResult(
                existing, DepartmentSkillProposalCreateStatus.EXISTING
            )
        path = self.proposal_path(proposal.department_id, proposal.proposal_id)
        if path.exists():
            raise DepartmentSkillError(
                f"Department skill proposal already exists: {proposal.proposal_id!r}"
            )
        atomic_json_write(path, department_skill_proposal_to_dict(proposal))
        return DepartmentSkillProposalCreateResult(proposal)

    def save_proposal(self, proposal: DepartmentSkillBindingProposal) -> Path:
        path = self.proposal_path(proposal.department_id, proposal.proposal_id)
        atomic_json_write(path, department_skill_proposal_to_dict(proposal))
        return path

    def load_proposal(
        self, department_id: str, proposal_id: str
    ) -> DepartmentSkillBindingProposal:
        path = self.proposal_path(department_id, proposal_id)
        if not path.exists():
            raise DepartmentSkillError(
                f"Department skill proposal does not exist: {proposal_id!r}"
            )
        return department_skill_proposal_from_dict(_load_json_object(path, "proposal"))

    def list_proposals(
        self,
        department_id: str,
        *,
        state: DepartmentSkillProposalState | str | None = None,
        skill_id: str | None = None,
    ) -> list[DepartmentSkillBindingProposal]:
        directory = self.proposals_dir(department_id)
        if not directory.exists():
            return []
        state_value = _proposal_state(state) if state is not None else None
        if skill_id is not None:
            _validate_identifier(skill_id, "skill_id")
        proposals = [
            department_skill_proposal_from_dict(_load_json_object(path, "proposal"))
            for path in directory.glob("*.json")
        ]
        filtered = [
            proposal
            for proposal in proposals
            if (state_value is None or proposal.state == state_value)
            and (skill_id is None or proposal.skill_id == skill_id)
        ]
        return sorted(
            filtered,
            key=lambda proposal: (proposal.created_at or "", proposal.proposal_id),
        )

    def find_pending_duplicate(
        self,
        *,
        department_id: str,
        skill_id: str,
        source_hash: str | None,
    ) -> DepartmentSkillBindingProposal | None:
        if source_hash is None:
            return None
        for proposal in self.list_proposals(
            department_id,
            state=DepartmentSkillProposalState.PENDING,
            skill_id=skill_id,
        ):
            if proposal.source_hash == source_hash:
                return proposal
        return None

    def save_binding(self, binding: DepartmentSkillBindingRecord) -> Path:
        path = self.binding_path(binding.department_id, binding.binding_id)
        atomic_json_write(path, department_skill_binding_to_dict(binding))
        return path

    def load_binding(
        self, department_id: str, binding_id: str
    ) -> DepartmentSkillBindingRecord:
        path = self.binding_path(department_id, binding_id)
        if not path.exists():
            raise DepartmentSkillError(
                f"Department skill binding does not exist: {binding_id!r}"
            )
        return department_skill_binding_from_dict(_load_json_object(path, "binding"))

    def list_active_bindings(self, department_id: str) -> list[DepartmentSkillBindingRecord]:
        directory = self.active_dir(department_id)
        if not directory.exists():
            return []
        bindings = [
            department_skill_binding_from_dict(_load_json_object(path, "binding"))
            for path in directory.glob("*.json")
        ]
        return sorted(
            [binding for binding in bindings if binding.active],
            key=lambda binding: (binding.skill_id, binding.binding_id),
        )

    def write_history(self, binding: DepartmentSkillBindingRecord) -> Path:
        path = self.history_path(
            binding.department_id, binding.binding_id, binding.revision
        )
        atomic_json_write(path, department_skill_binding_to_dict(binding))
        return path


@dataclass
class DepartmentSkillReviewService:
    """Review service that is allowed to promote proposals to active bindings."""

    store: DepartmentSkillBindingStore = field(default_factory=DepartmentSkillBindingStore)

    def approve(
        self, department_id: str, proposal_id: str, action: DepartmentSkillReviewAction
    ) -> DepartmentSkillBindingRecord:
        """Approve a proposal and write the active binding record."""

        proposal = self.store.load_proposal(department_id, proposal_id)
        self._validate_action(proposal, action, DepartmentSkillReviewDecision.APPROVE)
        if proposal.state not in {
            DepartmentSkillProposalState.PENDING,
            DepartmentSkillProposalState.CHANGES_REQUESTED,
        }:
            raise DepartmentSkillError("only pending proposals can be approved")
        if _requires_user_confirmation(proposal) and not action.user_confirmation_ref:
            raise DepartmentSkillError("user confirmation is required for this proposal")

        binding_id = action.supersede_binding_id or proposal.proposal_id
        revision = 1
        if action.supersede_binding_id is not None:
            current = self.store.load_binding(
                proposal.department_id, action.supersede_binding_id
            )
            self.store.write_history(replace(current, active=False))
            revision = current.revision + 1

        binding = DepartmentSkillBindingRecord(
            department_id=proposal.department_id,
            binding_id=binding_id,
            skill_id=proposal.skill_id,
            skill_source=proposal.skill_source,
            version_constraint=proposal.version_constraint,
            state=proposal.candidate_state,
            visibility=proposal.visibility,
            sensitivity=proposal.sensitivity,
            usage_guidance=proposal.candidate_guidance,
            applicability=proposal.applicability,
            disabled_conditions=proposal.disabled_conditions,
            limitations=proposal.limitations,
            risk_notes=proposal.risk_notes,
            tool_assumptions=proposal.tool_assumptions,
            owner=proposal.owner,
            source_refs=proposal.source_refs + action.audit_refs,
            revision=revision,
            active=True,
            accepted_at=action.reviewed_at,
            created_at=proposal.created_at,
            updated_at=action.reviewed_at,
            audit_summary=_review_audit_summary(proposal, action),
            replacement_skill_id=proposal.replacement_skill_id,
        )
        self.store.save_binding(binding)
        updated_state = (
            DepartmentSkillProposalState.SUPERSEDED
            if action.supersede_binding_id is not None
            else DepartmentSkillProposalState.APPROVED
        )
        self.store.save_proposal(
            _proposal_with_review_state(proposal, updated_state, action)
        )
        return binding

    def reject(
        self, department_id: str, proposal_id: str, action: DepartmentSkillReviewAction
    ) -> DepartmentSkillBindingProposal:
        return self._update_proposal_state(
            department_id,
            proposal_id,
            action,
            DepartmentSkillReviewDecision.REJECT,
            DepartmentSkillProposalState.REJECTED,
        )

    def request_changes(
        self, department_id: str, proposal_id: str, action: DepartmentSkillReviewAction
    ) -> DepartmentSkillBindingProposal:
        return self._update_proposal_state(
            department_id,
            proposal_id,
            action,
            DepartmentSkillReviewDecision.REQUEST_CHANGES,
            DepartmentSkillProposalState.CHANGES_REQUESTED,
        )

    def expire(
        self, department_id: str, proposal_id: str, action: DepartmentSkillReviewAction
    ) -> DepartmentSkillBindingProposal:
        return self._update_proposal_state(
            department_id,
            proposal_id,
            action,
            DepartmentSkillReviewDecision.EXPIRE,
            DepartmentSkillProposalState.EXPIRED,
        )

    def _update_proposal_state(
        self,
        department_id: str,
        proposal_id: str,
        action: DepartmentSkillReviewAction,
        expected_decision: DepartmentSkillReviewDecision,
        new_state: DepartmentSkillProposalState,
    ) -> DepartmentSkillBindingProposal:
        proposal = self.store.load_proposal(department_id, proposal_id)
        self._validate_action(proposal, action, expected_decision)
        if proposal.state is not DepartmentSkillProposalState.PENDING:
            raise DepartmentSkillError("only pending proposals can change review state")
        updated = _proposal_with_review_state(proposal, new_state, action)
        self.store.save_proposal(updated)
        return updated

    def _validate_action(
        self,
        proposal: DepartmentSkillBindingProposal,
        action: DepartmentSkillReviewAction,
        expected_decision: DepartmentSkillReviewDecision,
    ) -> None:
        if action.proposal_id != proposal.proposal_id:
            raise DepartmentSkillError("review action proposal_id does not match")
        if action.decision is not expected_decision:
            raise DepartmentSkillError("review action decision does not match")
        if not action.actor_id:
            raise DepartmentSkillError("review action actor_id is required")


def validate_department_skill_payload(payload: Mapping[str, Any]) -> None:
    """Reject raw skill material, private experience text, and secrets."""

    _reject_sensitive_payload(payload, "payload")


def proposal_from_skill_experience_input(
    proposal_input: SkillExperienceProposalInput,
    *,
    proposal_id: str,
    department_id: str,
    proposed_action: DepartmentSkillProposalAction | str = (
        DepartmentSkillProposalAction.ADD_BINDING
    ),
    candidate_state: DepartmentSkillBindingState | str = (
        DepartmentSkillBindingState.RECOMMENDED
    ),
    source_actor: str | None = None,
    created_at: str | None = None,
) -> DepartmentSkillBindingProposal:
    """Convert low-sensitivity private skill experience into a proposal."""

    return DepartmentSkillBindingProposal(
        proposal_id=proposal_id,
        department_id=department_id,
        proposed_action=proposed_action,
        skill_id=proposal_input.skill_id,
        candidate_guidance=proposal_input.summary,
        source_actor=source_actor or proposal_input.source_worker_id,
        source_refs=proposal_input.source_refs,
        rationale=proposal_input.applicability,
        source_hash=f"{proposal_input.source_worker_id}:{proposal_input.source_experience_id}",
        candidate_state=candidate_state,
        limitations=proposal_input.limitations,
        risk_notes=proposal_input.risk_notes,
        tool_assumptions=proposal_input.tool_assumptions,
        review_requirement=proposal_input.review_requirement,
        created_at=created_at,
        audit_summary=(
            f"Low-sensitivity skill experience proposal "
            f"{proposal_input.proposal_input_id}."
        ),
    )


def resolve_department_skill_bindings(
    store: DepartmentSkillBindingStore,
    department_id: str,
    *,
    inherited_department_ids: tuple[str, ...] = (),
) -> tuple[DepartmentSkillResolvedBinding, ...]:
    """Resolve active department bindings with conservative inheritance rules."""

    validate_org_node_id(department_id)
    resolved: dict[str, DepartmentSkillResolvedBinding] = {}

    for inherited_department_id in inherited_department_ids:
        validate_org_node_id(inherited_department_id)
        for binding in store.list_active_bindings(inherited_department_id):
            if binding.visibility not in {
                DepartmentSkillBindingVisibility.INHERITABLE_GUIDANCE,
                DepartmentSkillBindingVisibility.ORGANIZATION_GUIDANCE,
            }:
                continue
            _merge_resolved_binding(
                resolved,
                DepartmentSkillResolvedBinding(
                    binding=binding,
                    inherited=True,
                    source_department_id=inherited_department_id,
                    audit_summary=(
                        f"Inherited {binding.binding_id} from "
                        f"{inherited_department_id}."
                    ),
                ),
            )

    for binding in store.list_active_bindings(department_id):
        _merge_resolved_binding(
            resolved,
            DepartmentSkillResolvedBinding(
                binding=binding,
                inherited=False,
                source_department_id=department_id,
                audit_summary=f"Resolved local binding {binding.binding_id}.",
            ),
        )

    return tuple(
        resolved[skill_id]
        for skill_id in sorted(resolved, key=lambda value: (value, resolved[value].binding.binding_id))
    )


def validate_department_skill_applicability(
    binding: DepartmentSkillBindingRecord | DepartmentSkillResolvedBinding,
    request: DepartmentSkillApplicabilityRequest,
) -> DepartmentSkillApplicabilityResult:
    """Check whether one binding is safe to present as task skill guidance."""

    record = binding.binding if isinstance(binding, DepartmentSkillResolvedBinding) else binding
    reasons: list[str] = []
    required_review_refs: list[str] = []

    if not record.active or record.state is DepartmentSkillBindingState.DISABLED:
        reasons.append("disabled_binding")
    if record.state is DepartmentSkillBindingState.DEPRECATED:
        reasons.append("deprecated_binding")
    if record.department_id != request.department_id:
        inherited = (
            isinstance(binding, DepartmentSkillResolvedBinding) and binding.inherited
        )
        if not inherited:
            reasons.append("wrong_department")
    if record.applicability and request.task_type not in record.applicability:
        reasons.append("unsupported_task_type")
    if request.worker_role in record.disabled_conditions:
        reasons.append("wrong_worker_role")
    if record.skill_id not in request.allowed_skill_ids:
        reasons.append("profile_disallows_skill")

    missing_permissions = tuple(
        permission
        for permission in record.tool_assumptions
        if permission not in request.permission_names
    )
    if missing_permissions:
        reasons.append("missing_permission")

    if _sensitivity_exceeds(record.sensitivity, request.sensitivity):
        reasons.append("sensitive_task_blocked")
    if record.sensitivity is DepartmentSkillBindingSensitivity.USER_CONFIRMATION_REQUIRED:
        if request.confirmation_refs:
            required_review_refs.extend(request.confirmation_refs)
        else:
            reasons.append("user_confirmation_required")
    if record.state is DepartmentSkillBindingState.RESTRICTED:
        reasons.append("restricted_binding")

    unique_reasons = tuple(dict.fromkeys(reasons))
    if any(reason in _BLOCKING_APPLICABILITY_REASONS for reason in unique_reasons):
        decision = DepartmentSkillApplicabilityDecision.BLOCKED
        summary = ""
    elif unique_reasons:
        decision = DepartmentSkillApplicabilityDecision.NEEDS_REVIEW
        summary = record.usage_guidance
    elif record.state is DepartmentSkillBindingState.RECOMMENDED:
        decision = DepartmentSkillApplicabilityDecision.CANDIDATE_ONLY
        summary = record.usage_guidance
    else:
        decision = DepartmentSkillApplicabilityDecision.ALLOWED
        summary = record.usage_guidance

    result = DepartmentSkillApplicabilityResult(
        skill_id=record.skill_id,
        binding_id=record.binding_id,
        decision=decision,
        reasons=unique_reasons,
        safe_guidance_summary=summary,
        required_review_refs=tuple(required_review_refs),
        audit_summary=(
            f"Applicability for {record.skill_id} in task type "
            f"{request.task_type}: {decision.value}."
        ),
    )
    validate_department_skill_payload(department_skill_applicability_result_to_dict(result))
    return result


def guard_department_skill_usage(
    binding: DepartmentSkillBindingRecord | DepartmentSkillResolvedBinding,
    applicability: DepartmentSkillApplicabilityResult,
    *,
    runtime_type: str,
) -> DepartmentSkillGuardrailResult:
    """Convert applicability into a final safe-candidate guardrail result."""

    _require_string(runtime_type, "runtime_type")
    record = binding.binding if isinstance(binding, DepartmentSkillResolvedBinding) else binding
    reasons = list(applicability.reasons)
    if runtime_type != "internal_worker":
        reasons.append(DepartmentSkillGuardrailReason.EXTERNAL_RUNTIME_SUMMARY_ONLY.value)
    unique_reasons = tuple(dict.fromkeys(reasons))

    if _only_deprecated_reason(unique_reasons):
        decision = DepartmentSkillGuardrailDecision.WARNING_ONLY
    elif applicability.decision is DepartmentSkillApplicabilityDecision.BLOCKED:
        decision = DepartmentSkillGuardrailDecision.BLOCKED
    elif DepartmentSkillGuardrailReason.USER_CONFIRMATION_REQUIRED.value in unique_reasons:
        decision = DepartmentSkillGuardrailDecision.NEEDS_USER_CONFIRMATION
    elif any(reason in _OWNER_REVIEW_REASONS for reason in unique_reasons):
        decision = DepartmentSkillGuardrailDecision.NEEDS_OWNER_REVIEW
    elif DepartmentSkillGuardrailReason.DEPRECATED_BINDING.value in unique_reasons:
        decision = DepartmentSkillGuardrailDecision.WARNING_ONLY
    else:
        decision = DepartmentSkillGuardrailDecision.ALLOWED_CANDIDATE

    safe_candidate = None
    if decision in {
        DepartmentSkillGuardrailDecision.ALLOWED_CANDIDATE,
        DepartmentSkillGuardrailDecision.NEEDS_OWNER_REVIEW,
        DepartmentSkillGuardrailDecision.NEEDS_USER_CONFIRMATION,
    }:
        guidance = applicability.safe_guidance_summary or record.usage_guidance
        safe_candidate = DepartmentSkillSafeCandidate(
            skill_id=record.skill_id,
            binding_id=record.binding_id,
            title=record.skill_id.replace("_", " ").title(),
            guidance_summary=guidance,
            constraints=record.limitations + record.risk_notes,
            audit_refs=record.source_refs,
            replacement_skill_id=record.replacement_skill_id,
        )
    elif (
        decision is DepartmentSkillGuardrailDecision.WARNING_ONLY
        and record.replacement_skill_id is not None
    ):
        safe_candidate = DepartmentSkillSafeCandidate(
            skill_id=record.skill_id,
            binding_id=record.binding_id,
            title=record.skill_id.replace("_", " ").title(),
            guidance_summary="Deprecated department skill binding withheld.",
            constraints=("Use replacement skill reference instead.",),
            audit_refs=record.source_refs,
            replacement_skill_id=record.replacement_skill_id,
        )

    result = DepartmentSkillGuardrailResult(
        skill_id=record.skill_id,
        binding_id=record.binding_id,
        decision=decision,
        reasons=unique_reasons,
        safe_candidate=safe_candidate,
        review_requirement=_guardrail_review_requirement(decision),
        audit_summary=(
            f"Guardrail for {record.skill_id}: {decision.value}; "
            f"reasons={','.join(unique_reasons) or 'none'}."
        ),
    )
    validate_department_skill_payload(department_skill_guardrail_result_to_dict(result))
    return result


def department_skill_dir(worker_agents_home: str | Path, department_id: str) -> Path:
    """Return the durable department skill root without creating it."""

    validate_org_node_id(department_id)
    return (
        Path(worker_agents_home)
        / "organization"
        / "departments"
        / department_id
        / "skills"
    )


def department_skill_binding_to_dict(
    binding: DepartmentSkillBindingRecord,
) -> dict[str, Any]:
    """Return a deterministic JSON-ready active department skill binding."""

    return {
        "department_id": binding.department_id,
        "binding_id": binding.binding_id,
        "schema_version": binding.schema_version,
        "skill_id": binding.skill_id,
        "skill_source": binding.skill_source,
        "version_constraint": binding.version_constraint,
        "state": binding.state.value,
        "visibility": binding.visibility.value,
        "sensitivity": binding.sensitivity.value,
        "usage_guidance": binding.usage_guidance,
        "applicability": list(binding.applicability),
        "disabled_conditions": list(binding.disabled_conditions),
        "limitations": list(binding.limitations),
        "risk_notes": list(binding.risk_notes),
        "tool_assumptions": list(binding.tool_assumptions),
        "owner": binding.owner,
        "source_refs": list(binding.source_refs),
        "revision": binding.revision,
        "active": binding.active,
        "accepted_at": binding.accepted_at,
        "created_at": binding.created_at,
        "updated_at": binding.updated_at,
        "audit_summary": binding.audit_summary,
        "replacement_skill_id": binding.replacement_skill_id,
    }


def department_skill_binding_from_dict(
    data: Mapping[str, Any],
) -> DepartmentSkillBindingRecord:
    """Load an active department skill binding after boundary validation."""

    data = _require_mapping(data, "department skill binding")
    _reject_unknown_fields(data, _BINDING_FIELDS, "department skill binding")
    return DepartmentSkillBindingRecord(
        department_id=_require_string(data.get("department_id"), "department_id"),
        binding_id=_require_string(data.get("binding_id"), "binding_id"),
        schema_version=data.get("schema_version", DEPARTMENT_SKILL_SCHEMA_VERSION),
        skill_id=_require_string(data.get("skill_id"), "skill_id"),
        skill_source=_require_string(data.get("skill_source"), "skill_source"),
        version_constraint=_string_value(
            data.get("version_constraint", ""), "version_constraint"
        ),
        state=data.get("state", DepartmentSkillBindingState.RECOMMENDED),
        visibility=data.get(
            "visibility", DepartmentSkillBindingVisibility.PRIVATE_TO_DEPARTMENT
        ),
        sensitivity=data.get("sensitivity", DepartmentSkillBindingSensitivity.LOW),
        usage_guidance=_require_string(data.get("usage_guidance"), "usage_guidance"),
        applicability=_string_tuple(data.get("applicability", ()), "applicability"),
        disabled_conditions=_string_tuple(
            data.get("disabled_conditions", ()), "disabled_conditions"
        ),
        limitations=_string_tuple(data.get("limitations", ()), "limitations"),
        risk_notes=_string_tuple(data.get("risk_notes", ()), "risk_notes"),
        tool_assumptions=_string_tuple(
            data.get("tool_assumptions", ()), "tool_assumptions"
        ),
        owner=_string_value(data.get("owner", ""), "owner"),
        source_refs=_string_tuple(data.get("source_refs", ()), "source_refs"),
        revision=data.get("revision", 1),
        active=data.get("active", True),
        accepted_at=_optional_string(data.get("accepted_at"), "accepted_at"),
        created_at=_optional_string(data.get("created_at"), "created_at"),
        updated_at=_optional_string(data.get("updated_at"), "updated_at"),
        audit_summary=_string_value(data.get("audit_summary", ""), "audit_summary"),
        replacement_skill_id=_optional_string(
            data.get("replacement_skill_id"), "replacement_skill_id"
        ),
    )


def department_skill_proposal_to_dict(
    proposal: DepartmentSkillBindingProposal,
) -> dict[str, Any]:
    """Return a deterministic JSON-ready department skill proposal."""

    return {
        "proposal_id": proposal.proposal_id,
        "department_id": proposal.department_id,
        "schema_version": proposal.schema_version,
        "proposed_action": proposal.proposed_action.value,
        "skill_id": proposal.skill_id,
        "skill_source": proposal.skill_source,
        "version_constraint": proposal.version_constraint,
        "candidate_state": proposal.candidate_state.value,
        "candidate_guidance": proposal.candidate_guidance,
        "source_actor": proposal.source_actor,
        "source_refs": list(proposal.source_refs),
        "rationale": proposal.rationale,
        "source_hash": proposal.source_hash,
        "visibility": proposal.visibility.value,
        "sensitivity": proposal.sensitivity.value,
        "applicability": list(proposal.applicability),
        "disabled_conditions": list(proposal.disabled_conditions),
        "limitations": list(proposal.limitations),
        "risk_notes": list(proposal.risk_notes),
        "tool_assumptions": list(proposal.tool_assumptions),
        "owner": proposal.owner,
        "review_requirement": proposal.review_requirement,
        "state": proposal.state.value,
        "created_at": proposal.created_at,
        "updated_at": proposal.updated_at,
        "audit_summary": proposal.audit_summary,
        "replacement_skill_id": proposal.replacement_skill_id,
    }


def department_skill_proposal_from_dict(
    data: Mapping[str, Any],
) -> DepartmentSkillBindingProposal:
    """Load a department skill proposal after boundary validation."""

    data = _require_mapping(data, "department skill proposal")
    _reject_unknown_fields(data, _PROPOSAL_FIELDS, "department skill proposal")
    return DepartmentSkillBindingProposal(
        proposal_id=_require_string(data.get("proposal_id"), "proposal_id"),
        department_id=_require_string(data.get("department_id"), "department_id"),
        schema_version=data.get("schema_version", DEPARTMENT_SKILL_SCHEMA_VERSION),
        proposed_action=_require_string(data.get("proposed_action"), "proposed_action"),
        skill_id=_require_string(data.get("skill_id"), "skill_id"),
        skill_source=_require_string(data.get("skill_source"), "skill_source"),
        version_constraint=_string_value(
            data.get("version_constraint", ""), "version_constraint"
        ),
        candidate_state=data.get("candidate_state", DepartmentSkillBindingState.RECOMMENDED),
        candidate_guidance=_require_string(
            data.get("candidate_guidance"), "candidate_guidance"
        ),
        source_actor=_require_string(data.get("source_actor"), "source_actor"),
        source_refs=_string_tuple(data.get("source_refs", ()), "source_refs"),
        rationale=_string_value(data.get("rationale", ""), "rationale"),
        source_hash=_optional_string(data.get("source_hash"), "source_hash"),
        visibility=data.get(
            "visibility", DepartmentSkillBindingVisibility.PRIVATE_TO_DEPARTMENT
        ),
        sensitivity=data.get("sensitivity", DepartmentSkillBindingSensitivity.INTERNAL),
        applicability=_string_tuple(data.get("applicability", ()), "applicability"),
        disabled_conditions=_string_tuple(
            data.get("disabled_conditions", ()), "disabled_conditions"
        ),
        limitations=_string_tuple(data.get("limitations", ()), "limitations"),
        risk_notes=_string_tuple(data.get("risk_notes", ()), "risk_notes"),
        tool_assumptions=_string_tuple(
            data.get("tool_assumptions", ()), "tool_assumptions"
        ),
        owner=_string_value(data.get("owner", ""), "owner"),
        review_requirement=_require_string(
            data.get("review_requirement"), "review_requirement"
        ),
        state=data.get("state", DepartmentSkillProposalState.PENDING),
        created_at=_optional_string(data.get("created_at"), "created_at"),
        updated_at=_optional_string(data.get("updated_at"), "updated_at"),
        audit_summary=_string_value(data.get("audit_summary", ""), "audit_summary"),
        replacement_skill_id=_optional_string(
            data.get("replacement_skill_id"), "replacement_skill_id"
        ),
    )


def department_skill_resolved_binding_to_dict(
    resolved: DepartmentSkillResolvedBinding,
) -> dict[str, Any]:
    """Return a JSON-safe resolved binding view for policy callers."""

    return {
        "binding": department_skill_binding_to_dict(resolved.binding),
        "inherited": resolved.inherited,
        "source_department_id": resolved.source_department_id,
        "audit_summary": resolved.audit_summary,
    }


def department_skill_applicability_result_to_dict(
    result: DepartmentSkillApplicabilityResult,
) -> dict[str, Any]:
    """Return a JSON-safe applicability result for guardrail callers."""

    return {
        "skill_id": result.skill_id,
        "binding_id": result.binding_id,
        "decision": result.decision.value,
        "reasons": list(result.reasons),
        "safe_guidance_summary": result.safe_guidance_summary,
        "required_review_refs": list(result.required_review_refs),
        "audit_summary": result.audit_summary,
    }


def department_skill_safe_candidate_to_dict(
    candidate: DepartmentSkillSafeCandidate,
) -> dict[str, Any]:
    """Return the field-limited skill view allowed past guardrails."""

    return {
        "skill_id": candidate.skill_id,
        "binding_id": candidate.binding_id,
        "title": candidate.title,
        "guidance_summary": candidate.guidance_summary,
        "constraints": list(candidate.constraints),
        "audit_refs": list(candidate.audit_refs),
        "replacement_skill_id": candidate.replacement_skill_id,
    }


def department_skill_guardrail_result_to_dict(
    result: DepartmentSkillGuardrailResult,
) -> dict[str, Any]:
    """Return a JSON-safe guardrail result for context policy callers."""

    return {
        "skill_id": result.skill_id,
        "binding_id": result.binding_id,
        "decision": result.decision.value,
        "reasons": list(result.reasons),
        "safe_candidate": (
            department_skill_safe_candidate_to_dict(result.safe_candidate)
            if result.safe_candidate is not None
            else None
        ),
        "review_requirement": result.review_requirement,
        "audit_summary": result.audit_summary,
    }


_BINDING_FIELDS = {
    "department_id",
    "binding_id",
    "schema_version",
    "skill_id",
    "skill_source",
    "version_constraint",
    "state",
    "visibility",
    "sensitivity",
    "usage_guidance",
    "applicability",
    "disabled_conditions",
    "limitations",
    "risk_notes",
    "tool_assumptions",
    "owner",
    "source_refs",
    "revision",
    "active",
    "accepted_at",
    "created_at",
    "updated_at",
    "audit_summary",
    "replacement_skill_id",
}

_PROPOSAL_FIELDS = {
    "proposal_id",
    "department_id",
    "schema_version",
    "proposed_action",
    "skill_id",
    "skill_source",
    "version_constraint",
    "candidate_state",
    "candidate_guidance",
    "source_actor",
    "source_refs",
    "rationale",
    "source_hash",
    "visibility",
    "sensitivity",
    "applicability",
    "disabled_conditions",
    "limitations",
    "risk_notes",
    "tool_assumptions",
    "owner",
    "review_requirement",
    "state",
    "created_at",
    "updated_at",
    "audit_summary",
    "replacement_skill_id",
}


def _require_schema_version(schema_version: int) -> None:
    if schema_version != DEPARTMENT_SKILL_SCHEMA_VERSION:
        raise DepartmentSkillError(
            f"Unsupported department skill schema_version: {schema_version!r}"
        )


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise DepartmentSkillError(f"{field_name} must be a non-empty string")
    return value


def _string_value(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise DepartmentSkillError(f"{field_name} must be a string")
    return value


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, field_name)


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise DepartmentSkillError(f"{field_name} must be a list of strings")
    return tuple(_require_string(item, field_name) for item in value)


def _coerce_string_tuple(instance: object, field_name: str) -> None:
    object.__setattr__(
        instance,
        field_name,
        tuple(_require_string(item, field_name) for item in getattr(instance, field_name)),
    )


def _require_positive_int(value: Any, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DepartmentSkillError(f"{field_name} must be a positive integer")


def _validate_identifier(value: str, field_name: str) -> str:
    _require_string(value, field_name)
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise DepartmentSkillError(f"{field_name} must be a single path segment")
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
        raise DepartmentSkillError(f"{field_name} must stay within allowed storage")
    return value


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DepartmentSkillError(f"{field_name} must be an object")
    return value


def _reject_unknown_fields(
    data: Mapping[str, Any], allowed_fields: set[str], field_name: str
) -> None:
    unknown_fields = sorted(set(data) - allowed_fields)
    if unknown_fields:
        joined = ", ".join(unknown_fields)
        raise DepartmentSkillError(f"{field_name} has unknown fields: {joined}")


def _binding_state(value: DepartmentSkillBindingState | str) -> DepartmentSkillBindingState:
    try:
        return (
            value
            if isinstance(value, DepartmentSkillBindingState)
            else DepartmentSkillBindingState(value)
        )
    except ValueError as exc:
        raise DepartmentSkillError(f"Unknown department skill state: {value!r}") from exc


def _binding_visibility(
    value: DepartmentSkillBindingVisibility | str,
) -> DepartmentSkillBindingVisibility:
    try:
        return (
            value
            if isinstance(value, DepartmentSkillBindingVisibility)
            else DepartmentSkillBindingVisibility(value)
        )
    except ValueError as exc:
        raise DepartmentSkillError(
            f"Unknown department skill visibility: {value!r}"
        ) from exc


def _binding_sensitivity(
    value: DepartmentSkillBindingSensitivity | str,
) -> DepartmentSkillBindingSensitivity:
    try:
        return (
            value
            if isinstance(value, DepartmentSkillBindingSensitivity)
            else DepartmentSkillBindingSensitivity(value)
        )
    except ValueError as exc:
        raise DepartmentSkillError(
            f"Unknown department skill sensitivity: {value!r}"
        ) from exc


def _proposal_state(value: DepartmentSkillProposalState | str) -> DepartmentSkillProposalState:
    try:
        return (
            value
            if isinstance(value, DepartmentSkillProposalState)
            else DepartmentSkillProposalState(value)
        )
    except ValueError as exc:
        raise DepartmentSkillError(
            f"Unknown department skill proposal state: {value!r}"
        ) from exc


def _proposal_action(
    value: DepartmentSkillProposalAction | str,
) -> DepartmentSkillProposalAction:
    try:
        return (
            value
            if isinstance(value, DepartmentSkillProposalAction)
            else DepartmentSkillProposalAction(value)
        )
    except ValueError as exc:
        raise DepartmentSkillError(
            f"Unknown department skill proposal action: {value!r}"
        ) from exc


def _applicability_decision(
    value: DepartmentSkillApplicabilityDecision | str,
) -> DepartmentSkillApplicabilityDecision:
    try:
        return (
            value
            if isinstance(value, DepartmentSkillApplicabilityDecision)
            else DepartmentSkillApplicabilityDecision(value)
        )
    except ValueError as exc:
        raise DepartmentSkillError(
            f"Unknown department skill applicability decision: {value!r}"
        ) from exc


def _guardrail_decision(
    value: DepartmentSkillGuardrailDecision | str,
) -> DepartmentSkillGuardrailDecision:
    try:
        return (
            value
            if isinstance(value, DepartmentSkillGuardrailDecision)
            else DepartmentSkillGuardrailDecision(value)
        )
    except ValueError as exc:
        raise DepartmentSkillError(
            f"Unknown department skill guardrail decision: {value!r}"
        ) from exc


def _guardrail_review_requirement(
    decision: DepartmentSkillGuardrailDecision,
) -> str:
    if decision is DepartmentSkillGuardrailDecision.NEEDS_USER_CONFIRMATION:
        return "user_confirmation"
    if decision is DepartmentSkillGuardrailDecision.NEEDS_OWNER_REVIEW:
        return "department_owner_review"
    if decision is DepartmentSkillGuardrailDecision.WARNING_ONLY:
        return "deprecated_binding_review"
    return ""


def _only_deprecated_reason(reasons: tuple[str, ...]) -> bool:
    return reasons == (DepartmentSkillGuardrailReason.DEPRECATED_BINDING.value,)


def _proposal_create_status(
    value: DepartmentSkillProposalCreateStatus | str,
) -> DepartmentSkillProposalCreateStatus:
    try:
        return (
            value
            if isinstance(value, DepartmentSkillProposalCreateStatus)
            else DepartmentSkillProposalCreateStatus(value)
        )
    except ValueError as exc:
        raise DepartmentSkillError(
            f"Unknown department skill create status: {value!r}"
        ) from exc


def _reviewer_role(value: DepartmentSkillReviewerRole | str) -> DepartmentSkillReviewerRole:
    try:
        return (
            value
            if isinstance(value, DepartmentSkillReviewerRole)
            else DepartmentSkillReviewerRole(value)
        )
    except ValueError as exc:
        raise DepartmentSkillError(
            f"Unknown department skill reviewer role: {value!r}"
        ) from exc


def _review_decision(
    value: DepartmentSkillReviewDecision | str,
) -> DepartmentSkillReviewDecision:
    try:
        return (
            value
            if isinstance(value, DepartmentSkillReviewDecision)
            else DepartmentSkillReviewDecision(value)
        )
    except ValueError as exc:
        raise DepartmentSkillError(
            f"Unknown department skill review decision: {value!r}"
        ) from exc


def _requires_user_confirmation(proposal: DepartmentSkillBindingProposal) -> bool:
    return (
        proposal.sensitivity
        is DepartmentSkillBindingSensitivity.USER_CONFIRMATION_REQUIRED
    )


def _review_audit_summary(
    proposal: DepartmentSkillBindingProposal, action: DepartmentSkillReviewAction
) -> str:
    return (
        f"{action.decision.value} department skill proposal "
        f"{proposal.proposal_id} by {action.actor_role.value}:{action.actor_id}. "
        f"Reason: {action.reason}"
    )


def _proposal_with_review_state(
    proposal: DepartmentSkillBindingProposal,
    state: DepartmentSkillProposalState,
    action: DepartmentSkillReviewAction,
) -> DepartmentSkillBindingProposal:
    return replace(
        proposal,
        state=state,
        updated_at=action.reviewed_at,
        audit_summary=_review_audit_summary(proposal, action),
    )


def _merge_resolved_binding(
    resolved: dict[str, DepartmentSkillResolvedBinding],
    candidate: DepartmentSkillResolvedBinding,
) -> None:
    existing = resolved.get(candidate.binding.skill_id)
    if existing is None or _is_more_conservative(candidate.binding, existing.binding):
        resolved[candidate.binding.skill_id] = candidate


def _is_more_conservative(
    candidate: DepartmentSkillBindingRecord,
    existing: DepartmentSkillBindingRecord,
) -> bool:
    candidate_rank = _STATE_RANK[candidate.state]
    existing_rank = _STATE_RANK[existing.state]
    if candidate_rank != existing_rank:
        return candidate_rank > existing_rank
    # For equal state, prefer local overrides and then the newest revision.
    if candidate.department_id != existing.department_id:
        return True
    return candidate.revision >= existing.revision


def _sensitivity_exceeds(
    value: DepartmentSkillBindingSensitivity,
    maximum: DepartmentSkillBindingSensitivity,
) -> bool:
    return _SENSITIVITY_RANK[value] > _SENSITIVITY_RANK[maximum]


def _load_json_object(path: Path, field_name: str) -> Mapping[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DepartmentSkillError(f"{field_name} is not valid JSON: {path}") from exc
    return _require_mapping(data, field_name)


def _reject_sensitive_payload(value: Any, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in _SENSITIVE_FIELD_NAMES:
                raise DepartmentSkillError(f"{path}.{key_text} contains sensitive data")
            _reject_sensitive_payload(item, f"{path}.{key_text}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_sensitive_payload(item, f"{path}[{index}]")

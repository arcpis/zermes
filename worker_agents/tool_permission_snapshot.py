"""Read-only worker tool permission snapshots."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from .private_assets import (
    PRIVATE_ASSET_SCHEMA_VERSION,
    PrivateAssetError,
    validate_private_asset_payload,
)
from .profile import WorkerAgentProfile, validate_worker_id, worker_profile_to_dict


class ToolPolicyViolationCode(StrEnum):
    """Reasons a department policy candidate exceeds worker permissions."""

    TOOL_NOT_IN_PROFILE = "tool_not_in_profile"
    WORKSPACE_OUT_OF_SCOPE = "workspace_out_of_scope"
    TASK_TOKEN_BUDGET_EXCEEDED = "task_token_budget_exceeded"
    TURN_TOKEN_BUDGET_EXCEEDED = "turn_token_budget_exceeded"
    COST_BUDGET_EXCEEDED = "cost_budget_exceeded"
    HIGH_RISK_REQUIRES_APPROVAL = "high_risk_requires_approval"


@dataclass(frozen=True)
class ToolPolicyCompatibilityResult:
    """Result of checking a requested policy against one worker snapshot."""

    allowed: bool
    violations: tuple[str, ...] = ()
    approval_required: tuple[str, ...] = ()
    audit_summary: str = ""
    schema_version: int = PRIVATE_ASSET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        if not isinstance(self.allowed, bool):
            raise PrivateAssetError("allowed must be a boolean")
        object.__setattr__(
            self, "violations", tuple(_require_string(v, "violations") for v in self.violations)
        )
        object.__setattr__(
            self,
            "approval_required",
            tuple(_require_string(v, "approval_required") for v in self.approval_required),
        )
        if not isinstance(self.audit_summary, str):
            raise PrivateAssetError("audit_summary must be a string")


@dataclass(frozen=True)
class WorkerToolPermissionSnapshot:
    """Credential-free read-only view of a worker profile's permissions."""

    worker_id: str
    profile_hash: str
    allowed_tools: tuple[str, ...] = ()
    approval_required_tools: tuple[str, ...] = ()
    read_roots: tuple[str, ...] = ()
    write_roots: tuple[str, ...] = ()
    max_task_tokens: int = 0
    max_turn_tokens: int = 0
    max_task_cost_usd: float | None = None
    created_at: str | None = None
    redaction_status: str = "credentials_excluded"
    schema_version: int = PRIVATE_ASSET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        validate_worker_id(self.worker_id)
        _require_string(self.profile_hash, "profile_hash")
        object.__setattr__(
            self, "allowed_tools", tuple(_require_string(v, "allowed_tools") for v in self.allowed_tools)
        )
        object.__setattr__(
            self,
            "approval_required_tools",
            tuple(
                _require_string(v, "approval_required_tools")
                for v in self.approval_required_tools
            ),
        )
        object.__setattr__(
            self, "read_roots", tuple(_require_string(v, "read_roots") for v in self.read_roots)
        )
        object.__setattr__(
            self, "write_roots", tuple(_require_string(v, "write_roots") for v in self.write_roots)
        )
        _non_negative_int(self.max_task_tokens, "max_task_tokens")
        _non_negative_int(self.max_turn_tokens, "max_turn_tokens")
        if self.max_task_cost_usd is not None:
            _non_negative_number(self.max_task_cost_usd, "max_task_cost_usd")
        if self.created_at is not None:
            _require_string(self.created_at, "created_at")
        _require_string(self.redaction_status, "redaction_status")


@dataclass(frozen=True)
class ToolPolicyCandidate:
    """Department or task tool policy request before profile cross-checking."""

    requested_tools: tuple[str, ...] = ()
    requested_read_roots: tuple[str, ...] = ()
    requested_write_roots: tuple[str, ...] = ()
    requested_max_task_tokens: int | None = None
    requested_max_turn_tokens: int | None = None
    requested_max_task_cost_usd: float | None = None
    high_risk_tools: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "requested_tools",
            tuple(_require_string(v, "requested_tools") for v in self.requested_tools),
        )
        object.__setattr__(
            self,
            "requested_read_roots",
            tuple(
                _require_string(v, "requested_read_roots")
                for v in self.requested_read_roots
            ),
        )
        object.__setattr__(
            self,
            "requested_write_roots",
            tuple(
                _require_string(v, "requested_write_roots")
                for v in self.requested_write_roots
            ),
        )
        object.__setattr__(
            self,
            "high_risk_tools",
            tuple(_require_string(v, "high_risk_tools") for v in self.high_risk_tools),
        )
        for value, field_name in (
            (self.requested_max_task_tokens, "requested_max_task_tokens"),
            (self.requested_max_turn_tokens, "requested_max_turn_tokens"),
        ):
            if value is not None:
                _non_negative_int(value, field_name)
        if self.requested_max_task_cost_usd is not None:
            _non_negative_number(
                self.requested_max_task_cost_usd, "requested_max_task_cost_usd"
            )
        validate_private_asset_payload(self.metadata)


def build_tool_permission_snapshot(
    profile: WorkerAgentProfile,
    *,
    created_at: str | None = None,
) -> WorkerToolPermissionSnapshot:
    """Build a credential-free permission snapshot from a worker profile."""

    profile_payload = worker_profile_to_dict(profile)
    validate_private_asset_payload(profile_payload)
    profile_hash = hashlib.sha256(
        json.dumps(profile_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return WorkerToolPermissionSnapshot(
        worker_id=profile.worker_id,
        profile_hash=f"sha256:{profile_hash}",
        allowed_tools=profile.tools.allowed_tools,
        approval_required_tools=profile.tools.approval_required_tools,
        read_roots=profile.workspace.read_roots,
        write_roots=profile.workspace.write_roots,
        max_task_tokens=profile.budgets.max_task_tokens,
        max_turn_tokens=profile.budgets.max_turn_tokens,
        max_task_cost_usd=profile.budgets.max_task_cost_usd,
        created_at=created_at,
    )


def check_tool_policy_within_worker_snapshot(
    snapshot: WorkerToolPermissionSnapshot,
    candidate: ToolPolicyCandidate,
) -> ToolPolicyCompatibilityResult:
    """Return whether a policy candidate stays within worker permissions."""

    violations: list[str] = []
    approval_required: list[str] = []

    allowed_tools = set(snapshot.allowed_tools)
    approval_tools = set(snapshot.approval_required_tools)
    for tool in candidate.requested_tools:
        if tool not in allowed_tools:
            violations.append(ToolPolicyViolationCode.TOOL_NOT_IN_PROFILE.value)
    for tool in candidate.high_risk_tools:
        if tool in approval_tools:
            approval_required.append(
                ToolPolicyViolationCode.HIGH_RISK_REQUIRES_APPROVAL.value
            )
        elif tool not in allowed_tools:
            violations.append(ToolPolicyViolationCode.TOOL_NOT_IN_PROFILE.value)

    if not set(candidate.requested_read_roots).issubset(snapshot.read_roots):
        violations.append(ToolPolicyViolationCode.WORKSPACE_OUT_OF_SCOPE.value)
    if not set(candidate.requested_write_roots).issubset(snapshot.write_roots):
        violations.append(ToolPolicyViolationCode.WORKSPACE_OUT_OF_SCOPE.value)

    if _exceeds_limit(
        candidate.requested_max_task_tokens, snapshot.max_task_tokens
    ):
        violations.append(ToolPolicyViolationCode.TASK_TOKEN_BUDGET_EXCEEDED.value)
    if _exceeds_limit(
        candidate.requested_max_turn_tokens, snapshot.max_turn_tokens
    ):
        violations.append(ToolPolicyViolationCode.TURN_TOKEN_BUDGET_EXCEEDED.value)
    if _exceeds_float_limit(
        candidate.requested_max_task_cost_usd, snapshot.max_task_cost_usd
    ):
        violations.append(ToolPolicyViolationCode.COST_BUDGET_EXCEEDED.value)

    unique_violations = tuple(dict.fromkeys(violations))
    unique_approvals = tuple(dict.fromkeys(approval_required))
    return ToolPolicyCompatibilityResult(
        allowed=not unique_violations and not unique_approvals,
        violations=unique_violations,
        approval_required=unique_approvals,
        audit_summary=(
            "candidate stays within worker profile"
            if not unique_violations and not unique_approvals
            else "candidate requires rejection or approval"
        ),
    )


def tool_permission_snapshot_to_dict(
    snapshot: WorkerToolPermissionSnapshot,
) -> dict[str, Any]:
    """Return a deterministic JSON-ready permission snapshot mapping."""

    return {
        "worker_id": snapshot.worker_id,
        "schema_version": snapshot.schema_version,
        "profile_hash": snapshot.profile_hash,
        "allowed_tools": list(snapshot.allowed_tools),
        "approval_required_tools": list(snapshot.approval_required_tools),
        "read_roots": list(snapshot.read_roots),
        "write_roots": list(snapshot.write_roots),
        "max_task_tokens": snapshot.max_task_tokens,
        "max_turn_tokens": snapshot.max_turn_tokens,
        "max_task_cost_usd": snapshot.max_task_cost_usd,
        "created_at": snapshot.created_at,
        "redaction_status": snapshot.redaction_status,
    }


def compatibility_result_to_dict(
    result: ToolPolicyCompatibilityResult,
) -> dict[str, Any]:
    """Return a deterministic JSON-ready compatibility result mapping."""

    return {
        "allowed": result.allowed,
        "schema_version": result.schema_version,
        "violations": list(result.violations),
        "approval_required": list(result.approval_required),
        "audit_summary": result.audit_summary,
    }


def _require_schema_version(schema_version: int) -> None:
    if schema_version != PRIVATE_ASSET_SCHEMA_VERSION:
        raise PrivateAssetError(
            f"Unsupported tool permission schema_version: {schema_version!r}"
        )


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise PrivateAssetError(f"{field_name} must be a non-empty string")
    return value


def _non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PrivateAssetError(f"{field_name} must be a non-negative integer")
    return value


def _non_negative_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise PrivateAssetError(f"{field_name} must be a non-negative number")
    return float(value)


def _exceeds_limit(requested: int | None, limit: int) -> bool:
    if requested is None:
        return False
    # A zero profile limit means the worker has no budget to grant.
    return requested > limit


def _exceeds_float_limit(requested: float | None, limit: float | None) -> bool:
    if requested is None:
        return False
    return limit is None or requested > limit

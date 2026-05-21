"""Delegation policy checks for worker-created temporary subagents."""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from pathlib import PurePosixPath

from .profile import WorkerAgentProfile
from .runtime_contract import RuntimeType
from .temporary_subagents import TemporarySubagentRequest


class TemporarySubagentPolicyError(ValueError):
    """Raised when temporary subagent delegation policy input is invalid."""


@dataclass(frozen=True)
class TemporarySubagentEffectivePolicy:
    """Concrete limits that a runner must use for one temporary subagent."""

    runtime_type: RuntimeType
    model_name: str | None
    allowed_tools: tuple[str, ...]
    workspace_read_roots: tuple[str, ...]
    workspace_write_roots: tuple[str, ...]
    max_task_tokens: int | None
    max_task_cost_usd: float | None
    timeout_seconds: int | None
    parent_worker_id: str
    task_id: str
    delegation_id: str


@dataclass(frozen=True)
class TemporarySubagentPolicyDecision:
    """Allow/deny decision with an audit-safe reason and effective limits."""

    allowed: bool
    reason_code: str
    message: str
    effective_policy: TemporarySubagentEffectivePolicy | None = None
    audit_summary: str | None = None


def evaluate_temporary_subagent_policy(
    parent_profile: WorkerAgentProfile,
    request: TemporarySubagentRequest,
    *,
    active_child_count: int = 0,
    remaining_task_tokens: int | None = None,
) -> TemporarySubagentPolicyDecision:
    """Return the launch decision for a temporary subagent request."""

    _validate_policy_inputs(parent_profile, request, active_child_count)
    if not parent_profile.delegation.allow_temporary_child_agents:
        return _deny("delegation_disabled", "Parent worker cannot create temporary subagents.")
    if parent_profile.worker_id != request.parent_worker_id:
        return _deny("parent_mismatch", "Request parent does not match worker profile.")
    if active_child_count >= parent_profile.limits.max_concurrent_tasks:
        return _deny("concurrency_limit", "Parent worker has no temporary child slots available.")

    model_decision = _effective_model(parent_profile, request)
    if isinstance(model_decision, TemporarySubagentPolicyDecision):
        return model_decision
    tool_decision = _effective_tools(parent_profile, request)
    if isinstance(tool_decision, TemporarySubagentPolicyDecision):
        return tool_decision
    workspace_decision = _effective_workspace(parent_profile, request)
    if isinstance(workspace_decision, TemporarySubagentPolicyDecision):
        return workspace_decision
    budget_decision = _effective_budget(parent_profile, request, remaining_task_tokens)
    if isinstance(budget_decision, TemporarySubagentPolicyDecision):
        return budget_decision

    read_roots, write_roots = workspace_decision
    max_task_tokens, max_task_cost_usd, timeout_seconds = budget_decision
    policy = TemporarySubagentEffectivePolicy(
        runtime_type=request.requested_runtime_type,
        model_name=model_decision,
        allowed_tools=tool_decision,
        workspace_read_roots=read_roots,
        workspace_write_roots=write_roots,
        max_task_tokens=max_task_tokens,
        max_task_cost_usd=max_task_cost_usd,
        timeout_seconds=timeout_seconds,
        parent_worker_id=parent_profile.worker_id,
        task_id=request.task_id,
        delegation_id=request.delegation_id,
    )
    return TemporarySubagentPolicyDecision(
        allowed=True,
        reason_code="allowed",
        message="Temporary subagent request is within parent worker policy.",
        effective_policy=policy,
        audit_summary=(
            f"Temporary subagent {request.delegation_id} allowed for "
            f"parent worker {parent_profile.worker_id}."
        ),
    )


def temporary_subagent_effective_policy_to_dict(
    policy: TemporarySubagentEffectivePolicy,
) -> dict[str, object]:
    """Return a deterministic JSON-safe effective policy snapshot."""

    return {
        "runtime_type": policy.runtime_type.value,
        "model_name": policy.model_name,
        "allowed_tools": list(policy.allowed_tools),
        "workspace_read_roots": list(policy.workspace_read_roots),
        "workspace_write_roots": list(policy.workspace_write_roots),
        "max_task_tokens": policy.max_task_tokens,
        "max_task_cost_usd": policy.max_task_cost_usd,
        "timeout_seconds": policy.timeout_seconds,
        "parent_worker_id": policy.parent_worker_id,
        "task_id": policy.task_id,
        "delegation_id": policy.delegation_id,
    }


def temporary_subagent_policy_decision_to_dict(
    decision: TemporarySubagentPolicyDecision,
) -> dict[str, object]:
    """Return a JSON-safe policy decision for audit records."""

    return {
        "allowed": decision.allowed,
        "reason_code": decision.reason_code,
        "message": decision.message,
        "effective_policy": (
            temporary_subagent_effective_policy_to_dict(decision.effective_policy)
            if decision.effective_policy is not None
            else None
        ),
        "audit_summary": decision.audit_summary,
    }


def _validate_policy_inputs(
    parent_profile: WorkerAgentProfile,
    request: TemporarySubagentRequest,
    active_child_count: int,
) -> None:
    if not isinstance(parent_profile, WorkerAgentProfile):
        raise TemporarySubagentPolicyError(
            "parent_profile must be a WorkerAgentProfile"
        )
    if not isinstance(request, TemporarySubagentRequest):
        raise TemporarySubagentPolicyError(
            "request must be a TemporarySubagentRequest"
        )
    if isinstance(active_child_count, bool) or active_child_count < 0:
        raise TemporarySubagentPolicyError(
            "active_child_count must be a non-negative integer"
        )


def _effective_model(
    parent_profile: WorkerAgentProfile, request: TemporarySubagentRequest
) -> str | None | TemporarySubagentPolicyDecision:
    requested_model = request.requested_model or parent_profile.model.default_model
    allowed_by_worker = set(parent_profile.model.allowed_models)
    if parent_profile.model.default_model:
        allowed_by_worker.add(parent_profile.model.default_model)
    allowed_by_delegation = set(parent_profile.delegation.allowed_child_models)

    if requested_model is None:
        return None
    if allowed_by_worker and requested_model not in allowed_by_worker:
        return _deny("model_not_allowed", "Requested model is not allowed for the parent worker.")
    if allowed_by_delegation and requested_model not in allowed_by_delegation:
        return _deny("child_model_not_allowed", "Requested model is not allowed for temporary subagents.")
    return requested_model


def _effective_tools(
    parent_profile: WorkerAgentProfile, request: TemporarySubagentRequest
) -> tuple[str, ...] | TemporarySubagentPolicyDecision:
    parent_tools = set(parent_profile.tools.allowed_tools)
    child_tools = set(parent_profile.delegation.allowed_child_tools or parent_tools)
    requested_tools = set(request.requested_tools)
    if not requested_tools:
        return tuple(sorted(parent_tools & child_tools))
    if not requested_tools <= parent_tools:
        return _deny("tool_not_allowed", "Requested tools exceed the parent worker tool policy.")
    if not requested_tools <= child_tools:
        return _deny("child_tool_not_allowed", "Requested tools exceed the temporary subagent tool policy.")
    return tuple(tool for tool in request.requested_tools if tool in requested_tools)


def _effective_workspace(
    parent_profile: WorkerAgentProfile, request: TemporarySubagentRequest
) -> tuple[tuple[str, ...], tuple[str, ...]] | TemporarySubagentPolicyDecision:
    read_roots = request.workspace_read_roots or parent_profile.workspace.read_roots
    write_roots = request.workspace_write_roots
    if not _paths_within_roots(read_roots, parent_profile.workspace.read_roots):
        return _deny("read_workspace_out_of_bounds", "Requested read workspace exceeds parent worker policy.")
    if not _paths_within_roots(write_roots, parent_profile.workspace.write_roots):
        return _deny("write_workspace_out_of_bounds", "Requested write workspace exceeds parent worker policy.")
    return read_roots, write_roots


def _effective_budget(
    parent_profile: WorkerAgentProfile,
    request: TemporarySubagentRequest,
    remaining_task_tokens: int | None,
) -> tuple[int | None, float | None, int | None] | TemporarySubagentPolicyDecision:
    max_task_tokens = request.max_task_tokens
    child_token_limit = parent_profile.delegation.max_child_task_tokens or None
    parent_token_limit = parent_profile.budgets.max_task_tokens or None
    if max_task_tokens is not None:
        for limit, code, message in (
            (child_token_limit, "child_token_budget_exceeded", "Requested token budget exceeds temporary subagent policy."),
            (parent_token_limit, "parent_token_budget_exceeded", "Requested token budget exceeds parent worker policy."),
            (remaining_task_tokens, "remaining_token_budget_exceeded", "Requested token budget exceeds remaining task budget."),
        ):
            if limit is not None and max_task_tokens > limit:
                return _deny(code, message)

    max_task_cost_usd = request.max_task_cost_usd
    parent_cost_limit = parent_profile.budgets.max_task_cost_usd
    if (
        max_task_cost_usd is not None
        and parent_cost_limit is not None
        and max_task_cost_usd > parent_cost_limit
    ):
        return _deny("parent_cost_budget_exceeded", "Requested cost budget exceeds parent worker policy.")

    timeout_seconds = request.timeout_seconds
    parent_timeout = parent_profile.limits.timeout_seconds
    if (
        timeout_seconds is not None
        and parent_timeout is not None
        and timeout_seconds > parent_timeout
    ):
        return _deny("timeout_exceeded", "Requested timeout exceeds parent worker policy.")
    return max_task_tokens, max_task_cost_usd, timeout_seconds


def _paths_within_roots(paths: tuple[str, ...], roots: tuple[str, ...]) -> bool:
    if not paths:
        return True
    normalized_roots = tuple(_normalize_policy_path(root) for root in roots)
    if not normalized_roots:
        return False
    return all(
        any(_is_under_root(_normalize_policy_path(path), root) for root in normalized_roots)
        for path in paths
    )


def _normalize_policy_path(value: str) -> PurePosixPath:
    if value in {"*", "all"} or not value:
        raise TemporarySubagentPolicyError("workspace paths must be bounded")
    normalized = posixpath.normpath(value.replace("\\", "/"))
    if normalized in {".", ".."} or normalized.startswith("../") or "/../" in normalized:
        raise TemporarySubagentPolicyError("workspace paths must not escape their root")
    return PurePosixPath(normalized)


def _is_under_root(path: PurePosixPath, root: PurePosixPath) -> bool:
    return path == root or root in path.parents


def _deny(reason_code: str, message: str) -> TemporarySubagentPolicyDecision:
    return TemporarySubagentPolicyDecision(
        allowed=False,
        reason_code=reason_code,
        message=message,
        audit_summary=message,
    )

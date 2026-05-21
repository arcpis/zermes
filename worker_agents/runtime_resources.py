"""Runtime resource contracts shared by all managed worker adapters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .runtime_contract import RuntimeExecutionBudget


class RuntimeResourceError(ValueError):
    """Raised when runtime resource controls are invalid or exceeded."""


class RuntimeBudgetSource(StrEnum):
    """Policy layers that can narrow one runtime invocation budget."""

    WORKER_PROFILE = "worker_profile"
    ORGANIZATION_POLICY = "organization_policy"
    TASK_REQUEST = "task_request"
    PARENT_RUNTIME = "parent_runtime"
    ADAPTER_DEFINITION = "adapter_definition"
    DEFAULT_LIMITS = "default_limits"


class RuntimeBudgetViolationKind(StrEnum):
    """Budget limits that can be exceeded by runtime usage."""

    INPUT_TOKENS = "input_tokens"
    OUTPUT_TOKENS = "output_tokens"
    TOTAL_TOKENS = "total_tokens"
    COST = "cost"
    WALL_TIME = "wall_time"
    OUTPUT_BYTES = "output_bytes"
    TRANSCRIPT_BYTES = "transcript_bytes"
    RETRY_ATTEMPTS = "retry_attempts"
    CONCURRENT_CHILDREN = "concurrent_children"


@dataclass(frozen=True)
class RuntimeBudgetPolicy:
    """One policy layer that may narrow runtime resource limits."""

    source: RuntimeBudgetSource | str
    source_ref: str
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    max_total_tokens: int | None = None
    max_cost_units: float | None = None
    max_wall_time_seconds: int | None = None
    max_output_bytes: int | None = None
    max_transcript_bytes: int | None = None
    max_retry_attempts: int | None = None
    max_concurrent_children: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", _coerce_budget_source(self.source))
        _require_string(self.source_ref, "source_ref")
        for field_name in (
            "max_input_tokens",
            "max_output_tokens",
            "max_total_tokens",
            "max_wall_time_seconds",
            "max_output_bytes",
            "max_transcript_bytes",
        ):
            _optional_positive_int(getattr(self, field_name), field_name)
        for field_name in ("max_retry_attempts", "max_concurrent_children"):
            _optional_non_negative_int(getattr(self, field_name), field_name)
        _optional_non_negative_float(self.max_cost_units, "max_cost_units")
        if not _has_any_limit(self):
            raise RuntimeResourceError("runtime budget policy requires at least one limit")


@dataclass(frozen=True)
class RuntimeBudgetSnapshot:
    """Resolved immutable resource limits for one runtime invocation."""

    source_refs: tuple[str, ...]
    max_input_tokens: int
    max_output_tokens: int
    max_total_tokens: int
    max_cost_units: float
    max_wall_time_seconds: int
    max_output_bytes: int
    max_transcript_bytes: int
    max_retry_attempts: int
    max_concurrent_children: int

    def __post_init__(self) -> None:
        if not isinstance(self.source_refs, tuple) or not self.source_refs:
            raise RuntimeResourceError("source_refs must be a non-empty tuple")
        if any(not isinstance(value, str) or not value for value in self.source_refs):
            raise RuntimeResourceError("source_refs must contain non-empty strings")
        for field_name in (
            "max_input_tokens",
            "max_output_tokens",
            "max_total_tokens",
            "max_wall_time_seconds",
            "max_output_bytes",
            "max_transcript_bytes",
        ):
            _positive_int(getattr(self, field_name), field_name)
        for field_name in ("max_retry_attempts", "max_concurrent_children"):
            _non_negative_int(getattr(self, field_name), field_name)
        _non_negative_float(self.max_cost_units, "max_cost_units")
        if self.max_total_tokens < self.max_input_tokens:
            raise RuntimeResourceError("max_total_tokens must cover max_input_tokens")
        if self.max_total_tokens < self.max_output_tokens:
            raise RuntimeResourceError("max_total_tokens must cover max_output_tokens")


@dataclass(frozen=True)
class RuntimeResourceUsage:
    """Low-sensitive resource usage for one runtime invocation."""

    input_tokens: int = 0
    output_tokens: int = 0
    cost_units: float = 0.0
    wall_time_seconds: int = 0
    output_bytes: int = 0
    transcript_bytes: int = 0
    retry_attempts: int = 0
    concurrent_children: int = 0

    def __post_init__(self) -> None:
        for field_name in (
            "input_tokens",
            "output_tokens",
            "wall_time_seconds",
            "output_bytes",
            "transcript_bytes",
            "retry_attempts",
            "concurrent_children",
        ):
            _non_negative_int(getattr(self, field_name), field_name)
        _non_negative_float(self.cost_units, "cost_units")

    @property
    def total_tokens(self) -> int:
        """Return input plus output tokens for budget comparisons."""

        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class RuntimeBudgetViolation:
    """Audit-safe detail for a single exceeded runtime budget limit."""

    kind: RuntimeBudgetViolationKind | str
    used: float
    limit: float
    source_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _coerce_violation_kind(self.kind))
        _non_negative_float(self.used, "used")
        _non_negative_float(self.limit, "limit")
        if not isinstance(self.source_refs, tuple) or not self.source_refs:
            raise RuntimeResourceError("source_refs must be a non-empty tuple")


def runtime_budget_policy_from_execution_budget(
    budget: RuntimeExecutionBudget,
    *,
    source: RuntimeBudgetSource | str = RuntimeBudgetSource.WORKER_PROFILE,
) -> RuntimeBudgetPolicy:
    """Convert the existing runtime request budget into a resource policy layer."""

    if not isinstance(budget, RuntimeExecutionBudget):
        raise RuntimeResourceError("budget must be a RuntimeExecutionBudget")
    total_tokens = _sum_optional_ints(budget.max_input_tokens, budget.max_output_tokens)
    return RuntimeBudgetPolicy(
        source=source,
        source_ref=budget.budget_source,
        max_input_tokens=budget.max_input_tokens,
        max_output_tokens=budget.max_output_tokens,
        max_total_tokens=total_tokens,
        max_cost_units=budget.max_cost_usd,
        max_wall_time_seconds=budget.timeout_seconds,
        max_output_bytes=budget.max_output_bytes,
        max_transcript_bytes=budget.max_transcript_bytes,
    )


def resolve_runtime_budget(
    policies: tuple[RuntimeBudgetPolicy, ...],
    *,
    defaults: RuntimeBudgetPolicy,
) -> RuntimeBudgetSnapshot:
    """Resolve effective runtime limits by applying the strictest policy values."""

    if not isinstance(defaults, RuntimeBudgetPolicy):
        raise RuntimeResourceError("defaults must be a RuntimeBudgetPolicy")
    all_policies = (defaults,) + tuple(policies)
    if any(not isinstance(policy, RuntimeBudgetPolicy) for policy in all_policies):
        raise RuntimeResourceError("policies must contain RuntimeBudgetPolicy records")
    source_refs = tuple(policy.source_ref for policy in all_policies)
    return RuntimeBudgetSnapshot(
        source_refs=source_refs,
        max_input_tokens=_strictest_required_limit(all_policies, "max_input_tokens"),
        max_output_tokens=_strictest_required_limit(all_policies, "max_output_tokens"),
        max_total_tokens=_strictest_required_limit(all_policies, "max_total_tokens"),
        max_cost_units=float(_strictest_required_limit(all_policies, "max_cost_units")),
        max_wall_time_seconds=_strictest_required_limit(
            all_policies, "max_wall_time_seconds"
        ),
        max_output_bytes=_strictest_required_limit(all_policies, "max_output_bytes"),
        max_transcript_bytes=_strictest_required_limit(
            all_policies, "max_transcript_bytes"
        ),
        max_retry_attempts=_strictest_required_limit(
            all_policies, "max_retry_attempts"
        ),
        max_concurrent_children=_strictest_required_limit(
            all_policies, "max_concurrent_children"
        ),
    )


def validate_runtime_usage(
    usage: RuntimeResourceUsage, budget: RuntimeBudgetSnapshot
) -> tuple[RuntimeBudgetViolation, ...]:
    """Return all exceeded budget limits without exposing runtime content."""

    if not isinstance(usage, RuntimeResourceUsage):
        raise RuntimeResourceError("usage must be a RuntimeResourceUsage")
    if not isinstance(budget, RuntimeBudgetSnapshot):
        raise RuntimeResourceError("budget must be a RuntimeBudgetSnapshot")
    checks = (
        (RuntimeBudgetViolationKind.INPUT_TOKENS, usage.input_tokens, budget.max_input_tokens),
        (RuntimeBudgetViolationKind.OUTPUT_TOKENS, usage.output_tokens, budget.max_output_tokens),
        (RuntimeBudgetViolationKind.TOTAL_TOKENS, usage.total_tokens, budget.max_total_tokens),
        (RuntimeBudgetViolationKind.COST, usage.cost_units, budget.max_cost_units),
        (RuntimeBudgetViolationKind.WALL_TIME, usage.wall_time_seconds, budget.max_wall_time_seconds),
        (RuntimeBudgetViolationKind.OUTPUT_BYTES, usage.output_bytes, budget.max_output_bytes),
        (RuntimeBudgetViolationKind.TRANSCRIPT_BYTES, usage.transcript_bytes, budget.max_transcript_bytes),
        (RuntimeBudgetViolationKind.RETRY_ATTEMPTS, usage.retry_attempts, budget.max_retry_attempts),
        (RuntimeBudgetViolationKind.CONCURRENT_CHILDREN, usage.concurrent_children, budget.max_concurrent_children),
    )
    return tuple(
        RuntimeBudgetViolation(kind=kind, used=used, limit=limit, source_refs=budget.source_refs)
        for kind, used, limit in checks
        if used > limit
    )


def runtime_resource_usage_to_audit_summary(
    usage: RuntimeResourceUsage,
) -> dict[str, int | float]:
    """Return JSON-safe counters only; never include prompts or transcripts."""

    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
        "cost_units": usage.cost_units,
        "wall_time_seconds": usage.wall_time_seconds,
        "output_bytes": usage.output_bytes,
        "transcript_bytes": usage.transcript_bytes,
        "retry_attempts": usage.retry_attempts,
        "concurrent_children": usage.concurrent_children,
    }


def runtime_budget_snapshot_to_dict(
    budget: RuntimeBudgetSnapshot,
) -> dict[str, object]:
    """Return a deterministic JSON-safe effective budget snapshot."""

    return {
        "source_refs": list(budget.source_refs),
        "max_input_tokens": budget.max_input_tokens,
        "max_output_tokens": budget.max_output_tokens,
        "max_total_tokens": budget.max_total_tokens,
        "max_cost_units": budget.max_cost_units,
        "max_wall_time_seconds": budget.max_wall_time_seconds,
        "max_output_bytes": budget.max_output_bytes,
        "max_transcript_bytes": budget.max_transcript_bytes,
        "max_retry_attempts": budget.max_retry_attempts,
        "max_concurrent_children": budget.max_concurrent_children,
    }


def runtime_budget_violation_to_dict(
    violation: RuntimeBudgetViolation,
) -> dict[str, object]:
    """Return a JSON-safe budget violation record."""

    return {
        "kind": violation.kind.value,
        "used": violation.used,
        "limit": violation.limit,
        "source_refs": list(violation.source_refs),
    }


def _coerce_budget_source(value: RuntimeBudgetSource | str) -> RuntimeBudgetSource:
    try:
        return RuntimeBudgetSource(value)
    except ValueError as exc:
        raise RuntimeResourceError(f"Unknown runtime budget source: {value!r}") from exc


def _coerce_violation_kind(
    value: RuntimeBudgetViolationKind | str,
) -> RuntimeBudgetViolationKind:
    try:
        return RuntimeBudgetViolationKind(value)
    except ValueError as exc:
        raise RuntimeResourceError(f"Unknown runtime budget violation: {value!r}") from exc


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeResourceError(f"{field_name} must be a non-empty string")
    return value


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RuntimeResourceError(f"{field_name} must be a positive integer")
    return value


def _non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimeResourceError(f"{field_name} must be a non-negative integer")
    return value


def _optional_positive_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, field_name)


def _optional_non_negative_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    return _non_negative_int(value, field_name)


def _non_negative_float(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise RuntimeResourceError(f"{field_name} must be a non-negative number")
    return float(value)


def _optional_non_negative_float(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    return _non_negative_float(value, field_name)


def _has_any_limit(policy: RuntimeBudgetPolicy) -> bool:
    return any(
        getattr(policy, field_name) is not None
        for field_name in (
            "max_input_tokens",
            "max_output_tokens",
            "max_total_tokens",
            "max_cost_units",
            "max_wall_time_seconds",
            "max_output_bytes",
            "max_transcript_bytes",
            "max_retry_attempts",
            "max_concurrent_children",
        )
    )


def _strictest_required_limit(
    policies: tuple[RuntimeBudgetPolicy, ...], field_name: str
) -> int | float:
    values = tuple(
        getattr(policy, field_name)
        for policy in policies
        if getattr(policy, field_name) is not None
    )
    if not values:
        raise RuntimeResourceError(f"{field_name} requires an effective limit")
    return min(values)


def _sum_optional_ints(left: int | None, right: int | None) -> int | None:
    if left is None or right is None:
        return None
    return left + right

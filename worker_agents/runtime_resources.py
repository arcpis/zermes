"""Runtime resource contracts shared by all managed worker adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from .runtime_contract import (
    RuntimeErrorCode,
    RuntimeErrorInfo,
    RuntimeEvent,
    RuntimeEventType,
    RuntimeExecutionBudget,
    RuntimeRequest,
    RuntimeState,
    utc_timestamp,
)
from .storage import WorkerAgentRuntimeDataStore


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


class RuntimeCancellationReason(StrEnum):
    """Reasons a managed runtime invocation may be stopped."""

    USER_REQUESTED = "user_requested"
    PARENT_RUNTIME_REQUESTED = "parent_runtime_requested"
    TIMEOUT = "timeout"
    BUDGET_EXHAUSTED = "budget_exhausted"
    SYSTEM_SHUTDOWN = "system_shutdown"
    SAFETY_STOP = "safety_stop"


class RuntimeConcurrencyDimension(StrEnum):
    """Dimensions that can independently limit runtime concurrency."""

    USER = "user"
    ORGANIZATION_NODE = "organization_node"
    WORKER = "worker"
    ADAPTER = "adapter"
    RUNTIME_TYPE = "runtime_type"
    PARENT_RUNTIME_SESSION = "parent_runtime_session"


class RuntimeConcurrencyDecisionKind(StrEnum):
    """Outcomes from attempting to acquire a runtime concurrency slot."""

    ALLOWED = "allowed"
    REJECTED = "rejected"
    QUEUED = "queued"
    NEEDS_APPROVAL = "needs_approval"


class RuntimeTranscriptKind(StrEnum):
    """Runtime transcript streams that stay in clearable task data."""

    RAW_LOG = "raw_log"
    TOOL_LOG = "tool_log"
    EXTERNAL_OUTPUT = "external_output"
    COMPACT_SUMMARY = "compact_summary"


class RuntimeTranscriptRetentionClass(StrEnum):
    """Retention class labels consumed by later cleanup policy."""

    EPHEMERAL = "ephemeral"
    TASK_AUDIT = "task_audit"


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


@dataclass(frozen=True)
class RuntimeCancellationRequest:
    """Audit-safe cancellation request for one runtime invocation."""

    reason: RuntimeCancellationReason | str
    requested_by: str
    requested_at: str
    safe_summary: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason", _coerce_cancellation_reason(self.reason))
        _require_string(self.requested_by, "requested_by")
        _require_string(self.requested_at, "requested_at")
        _require_string(self.safe_summary, "safe_summary")


@dataclass(frozen=True)
class RuntimeCancellationToken:
    """Immutable cancellation token; cancelling returns a new token."""

    request: RuntimeCancellationRequest | None = None
    audit_notes: tuple[str, ...] = ()

    @property
    def cancelled(self) -> bool:
        """Return whether cancellation has been requested."""

        return self.request is not None

    def cancel(
        self,
        reason: RuntimeCancellationReason | str,
        *,
        requested_by: str,
        safe_summary: str,
        requested_at: str | None = None,
    ) -> "RuntimeCancellationToken":
        """Return a token with the first cancellation reason preserved."""

        request = RuntimeCancellationRequest(
            reason=reason,
            requested_by=requested_by,
            requested_at=requested_at or utc_timestamp(),
            safe_summary=safe_summary,
        )
        if self.request is not None:
            return RuntimeCancellationToken(
                request=self.request,
                audit_notes=self.audit_notes + (request.safe_summary,),
            )
        return RuntimeCancellationToken(request=request, audit_notes=self.audit_notes)


@dataclass(frozen=True)
class RuntimeConcurrencyKey:
    """One counted concurrency bucket for a runtime invocation."""

    dimension: RuntimeConcurrencyDimension | str
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "dimension", _coerce_concurrency_dimension(self.dimension)
        )
        _require_string(self.value, "value")


@dataclass(frozen=True)
class RuntimeConcurrencyLimit:
    """Maximum active invocations for one concurrency bucket."""

    key: RuntimeConcurrencyKey
    max_active: int
    decision_kind: RuntimeConcurrencyDecisionKind | str = (
        RuntimeConcurrencyDecisionKind.REJECTED
    )

    def __post_init__(self) -> None:
        if not isinstance(self.key, RuntimeConcurrencyKey):
            raise RuntimeResourceError("key must be a RuntimeConcurrencyKey")
        _positive_int(self.max_active, "max_active")
        object.__setattr__(
            self,
            "decision_kind",
            _coerce_concurrency_decision_kind(self.decision_kind),
        )


@dataclass(frozen=True)
class RuntimeConcurrencyRequest:
    """Runtime identity fields used to compute concurrency buckets."""

    request_id: str
    worker_id: str
    runtime_type: str
    user_id: str | None = None
    organization_node_id: str | None = None
    adapter_id: str | None = None
    parent_runtime_session_id: str | None = None

    def __post_init__(self) -> None:
        _require_string(self.request_id, "request_id")
        _require_string(self.worker_id, "worker_id")
        _require_string(self.runtime_type, "runtime_type")
        for field_name in (
            "user_id",
            "organization_node_id",
            "adapter_id",
            "parent_runtime_session_id",
        ):
            value = getattr(self, field_name)
            if value is not None:
                _require_string(value, field_name)

    def keys(self) -> tuple[RuntimeConcurrencyKey, ...]:
        """Return the concurrency buckets occupied by this request."""

        pairs = (
            (RuntimeConcurrencyDimension.USER, self.user_id),
            (RuntimeConcurrencyDimension.ORGANIZATION_NODE, self.organization_node_id),
            (RuntimeConcurrencyDimension.WORKER, self.worker_id),
            (RuntimeConcurrencyDimension.ADAPTER, self.adapter_id),
            (RuntimeConcurrencyDimension.RUNTIME_TYPE, self.runtime_type),
            (
                RuntimeConcurrencyDimension.PARENT_RUNTIME_SESSION,
                self.parent_runtime_session_id,
            ),
        )
        return tuple(
            RuntimeConcurrencyKey(dimension=dimension, value=value)
            for dimension, value in pairs
            if value is not None
        )


@dataclass(frozen=True)
class RuntimeConcurrencyLease:
    """A running invocation's acquired concurrency slots."""

    lease_id: str
    request_id: str
    keys: tuple[RuntimeConcurrencyKey, ...]

    def __post_init__(self) -> None:
        _require_string(self.lease_id, "lease_id")
        _require_string(self.request_id, "request_id")
        if not isinstance(self.keys, tuple) or not self.keys:
            raise RuntimeResourceError("keys must be a non-empty tuple")
        if any(not isinstance(key, RuntimeConcurrencyKey) for key in self.keys):
            raise RuntimeResourceError("keys must contain RuntimeConcurrencyKey records")


@dataclass(frozen=True)
class RuntimeConcurrencyDecision:
    """Allow, reject, queue, or escalate one concurrency acquisition."""

    kind: RuntimeConcurrencyDecisionKind | str
    reason_code: str
    safe_summary: str
    lease: RuntimeConcurrencyLease | None = None
    retry_after_seconds: int | None = None
    limit_key: RuntimeConcurrencyKey | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "kind", _coerce_concurrency_decision_kind(self.kind)
        )
        _require_string(self.reason_code, "reason_code")
        _require_string(self.safe_summary, "safe_summary")
        if self.lease is not None and not isinstance(
            self.lease, RuntimeConcurrencyLease
        ):
            raise RuntimeResourceError("lease must be a RuntimeConcurrencyLease")
        _optional_positive_int(self.retry_after_seconds, "retry_after_seconds")
        if self.limit_key is not None and not isinstance(
            self.limit_key, RuntimeConcurrencyKey
        ):
            raise RuntimeResourceError("limit_key must be a RuntimeConcurrencyKey")


@dataclass
class RuntimeConcurrencyGate:
    """Local in-process gate for early runtime concurrency enforcement."""

    active_leases: dict[str, RuntimeConcurrencyLease] = field(default_factory=dict)

    def try_acquire(
        self,
        request: RuntimeConcurrencyRequest,
        limits: tuple[RuntimeConcurrencyLimit, ...],
    ) -> RuntimeConcurrencyDecision:
        """Acquire a local concurrency lease or return a safe denial."""

        if not isinstance(request, RuntimeConcurrencyRequest):
            raise RuntimeResourceError("request must be a RuntimeConcurrencyRequest")
        if any(not isinstance(limit, RuntimeConcurrencyLimit) for limit in limits):
            raise RuntimeResourceError(
                "limits must contain RuntimeConcurrencyLimit records"
            )
        keys = request.keys()
        for limit in limits:
            if limit.key not in keys:
                continue
            active_count = self.snapshot().get(limit.key, 0)
            if active_count >= limit.max_active:
                return RuntimeConcurrencyDecision(
                    kind=limit.decision_kind,
                    reason_code="concurrency_limit",
                    safe_summary=(
                        f"Runtime concurrency limit reached for "
                        f"{limit.key.dimension.value}:{limit.key.value}."
                    ),
                    retry_after_seconds=30
                    if limit.decision_kind == RuntimeConcurrencyDecisionKind.QUEUED
                    else None,
                    limit_key=limit.key,
                )
        lease = RuntimeConcurrencyLease(
            lease_id=f"lease-{request.request_id}",
            request_id=request.request_id,
            keys=keys,
        )
        self.active_leases[lease.lease_id] = lease
        return RuntimeConcurrencyDecision(
            kind=RuntimeConcurrencyDecisionKind.ALLOWED,
            reason_code="allowed",
            safe_summary="Runtime concurrency slot acquired.",
            lease=lease,
        )

    def release(self, lease: RuntimeConcurrencyLease | str) -> bool:
        """Release a lease idempotently; return true when it existed."""

        lease_id = lease.lease_id if isinstance(lease, RuntimeConcurrencyLease) else lease
        _require_string(lease_id, "lease_id")
        return self.active_leases.pop(lease_id, None) is not None

    def snapshot(self) -> dict[RuntimeConcurrencyKey, int]:
        """Return active counts by concurrency bucket."""

        counts: dict[RuntimeConcurrencyKey, int] = {}
        for lease in self.active_leases.values():
            for key in lease.keys:
                counts[key] = counts.get(key, 0) + 1
        return counts


@dataclass(frozen=True)
class RuntimeTranscriptPolicy:
    """Limits and redaction requirements for runtime transcript storage."""

    allow_raw_transcript: bool = True
    max_raw_bytes: int = 64_000
    max_summary_bytes: int = 8_000
    retention_class: RuntimeTranscriptRetentionClass | str = (
        RuntimeTranscriptRetentionClass.EPHEMERAL
    )
    redaction_required: bool = True

    def __post_init__(self) -> None:
        _positive_int(self.max_raw_bytes, "max_raw_bytes")
        _positive_int(self.max_summary_bytes, "max_summary_bytes")
        object.__setattr__(
            self,
            "retention_class",
            _coerce_transcript_retention_class(self.retention_class),
        )
        if not isinstance(self.allow_raw_transcript, bool):
            raise RuntimeResourceError("allow_raw_transcript must be a boolean")
        if not isinstance(self.redaction_required, bool):
            raise RuntimeResourceError("redaction_required must be a boolean")


@dataclass(frozen=True)
class RuntimeTranscriptRef:
    """Reference to runtime transcript data stored in clearable task storage."""

    ref_id: str
    task_id: str
    runtime_session_id: str
    kind: RuntimeTranscriptKind | str
    storage_scope: str
    relative_path: str
    byte_count: int
    redaction_status: str

    def __post_init__(self) -> None:
        _require_string(self.ref_id, "ref_id")
        _require_string(self.task_id, "task_id")
        _require_string(self.runtime_session_id, "runtime_session_id")
        object.__setattr__(self, "kind", _coerce_transcript_kind(self.kind))
        _require_string(self.storage_scope, "storage_scope")
        if self.storage_scope != "runtime_data":
            raise RuntimeResourceError("transcript refs must use runtime_data scope")
        _require_string(self.relative_path, "relative_path")
        _non_negative_int(self.byte_count, "byte_count")
        _require_string(self.redaction_status, "redaction_status")


@dataclass(frozen=True)
class RuntimeTranscriptAuditSummary:
    """Low-sensitive transcript summary suitable for task events."""

    task_id: str
    runtime_session_id: str
    refs: tuple[RuntimeTranscriptRef, ...]
    total_bytes: int
    redaction_status: str
    safe_summary: str
    omitted_reason: str | None = None

    def __post_init__(self) -> None:
        _require_string(self.task_id, "task_id")
        _require_string(self.runtime_session_id, "runtime_session_id")
        if not isinstance(self.refs, tuple):
            raise RuntimeResourceError("refs must be a tuple")
        if any(not isinstance(ref, RuntimeTranscriptRef) for ref in self.refs):
            raise RuntimeResourceError("refs must contain RuntimeTranscriptRef records")
        _non_negative_int(self.total_bytes, "total_bytes")
        _require_string(self.redaction_status, "redaction_status")
        _require_string(self.safe_summary, "safe_summary")
        if self.omitted_reason is not None:
            _require_string(self.omitted_reason, "omitted_reason")


@dataclass(frozen=True)
class RuntimeTranscriptSink:
    """Write runtime transcript data only under clearable task storage."""

    runtime_store: WorkerAgentRuntimeDataStore
    task_id: str
    runtime_session_id: str
    policy: RuntimeTranscriptPolicy = field(default_factory=RuntimeTranscriptPolicy)

    def __post_init__(self) -> None:
        if not isinstance(self.runtime_store, WorkerAgentRuntimeDataStore):
            raise RuntimeResourceError(
                "runtime_store must be a WorkerAgentRuntimeDataStore"
            )
        _require_string(self.task_id, "task_id")
        _require_string(self.runtime_session_id, "runtime_session_id")
        if not isinstance(self.policy, RuntimeTranscriptPolicy):
            raise RuntimeResourceError("policy must be a RuntimeTranscriptPolicy")

    def write(
        self,
        kind: RuntimeTranscriptKind | str,
        text: str,
        *,
        file_name: str | None = None,
    ) -> RuntimeTranscriptRef:
        """Persist transcript text under the task runtime directory and return a ref."""

        transcript_kind = _coerce_transcript_kind(kind)
        _require_string(text, "text")
        if transcript_kind != RuntimeTranscriptKind.COMPACT_SUMMARY:
            if not self.policy.allow_raw_transcript:
                raise RuntimeResourceError("raw runtime transcript is disabled")
            byte_limit = self.policy.max_raw_bytes
        else:
            byte_limit = self.policy.max_summary_bytes
        sanitized = sanitize_runtime_text(text)
        encoded = sanitized.encode("utf-8")
        if len(encoded) > byte_limit:
            raise RuntimeResourceError("runtime transcript exceeds byte limit")
        safe_file_name = file_name or f"{transcript_kind.value}.txt"
        _reject_unsafe_transcript_file_name(safe_file_name)
        relative_path = Path("transcripts") / self.runtime_session_id / safe_file_name
        path = self.runtime_store.task_runtime_path(self.task_id, relative_path)
        _ensure_runtime_data_path(path, self.runtime_store.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(sanitized, encoding="utf-8")
        return RuntimeTranscriptRef(
            ref_id=f"{self.task_id}:{self.runtime_session_id}:{transcript_kind.value}",
            task_id=self.task_id,
            runtime_session_id=self.runtime_session_id,
            kind=transcript_kind,
            storage_scope="runtime_data",
            relative_path=str(path.relative_to(self.runtime_store.root)),
            byte_count=len(encoded),
            redaction_status="redacted" if self.policy.redaction_required else "raw",
        )

    def audit_summary(
        self, refs: tuple[RuntimeTranscriptRef, ...], *, safe_summary: str
    ) -> RuntimeTranscriptAuditSummary:
        """Build a low-sensitive audit summary from transcript references."""

        return RuntimeTranscriptAuditSummary(
            task_id=self.task_id,
            runtime_session_id=self.runtime_session_id,
            refs=refs,
            total_bytes=sum(ref.byte_count for ref in refs),
            redaction_status="redacted" if self.policy.redaction_required else "raw",
            safe_summary=sanitize_runtime_text(safe_summary),
            omitted_reason="raw transcript remains in runtime_data",
        )


@dataclass(frozen=True)
class RuntimeDeadline:
    """Monotonic-time deadline derived from an effective wall-time budget."""

    started_at_seconds: float
    timeout_seconds: int
    now: Callable[[], float]

    def __post_init__(self) -> None:
        _non_negative_float(self.started_at_seconds, "started_at_seconds")
        _positive_int(self.timeout_seconds, "timeout_seconds")
        if not callable(self.now):
            raise RuntimeResourceError("now must be callable")

    @property
    def expires_at_seconds(self) -> float:
        """Return the monotonic timestamp at which the runtime times out."""

        return self.started_at_seconds + self.timeout_seconds

    def expired(self) -> bool:
        """Return whether the current monotonic clock has passed the deadline."""

        return self.now() >= self.expires_at_seconds

    def elapsed_seconds(self) -> int:
        """Return elapsed whole seconds for audit and usage accounting."""

        return max(0, int(self.now() - self.started_at_seconds))


@dataclass(frozen=True)
class RuntimeControlScope:
    """Outer resource-control state for one runtime invocation."""

    budget: RuntimeBudgetSnapshot
    cancellation_token: RuntimeCancellationToken
    usage: RuntimeResourceUsage = field(default_factory=RuntimeResourceUsage)
    deadline: RuntimeDeadline | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.budget, RuntimeBudgetSnapshot):
            raise RuntimeResourceError("budget must be a RuntimeBudgetSnapshot")
        if not isinstance(self.cancellation_token, RuntimeCancellationToken):
            raise RuntimeResourceError(
                "cancellation_token must be a RuntimeCancellationToken"
            )
        if not isinstance(self.usage, RuntimeResourceUsage):
            raise RuntimeResourceError("usage must be a RuntimeResourceUsage")
        if self.deadline is not None and not isinstance(self.deadline, RuntimeDeadline):
            raise RuntimeResourceError("deadline must be a RuntimeDeadline")

    def with_usage_delta(self, delta: RuntimeResourceUsage) -> "RuntimeControlScope":
        """Return a new scope with cumulative resource usage."""

        if not isinstance(delta, RuntimeResourceUsage):
            raise RuntimeResourceError("delta must be a RuntimeResourceUsage")
        return RuntimeControlScope(
            budget=self.budget,
            cancellation_token=self.cancellation_token,
            usage=RuntimeResourceUsage(
                input_tokens=self.usage.input_tokens + delta.input_tokens,
                output_tokens=self.usage.output_tokens + delta.output_tokens,
                cost_units=self.usage.cost_units + delta.cost_units,
                wall_time_seconds=self.usage.wall_time_seconds + delta.wall_time_seconds,
                output_bytes=self.usage.output_bytes + delta.output_bytes,
                transcript_bytes=self.usage.transcript_bytes + delta.transcript_bytes,
                retry_attempts=self.usage.retry_attempts + delta.retry_attempts,
                concurrent_children=(
                    self.usage.concurrent_children + delta.concurrent_children
                ),
            ),
            deadline=self.deadline,
        )

    def with_cancellation(
        self,
        reason: RuntimeCancellationReason | str,
        *,
        requested_by: str,
        safe_summary: str,
        requested_at: str | None = None,
    ) -> "RuntimeControlScope":
        """Return a new scope after requesting cancellation."""

        return RuntimeControlScope(
            budget=self.budget,
            cancellation_token=self.cancellation_token.cancel(
                reason,
                requested_by=requested_by,
                safe_summary=safe_summary,
                requested_at=requested_at,
            ),
            usage=self.usage,
            deadline=self.deadline,
        )

    def check_deadline(self) -> "RuntimeControlScope":
        """Return a timeout-cancelled scope when the deadline has expired."""

        if self.deadline is None or not self.deadline.expired():
            return self
        return self.with_cancellation(
            RuntimeCancellationReason.TIMEOUT,
            requested_by="runtime_deadline",
            safe_summary="Runtime deadline expired.",
        )

    def check_budget(self) -> "RuntimeControlScope":
        """Return a budget-cancelled scope when current usage exceeds limits."""

        violations = validate_runtime_usage(self.usage, self.budget)
        if not violations:
            return self
        return self.with_cancellation(
            RuntimeCancellationReason.BUDGET_EXHAUSTED,
            requested_by="runtime_budget",
            safe_summary=f"Runtime budget exceeded: {violations[0].kind.value}.",
        )


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


def runtime_cancellation_error(
    cancellation: RuntimeCancellationRequest,
) -> RuntimeErrorInfo:
    """Convert a cancellation request into a low-sensitive runtime error."""

    if not isinstance(cancellation, RuntimeCancellationRequest):
        raise RuntimeResourceError(
            "cancellation must be a RuntimeCancellationRequest"
        )
    if cancellation.reason == RuntimeCancellationReason.TIMEOUT:
        code = RuntimeErrorCode.TIMED_OUT
    elif cancellation.reason == RuntimeCancellationReason.BUDGET_EXHAUSTED:
        code = RuntimeErrorCode.BUDGET_EXCEEDED
    else:
        code = RuntimeErrorCode.CANCELLED
    return RuntimeErrorInfo(
        code=code,
        message=cancellation.reason.value,
        safe_summary=cancellation.safe_summary,
        retryable=False,
        source=cancellation.requested_by,
        created_at=cancellation.requested_at,
    )


def runtime_cancellation_event(
    request: RuntimeRequest,
    cancellation: RuntimeCancellationRequest,
    *,
    sequence: int,
) -> RuntimeEvent:
    """Create the standard low-sensitive cancellation runtime event."""

    if not isinstance(request, RuntimeRequest):
        raise RuntimeResourceError("request must be a RuntimeRequest")
    if not isinstance(cancellation, RuntimeCancellationRequest):
        raise RuntimeResourceError(
            "cancellation must be a RuntimeCancellationRequest"
        )
    state = (
        RuntimeState.TIMED_OUT
        if cancellation.reason == RuntimeCancellationReason.TIMEOUT
        else RuntimeState.CANCELLED
    )
    event_type = (
        RuntimeEventType.ERROR
        if cancellation.reason
        in {
            RuntimeCancellationReason.TIMEOUT,
            RuntimeCancellationReason.BUDGET_EXHAUSTED,
        }
        else RuntimeEventType.CANCELLED
    )
    return RuntimeEvent(
        event_id=f"{request.request_id}-cancel-{sequence}",
        request_id=request.request_id,
        task_id=request.task_id,
        worker_id=request.worker_id,
        runtime_type=request.runtime_type,
        state=state,
        event_type=event_type,
        created_at=cancellation.requested_at,
        sequence=sequence,
        payload=runtime_cancellation_request_to_dict(cancellation),
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


def runtime_cancellation_request_to_dict(
    cancellation: RuntimeCancellationRequest,
) -> dict[str, str]:
    """Return a JSON-safe cancellation request."""

    return {
        "reason": cancellation.reason.value,
        "requested_by": cancellation.requested_by,
        "requested_at": cancellation.requested_at,
        "safe_summary": cancellation.safe_summary,
    }


def runtime_concurrency_decision_to_dict(
    decision: RuntimeConcurrencyDecision,
) -> dict[str, object]:
    """Return a JSON-safe concurrency decision."""

    return {
        "kind": decision.kind.value,
        "reason_code": decision.reason_code,
        "safe_summary": decision.safe_summary,
        "lease_id": decision.lease.lease_id if decision.lease else None,
        "retry_after_seconds": decision.retry_after_seconds,
        "limit_key": (
            runtime_concurrency_key_to_dict(decision.limit_key)
            if decision.limit_key
            else None
        ),
    }


def runtime_concurrency_key_to_dict(
    key: RuntimeConcurrencyKey,
) -> dict[str, str]:
    """Return a JSON-safe concurrency bucket key."""

    return {"dimension": key.dimension.value, "value": key.value}


def sanitize_runtime_text(text: str) -> str:
    """Reject unsafe labels and redact simple secret-looking assignments."""

    _require_string(text, "text")
    lowered = text.lower()
    for label in _SENSITIVE_TRANSCRIPT_LABELS:
        if label in lowered:
            raise RuntimeResourceError(
                f"runtime transcript includes sensitive label: {label}"
            )
    sanitized_lines: list[str] = []
    for line in text.splitlines():
        sanitized_lines.append(_sanitize_secret_assignment(line))
    return "\n".join(sanitized_lines)


def runtime_transcript_ref_to_dict(ref: RuntimeTranscriptRef) -> dict[str, object]:
    """Return a JSON-safe transcript reference."""

    return {
        "ref_id": ref.ref_id,
        "task_id": ref.task_id,
        "runtime_session_id": ref.runtime_session_id,
        "kind": ref.kind.value,
        "storage_scope": ref.storage_scope,
        "relative_path": ref.relative_path,
        "byte_count": ref.byte_count,
        "redaction_status": ref.redaction_status,
    }


def runtime_transcript_audit_summary_to_dict(
    summary: RuntimeTranscriptAuditSummary,
) -> dict[str, object]:
    """Return a JSON-safe transcript audit summary."""

    return {
        "task_id": summary.task_id,
        "runtime_session_id": summary.runtime_session_id,
        "refs": [runtime_transcript_ref_to_dict(ref) for ref in summary.refs],
        "total_bytes": summary.total_bytes,
        "redaction_status": summary.redaction_status,
        "safe_summary": summary.safe_summary,
        "omitted_reason": summary.omitted_reason,
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


def _coerce_cancellation_reason(
    value: RuntimeCancellationReason | str,
) -> RuntimeCancellationReason:
    try:
        return RuntimeCancellationReason(value)
    except ValueError as exc:
        raise RuntimeResourceError(
            f"Unknown runtime cancellation reason: {value!r}"
        ) from exc


def _coerce_concurrency_dimension(
    value: RuntimeConcurrencyDimension | str,
) -> RuntimeConcurrencyDimension:
    try:
        return RuntimeConcurrencyDimension(value)
    except ValueError as exc:
        raise RuntimeResourceError(
            f"Unknown runtime concurrency dimension: {value!r}"
        ) from exc


def _coerce_concurrency_decision_kind(
    value: RuntimeConcurrencyDecisionKind | str,
) -> RuntimeConcurrencyDecisionKind:
    try:
        return RuntimeConcurrencyDecisionKind(value)
    except ValueError as exc:
        raise RuntimeResourceError(
            f"Unknown runtime concurrency decision: {value!r}"
        ) from exc


def _coerce_transcript_kind(value: RuntimeTranscriptKind | str) -> RuntimeTranscriptKind:
    try:
        return RuntimeTranscriptKind(value)
    except ValueError as exc:
        raise RuntimeResourceError(f"Unknown runtime transcript kind: {value!r}") from exc


def _coerce_transcript_retention_class(
    value: RuntimeTranscriptRetentionClass | str,
) -> RuntimeTranscriptRetentionClass:
    try:
        return RuntimeTranscriptRetentionClass(value)
    except ValueError as exc:
        raise RuntimeResourceError(
            f"Unknown runtime transcript retention class: {value!r}"
        ) from exc


_SENSITIVE_TRANSCRIPT_LABELS = frozenset(
    {
        "api_key",
        "authorization:",
        "credential",
        "full_transcript",
        "private_memory",
        "raw_stderr",
        "raw_stdout",
        "raw_transcript",
        "refresh_token",
    }
)


def _sanitize_secret_assignment(line: str) -> str:
    lowered = line.lower()
    for marker in ("secret=", "token=", "password="):
        index = lowered.find(marker)
        if index >= 0:
            return line[: index + len(marker)] + "[redacted]"
    return line


def _reject_unsafe_transcript_file_name(file_name: str) -> None:
    _require_string(file_name, "file_name")
    path = Path(file_name)
    if path.name != file_name or file_name in {".", ".."}:
        raise RuntimeResourceError("transcript file_name must be a single file name")
    lowered = file_name.lower()
    if any(part in lowered for part in ("memory", "manifest", "thread", "profile")):
        raise RuntimeResourceError("transcript file_name must not target durable assets")


def _ensure_runtime_data_path(path: Path, root: Path) -> None:
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    if resolved_path == resolved_root or resolved_root not in resolved_path.parents:
        raise RuntimeResourceError("transcript path must stay under runtime data root")


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

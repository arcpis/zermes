"""Registry-aware service operations for managed worker tasks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .profile import WorkerAgentProfile, WorkerProfileError
from .registry import WorkerLifecycleStatus, WorkerRegistryError
from .registry_service import WorkerRegistryService
from .storage import WorkerAgentRuntimeDataStore, WorkerTaskStore
from .task_state import (
    TERMINAL_TASK_STATUSES,
    WorkerTaskError,
    WorkerTaskState,
    WorkerTaskStatus,
    transition_task_status,
    utc_timestamp,
    validate_task_id,
)


@dataclass
class WorkerTaskService:
    """Create and update task state without executing runtime adapters."""

    registry_service: WorkerRegistryService
    task_store: WorkerTaskStore

    @classmethod
    def from_registry_service(
        cls,
        registry_service: WorkerRegistryService,
        *,
        runtime_store: WorkerAgentRuntimeDataStore | None = None,
    ) -> "WorkerTaskService":
        """Build a task service that shares the existing worker registry."""
        return cls(
            registry_service=registry_service,
            task_store=WorkerTaskStore(runtime_store or WorkerAgentRuntimeDataStore()),
        )

    def create_task(
        self,
        *,
        task_id: str,
        worker_id: str,
        title: str,
        objective: str,
        created_by: str = "system",
        input_summary: str | None = None,
        origin_thread_id: str | None = None,
        report_to_thread_id: str | None = None,
        budgets: Mapping[str, Any] | None = None,
        workspace: Mapping[str, Any] | None = None,
        tags: tuple[str, ...] | list[str] = (),
        queue: bool = False,
    ) -> WorkerTaskState:
        """Create a task snapshot for an enabled worker without starting it."""
        validate_task_id(task_id)
        record = self.registry_service.get_worker(worker_id)
        if record.status != WorkerLifecycleStatus.ENABLED:
            raise WorkerTaskError(
                f"Worker is not enabled for new tasks: {worker_id!r}"
            )
        try:
            profile = self.registry_service.profile_store.load_worker_profile(worker_id)
        except WorkerProfileError as exc:
            raise WorkerTaskError(f"Worker profile is invalid: {exc}") from exc

        task_budgets = dict(budgets or {})
        _ensure_budget_within_profile(task_budgets, profile)
        timestamp = self.registry_service.now()
        state = WorkerTaskState(
            task_id=task_id,
            worker_id=worker_id,
            title=title,
            objective=objective,
            created_by=created_by,
            created_at=timestamp,
            updated_at=timestamp,
            updated_by=created_by,
            status=WorkerTaskStatus.QUEUED if queue else WorkerTaskStatus.DRAFT,
            input_summary=input_summary,
            origin_thread_id=origin_thread_id,
            report_to_thread_id=report_to_thread_id,
            assigned_worker_status=record.status.value,
            profile_snapshot=_profile_snapshot(profile),
            budgets=task_budgets,
            workspace=dict(workspace or {}),
            tags=tuple(tags),
        )
        self.task_store.save_task_state(state)
        return state

    def get_task(self, task_id: str) -> WorkerTaskState:
        """Return one task state from clearable runtime storage."""
        return self.task_store.load_task_state(task_id)

    def list_tasks(
        self,
        *,
        worker_id: str | None = None,
        status: WorkerTaskStatus | str | None = None,
        created_by: str | None = None,
        tags: tuple[str, ...] | list[str] | None = None,
    ) -> list[WorkerTaskState]:
        """List task states using lightweight fields stored in runtime data."""
        target_status = WorkerTaskStatus(status) if status is not None else None
        required_tags = set(tags or ())
        result = []
        for state in self.task_store.list_task_states(
            worker_id=worker_id,
            status=target_status,
        ):
            if worker_id is not None and state.worker_id != worker_id:
                continue
            if target_status is not None and state.status != target_status:
                continue
            if created_by is not None and state.created_by != created_by:
                continue
            if required_tags and not required_tags.issubset(state.tags):
                continue
            result.append(state)
        return result

    def list_active_tasks(self, worker_id: str) -> list[WorkerTaskState]:
        """Return non-terminal tasks that make up a worker's current workload."""
        return [
            task
            for task in self.task_store.list_task_states(worker_id=worker_id)
            if task.status not in TERMINAL_TASK_STATUSES
        ]

    def queue_task(
        self, task_id: str, *, updated_by: str = "system", status_reason: str | None = None
    ) -> WorkerTaskState:
        """Mark a task ready for a future scheduler or adapter."""
        return self._transition_task(
            task_id,
            WorkerTaskStatus.QUEUED,
            updated_by=updated_by,
            status_reason=status_reason,
        )

    def start_task(
        self, task_id: str, *, updated_by: str = "system", status_reason: str | None = None
    ) -> WorkerTaskState:
        """Mark a task as running without launching any adapter process."""
        return self._transition_task(
            task_id,
            WorkerTaskStatus.RUNNING,
            updated_by=updated_by,
            status_reason=status_reason,
        )

    def wait_for_input(
        self, task_id: str, *, updated_by: str = "system", status_reason: str | None = None
    ) -> WorkerTaskState:
        """Pause a task until the user or main agent supplies information."""
        return self._transition_task(
            task_id,
            WorkerTaskStatus.WAITING_FOR_INPUT,
            updated_by=updated_by,
            status_reason=status_reason,
        )

    def wait_for_approval(
        self, task_id: str, *, updated_by: str = "system", status_reason: str | None = None
    ) -> WorkerTaskState:
        """Pause a task until a high-risk or high-cost action is approved."""
        return self._transition_task(
            task_id,
            WorkerTaskStatus.WAITING_FOR_APPROVAL,
            updated_by=updated_by,
            status_reason=status_reason,
        )

    def request_cancel_task(
        self, task_id: str, *, updated_by: str = "system", status_reason: str | None = None
    ) -> WorkerTaskState:
        """Record a cancellation request for a running or waiting task."""
        return self._transition_task(
            task_id,
            WorkerTaskStatus.CANCELLING,
            updated_by=updated_by,
            status_reason=status_reason,
        )

    def cancel_task(
        self, task_id: str, *, updated_by: str = "system", status_reason: str | None = None
    ) -> WorkerTaskState:
        """Mark a task cancelled after adapter or coordinator cleanup."""
        return self._transition_task(
            task_id,
            WorkerTaskStatus.CANCELLED,
            updated_by=updated_by,
            status_reason=status_reason,
        )

    def fail_task(
        self, task_id: str, *, updated_by: str = "system", status_reason: str | None = None
    ) -> WorkerTaskState:
        """Mark a task failed with a readable reason."""
        return self._transition_task(
            task_id,
            WorkerTaskStatus.FAILED,
            updated_by=updated_by,
            status_reason=status_reason,
        )

    def complete_task(
        self,
        task_id: str,
        *,
        updated_by: str = "system",
        status_reason: str | None = None,
        result: Mapping[str, Any] | None = None,
    ) -> WorkerTaskState:
        """Mark a task succeeded and store its compact result summary."""
        return self._transition_task(
            task_id,
            WorkerTaskStatus.SUCCEEDED,
            updated_by=updated_by,
            status_reason=status_reason,
            result=result,
        )

    def expire_task(
        self, task_id: str, *, updated_by: str = "system", status_reason: str | None = None
    ) -> WorkerTaskState:
        """Mark a task expired due to timeout or stale runtime data."""
        return self._transition_task(
            task_id,
            WorkerTaskStatus.EXPIRED,
            updated_by=updated_by,
            status_reason=status_reason,
        )

    def _transition_task(
        self,
        task_id: str,
        target_status: WorkerTaskStatus,
        *,
        updated_by: str,
        status_reason: str | None,
        result: Mapping[str, Any] | None = None,
    ) -> WorkerTaskState:
        state = self.task_store.load_task_state(task_id)
        updated = transition_task_status(
            state,
            target_status,
            updated_by=updated_by,
            status_reason=status_reason,
            now=self.registry_service.now(),
            result=result,
        )
        self.task_store.save_task_state(updated)
        return updated


def _profile_snapshot(profile: WorkerAgentProfile) -> dict[str, Any]:
    """Return the low-sensitivity profile fields useful for task recovery."""
    return {
        "schema_version": profile.schema_version,
        "role": profile.role,
        "runtime_type": profile.runtime.runtime_type,
        "adapter_name": profile.runtime.adapter_name,
        "default_model": profile.model.default_model,
        "max_task_tokens": profile.budgets.max_task_tokens,
        "max_turn_tokens": profile.budgets.max_turn_tokens,
        "timeout_seconds": profile.limits.timeout_seconds,
    }


def _ensure_budget_within_profile(
    requested: Mapping[str, Any], profile: WorkerAgentProfile
) -> None:
    for field_name, limit in (
        ("max_task_tokens", profile.budgets.max_task_tokens),
        ("max_turn_tokens", profile.budgets.max_turn_tokens),
    ):
        value = requested.get(field_name)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise WorkerTaskError(f"budgets.{field_name} must be a non-negative integer")
        if value > limit:
            raise WorkerTaskError(
                f"budgets.{field_name} exceeds worker profile limit"
            )

    cost_value = requested.get("max_task_cost_usd")
    cost_limit = profile.budgets.max_task_cost_usd
    if cost_value is not None:
        if isinstance(cost_value, bool) or not isinstance(cost_value, (int, float)):
            raise WorkerTaskError("budgets.max_task_cost_usd must be a number")
        if cost_value < 0:
            raise WorkerTaskError("budgets.max_task_cost_usd must be non-negative")
        if cost_limit is not None and float(cost_value) > cost_limit:
            raise WorkerTaskError("budgets.max_task_cost_usd exceeds worker profile limit")

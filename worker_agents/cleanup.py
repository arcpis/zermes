"""Dry-run cleanup planning for managed worker-agent runtime data."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import shutil
from typing import Any, Mapping
from uuid import uuid4

from utils import atomic_json_write

from .retention import (
    RetentionAction,
    RetentionDataCategory,
    RetentionPolicy,
    default_retention_policy,
)
from .storage.runtime_data_store import WorkerAgentRuntimeDataStore
from .storage.safe_paths import path_under_root
from .storage.task_store import WorkerTaskStore
from .task_records import WorkerTaskResult
from .task_state import TERMINAL_TASK_STATUSES, WorkerTaskError, WorkerTaskState


REVIEW_REQUIRED_RISK = "review_required"
LOW_RISK = "low"


@dataclass(frozen=True)
class CleanupPlanItem:
    """One relative runtime path and the action a cleanup run may take."""

    relative_path: str
    category: RetentionDataCategory
    action: RetentionAction
    reason: str
    can_delete: bool = False
    requires_review: bool = False
    risk_level: str = LOW_RISK
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CleanupPlan:
    """Dry-run cleanup plan for clearable worker-agent runtime data."""

    cleanup_run_id: str
    created_at: str
    policy_version: int
    scan_root: str
    items: tuple[CleanupPlanItem, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def summary(self) -> Mapping[str, int]:
        """Return item counts grouped by actionability."""
        delete_count = sum(1 for item in self.items if item.can_delete)
        review_count = sum(1 for item in self.items if item.requires_review)
        keep_count = len(self.items) - delete_count - review_count
        return {
            "total": len(self.items),
            "delete": delete_count,
            "review": review_count,
            "keep": keep_count,
            "warnings": len(self.warnings),
        }


@dataclass(frozen=True)
class CleanupExecutionResult:
    """Audit record for one bounded cleanup execution."""

    cleanup_run_id: str
    started_at: str
    finished_at: str
    policy_version: int
    scan_root: str
    deleted: tuple[str, ...] = ()
    skipped: Mapping[str, str] = field(default_factory=dict)
    failed: Mapping[str, str] = field(default_factory=dict)

    @property
    def summary(self) -> Mapping[str, int]:
        """Return counts for deleted, skipped, and failed plan items."""
        return {
            "deleted": len(self.deleted),
            "skipped": len(self.skipped),
            "failed": len(self.failed),
        }


@dataclass
class CleanupPlanner:
    """Build dry-run cleanup plans from the clearable runtime store."""

    runtime_store: WorkerAgentRuntimeDataStore = field(
        default_factory=WorkerAgentRuntimeDataStore
    )
    task_store: WorkerTaskStore | None = None
    policy: RetentionPolicy = field(default_factory=default_retention_policy)
    now: datetime | None = None

    def build_plan(self) -> CleanupPlan:
        """Scan known runtime directories and return a non-mutating cleanup plan."""
        runtime_store = self.runtime_store
        runtime_store.initialize()
        task_store = self.task_store or WorkerTaskStore(runtime_store)
        created_at = _format_utc(self.now or datetime.now(timezone.utc))
        items: list[CleanupPlanItem] = []
        warnings: list[str] = []

        items.extend(self._scan_task_directories(task_store, warnings))
        items.extend(self._scan_cache_directories())
        items.extend(self._scan_log_directories())

        return CleanupPlan(
            cleanup_run_id=f"cleanup-{uuid4().hex}",
            created_at=created_at,
            policy_version=self.policy.schema_version,
            scan_root=str(runtime_store.root.resolve(strict=False)),
            items=tuple(items),
            warnings=tuple(warnings),
        )

    def _scan_task_directories(
        self, task_store: WorkerTaskStore, warnings: list[str]
    ) -> list[CleanupPlanItem]:
        tasks_dir = self.runtime_store.tasks_dir
        if not tasks_dir.exists():
            return []
        items: list[CleanupPlanItem] = []
        for task_dir in sorted(path for path in tasks_dir.iterdir() if path.is_dir()):
            task_id = task_dir.name
            relative_path = _relative_runtime_path(self.runtime_store.root, task_dir)
            try:
                state = task_store.load_task_state(task_id)
            except WorkerTaskError as exc:
                warnings.append(f"{relative_path}: {exc}")
                items.append(
                    _plan_item(
                        relative_path=relative_path,
                        category=RetentionDataCategory.RUNTIME_ORPHANED,
                        reason="task runtime state could not be loaded",
                        policy=self.policy,
                        requires_review=True,
                    )
                )
                continue

            result = _try_load_task_result(task_store, task_id)
            items.append(
                self._classify_task_directory(
                    relative_path=relative_path,
                    state=state,
                    result=result,
                )
            )
        return items

    def _classify_task_directory(
        self,
        *,
        relative_path: str,
        state: WorkerTaskState,
        result: WorkerTaskResult | None,
    ) -> CleanupPlanItem:
        if state.status not in TERMINAL_TASK_STATUSES:
            return _plan_item(
                relative_path=relative_path,
                category=RetentionDataCategory.RUNTIME_ACTIVE,
                reason=f"task is still {state.status.value}",
                policy=self.policy,
            )

        if state.requests or _has_unresolved_candidates(result):
            return _plan_item(
                relative_path=relative_path,
                category=RetentionDataCategory.RUNTIME_NEEDS_REVIEW,
                reason="task has pending requests or unretained result candidates",
                policy=self.policy,
                requires_review=True,
            )

        rule = self.policy.rule_for(RetentionDataCategory.RUNTIME_EXPIRED_TERMINAL)
        if _is_expired(
            updated_at=state.updated_at,
            retention_days=rule.retention_days,
            now=self.now or datetime.now(timezone.utc),
        ):
            return _plan_item(
                relative_path=relative_path,
                category=RetentionDataCategory.RUNTIME_EXPIRED_TERMINAL,
                reason="terminal task runtime exceeded its retention window",
                policy=self.policy,
                can_delete=True,
            )

        return _plan_item(
            relative_path=relative_path,
            category=RetentionDataCategory.RUNTIME_RECENT_TERMINAL,
            reason="terminal task runtime is still inside its retention window",
            policy=self.policy,
        )

    def _scan_cache_directories(self) -> list[CleanupPlanItem]:
        return self._scan_clearable_children(
            self.runtime_store.cache_dir,
            RetentionDataCategory.CACHE_REBUILDABLE,
            "cache data can be regenerated",
        )

    def _scan_log_directories(self) -> list[CleanupPlanItem]:
        return self._scan_clearable_children(
            self.runtime_store.logs_dir,
            RetentionDataCategory.TRANSCRIPT_SENSITIVE,
            "logs and transcript-like data have short retention",
        )

    def _scan_clearable_children(
        self, parent: Path, category: RetentionDataCategory, reason: str
    ) -> list[CleanupPlanItem]:
        if not parent.exists():
            return []
        rule = self.policy.rule_for(category)
        items = []
        for child in sorted(parent.iterdir()):
            relative_path = _relative_runtime_path(self.runtime_store.root, child)
            expired = _path_is_expired(
                child, retention_days=rule.retention_days, now=self.now
            )
            items.append(
                _plan_item(
                    relative_path=relative_path,
                    category=category,
                    reason=reason if expired else "runtime data is still recent",
                    policy=self.policy,
                    can_delete=expired and rule.action == RetentionAction.DELETE_WHEN_EXPIRED,
                )
            )
        return items


@dataclass
class CleanupExecutor:
    """Execute a cleanup plan after rechecking runtime safety constraints."""

    runtime_store: WorkerAgentRuntimeDataStore = field(
        default_factory=WorkerAgentRuntimeDataStore
    )
    task_store: WorkerTaskStore | None = None
    now: datetime | None = None

    @property
    def cleanup_runs_dir(self) -> Path:
        return self.runtime_store.root / "cleanup-runs"

    def execute_plan(self, plan: CleanupPlan) -> CleanupExecutionResult:
        """Delete only items the dry-run plan marked as safe to delete."""
        self.runtime_store.initialize()
        self._validate_plan_root(plan)
        started_at = _format_utc(self.now or datetime.now(timezone.utc))
        deleted: list[str] = []
        skipped: dict[str, str] = {}
        failed: dict[str, str] = {}

        for item in plan.items:
            try:
                path = self._resolve_item_path(item)
                skip_reason = self._skip_reason(item, path)
                if skip_reason:
                    skipped[item.relative_path] = skip_reason
                    continue
                _delete_runtime_path(path)
                deleted.append(item.relative_path)
            except Exception as exc:  # noqa: BLE001 - cleanup must report all failures.
                failed[item.relative_path] = str(exc)

        finished_at = _format_utc(self.now or datetime.now(timezone.utc))
        result = CleanupExecutionResult(
            cleanup_run_id=plan.cleanup_run_id,
            started_at=started_at,
            finished_at=finished_at,
            policy_version=plan.policy_version,
            scan_root=plan.scan_root,
            deleted=tuple(deleted),
            skipped=skipped,
            failed=failed,
        )
        self._save_result(result)
        return result

    def _validate_plan_root(self, plan: CleanupPlan) -> None:
        expected = self.runtime_store.root.resolve(strict=False)
        actual = Path(plan.scan_root).resolve(strict=False)
        if actual != expected:
            raise ValueError("cleanup plan scan_root does not match runtime store")

    def _resolve_item_path(self, item: CleanupPlanItem) -> Path:
        relative = Path(item.relative_path)
        if relative.is_absolute():
            raise ValueError("cleanup plan item path must be relative")
        return path_under_root(self.runtime_store.root, relative)

    def _skip_reason(self, item: CleanupPlanItem, path: Path) -> str | None:
        if not item.can_delete:
            return "plan item is not marked for deletion"
        if item.requires_review:
            return "plan item requires review"
        if item.category in {
            RetentionDataCategory.PROTECTED_LONG_TERM,
            RetentionDataCategory.RUNTIME_ACTIVE,
            RetentionDataCategory.RUNTIME_NEEDS_REVIEW,
            RetentionDataCategory.RUNTIME_ORPHANED,
        }:
            return f"{item.category.value} items are not deleted by executor"
        if not path.exists():
            return "runtime path no longer exists"
        if not _is_known_clearable_path(item.relative_path):
            return "runtime path is not in a known clearable area"
        task_skip = self._task_skip_reason(item)
        if task_skip:
            return task_skip
        return None

    def _task_skip_reason(self, item: CleanupPlanItem) -> str | None:
        if not item.relative_path.startswith("tasks/"):
            return None
        parts = Path(item.relative_path).parts
        if len(parts) != 2:
            return "task cleanup items must target a task directory"
        task_store = self.task_store or WorkerTaskStore(self.runtime_store)
        task_id = parts[1]
        try:
            state = task_store.load_task_state(task_id)
        except WorkerTaskError:
            return "task state could not be reloaded safely"
        if state.status not in TERMINAL_TASK_STATUSES:
            return f"task is now {state.status.value}"
        result = _try_load_task_result(task_store, task_id)
        if state.requests or _has_unresolved_candidates(result):
            return "task now has requests or unretained result candidates"
        return None

    def _save_result(self, result: CleanupExecutionResult) -> Path:
        path = self.cleanup_runs_dir / result.cleanup_run_id / "result.json"
        atomic_json_write(path, cleanup_execution_result_to_dict(result))
        return path


def cleanup_plan_to_dict(plan: CleanupPlan) -> dict[str, Any]:
    """Convert a cleanup plan to deterministic JSON-ready data."""
    return {
        "cleanup_run_id": plan.cleanup_run_id,
        "created_at": plan.created_at,
        "policy_version": plan.policy_version,
        "scan_root": plan.scan_root,
        "summary": dict(plan.summary),
        "warnings": list(plan.warnings),
        "items": [cleanup_plan_item_to_dict(item) for item in plan.items],
    }


def cleanup_execution_result_to_dict(
    result: CleanupExecutionResult,
) -> dict[str, Any]:
    """Convert cleanup execution result to deterministic JSON-ready data."""
    return {
        "cleanup_run_id": result.cleanup_run_id,
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "policy_version": result.policy_version,
        "scan_root": result.scan_root,
        "summary": dict(result.summary),
        "deleted": list(result.deleted),
        "skipped": dict(result.skipped),
        "failed": dict(result.failed),
    }


def cleanup_plan_item_to_dict(item: CleanupPlanItem) -> dict[str, Any]:
    """Convert one cleanup plan item to deterministic JSON-ready data."""
    return {
        "relative_path": item.relative_path,
        "category": item.category.value,
        "action": item.action.value,
        "reason": item.reason,
        "can_delete": item.can_delete,
        "requires_review": item.requires_review,
        "risk_level": item.risk_level,
        "metadata": dict(item.metadata),
    }


def _plan_item(
    *,
    relative_path: str,
    category: RetentionDataCategory,
    reason: str,
    policy: RetentionPolicy,
    can_delete: bool = False,
    requires_review: bool = False,
) -> CleanupPlanItem:
    rule = policy.rule_for(category)
    review = requires_review or rule.action == RetentionAction.REVIEW_REQUIRED
    return CleanupPlanItem(
        relative_path=relative_path,
        category=category,
        action=rule.action,
        reason=reason,
        can_delete=can_delete and not review,
        requires_review=review,
        risk_level=REVIEW_REQUIRED_RISK if review else LOW_RISK,
        metadata={"retention_days": rule.retention_days},
    )


def _try_load_task_result(
    task_store: WorkerTaskStore, task_id: str
) -> WorkerTaskResult | None:
    try:
        return task_store.load_task_result(task_id)
    except WorkerTaskError:
        return None


def _has_unresolved_candidates(result: WorkerTaskResult | None) -> bool:
    if result is None:
        return False
    return bool(
        result.manifest_candidates
        or result.memory_candidates
        or result.audit_summary_candidates
    )


def _is_expired(
    *, updated_at: str, retention_days: int | None, now: datetime
) -> bool:
    if retention_days is None:
        return False
    updated = _parse_utc(updated_at)
    return (now - updated).days >= retention_days


def _path_is_expired(
    path: Path, *, retention_days: int | None, now: datetime | None
) -> bool:
    if retention_days is None:
        return False
    current = now or datetime.now(timezone.utc)
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return (current - modified).days >= retention_days


def _parse_utc(value: str) -> datetime:
    raw = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _relative_runtime_path(root: Path, path: Path) -> str:
    return path.resolve(strict=False).relative_to(root.resolve(strict=False)).as_posix()


def _is_known_clearable_path(relative_path: str) -> bool:
    parts = Path(relative_path).parts
    return bool(parts) and parts[0] in {"tasks", "cache", "logs"}


def _delete_runtime_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()

"""Governance rules for Hermes self-evolution.

This module only defines naming and safety policy. It does not create branches,
write audit documents, or modify product code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import re


EVOLUTION_WORKSPACE_NAME = "self-evolution"
TASKS_DIR_NAME = "tasks"
TEMP_DIR_NAME = "temp"
DEFAULT_DEVELOPMENT_BRANCH_PREFIX = "self-evolution/dev"
DEFAULT_INTEGRATION_BRANCH = "self-evolution/main"
AUDIT_FILE_NAMES = {
    "thinking": "thinking.md",
    "plan": "plan.md",
    "approval": "approval.md",
    "change_log": "change-log.md",
    "verification": "verification.md",
    "final_report": "final-report.md",
}


@dataclass(frozen=True)
class TaskRecordLayout:
    """Audit and temporary paths reserved for one self-evolution task."""

    task_id: str
    workspace_dir: Path
    task_dir: Path
    temp_dir: Path
    thinking_path: Path
    plan_path: Path
    approval_path: Path
    change_log_path: Path
    verification_path: Path
    final_report_path: Path


@dataclass(frozen=True)
class GovernancePolicy:
    """Required safety policy for self-evolution tasks."""

    require_user_approval_before_code_changes: bool = True
    require_small_commits: bool = True
    require_detailed_commit_messages: bool = True
    allow_automatic_main_merge: bool = False

    def validate(self) -> list[str]:
        """Return policy violations; an empty list means the policy is valid."""
        violations: list[str] = []
        if not self.require_user_approval_before_code_changes:
            violations.append("user_approval_required")
        if not self.require_small_commits:
            violations.append("small_commits_required")
        if not self.require_detailed_commit_messages:
            violations.append("detailed_commit_messages_required")
        if self.allow_automatic_main_merge:
            violations.append("automatic_main_merge_forbidden")
        return violations


def get_evolution_workspace(project_root: str | Path) -> Path:
    """Return the self-evolution workspace beside the project root."""
    root = Path(project_root).resolve()
    return root.parent / EVOLUTION_WORKSPACE_NAME


def make_task_id(requirement: str, *, now: datetime | None = None) -> str:
    """Build a readable task id from a requirement and timestamp."""
    timestamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    return f"{timestamp}-{_slugify(requirement)}"


def build_development_branch_name(task_id: str) -> str:
    """Build the dedicated development branch name for one task."""
    return f"{DEFAULT_DEVELOPMENT_BRANCH_PREFIX}/{_slugify(task_id, max_length=80)}"


def build_task_record_layout(project_root: str | Path, task_id: str) -> TaskRecordLayout:
    """Return the audit file layout for a self-evolution task.

    The function only describes paths. It does not create files or directories.
    """
    workspace_dir = get_evolution_workspace(project_root)
    safe_task_id = _slugify(task_id, max_length=80)
    task_dir = workspace_dir / TASKS_DIR_NAME / safe_task_id
    temp_dir = task_dir / TEMP_DIR_NAME
    return TaskRecordLayout(
        task_id=safe_task_id,
        workspace_dir=workspace_dir,
        task_dir=task_dir,
        temp_dir=temp_dir,
        thinking_path=task_dir / AUDIT_FILE_NAMES["thinking"],
        plan_path=task_dir / AUDIT_FILE_NAMES["plan"],
        approval_path=task_dir / AUDIT_FILE_NAMES["approval"],
        change_log_path=task_dir / AUDIT_FILE_NAMES["change_log"],
        verification_path=task_dir / AUDIT_FILE_NAMES["verification"],
        final_report_path=task_dir / AUDIT_FILE_NAMES["final_report"],
    )


def _slugify(value: str, *, max_length: int = 48) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        slug = "task"
    return slug[:max_length].strip("-") or "task"

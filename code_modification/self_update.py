"""Audited self-update application state for self-evolution tasks.

This module records the governed application flow after a self-evolution task
has been integrated. It deliberately does not restart the current process,
install dependencies, or run arbitrary build commands; those actions need a
separate allow-listed runner and explicit user approval.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Literal

from .executor import (
    STATE_FILE_NAME,
    ExecutionState,
    read_state,
    require_explicit_approval,
)
from .git_workflow import current_commit, require_git_repository, run_git
from .governance import build_task_record_layout


UPDATE_APPLICATION_FILE_NAME = "update-application.md"
UPDATE_STATE_FILE_NAME = "update-state.json"
DEPENDENCY_LOCK_FILES = (
    "pyproject.toml",
    "uv.lock",
    "requirements.txt",
    "requirements-dev.txt",
    "constraints.txt",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
)
VALID_UPDATE_MODES = {"manual", "cli", "gateway", "cron"}
VALID_HEALTH_CONCLUSIONS = {"passed", "failed", "inconclusive"}


class SelfUpdateApplicationError(RuntimeError):
    """Raised when a self-update application step is unsafe or out of order."""


@dataclass(frozen=True)
class UpdateEvent:
    status: str
    message: str
    created_at: str


@dataclass(frozen=True)
class SelfUpdateApplicationState:
    task_id: str
    status: str
    project_root: str
    mode: str
    candidate_commit: str
    previous_active_commit: str
    approved_by_user: bool = False
    dependency_files_changed: tuple[str, ...] = ()
    worktree_path: str = ""
    build_commands: tuple[str, ...] = ()
    health_checks: tuple[str, ...] = ()
    restart_command: str = ""
    rollback_command: str = ""
    blocked_reason: str = ""
    restart_required: bool = False
    history: tuple[UpdateEvent, ...] = ()


def plan_self_update_application(
    task_id: str,
    *,
    project_root: str | Path,
    candidate_ref: str | None = None,
    previous_active_ref: str | None = None,
    mode: str = "manual",
) -> SelfUpdateApplicationState:
    """Create the audited self-update plan for an integrated task."""
    root = require_git_repository(project_root)
    clean_mode = _normalize_mode(mode)
    layout = build_task_record_layout(root, task_id)
    _require_integrated_task(layout.task_dir / STATE_FILE_NAME)
    candidate_commit = _resolve_commit(root, candidate_ref or "HEAD")
    previous_active_commit = _resolve_commit(root, previous_active_ref) if previous_active_ref else current_commit(root)
    dependency_changes = _changed_dependency_files(root, previous_active_commit, candidate_commit)
    state = SelfUpdateApplicationState(
        task_id=layout.task_id,
        status="planned",
        project_root=str(root),
        mode=clean_mode,
        candidate_commit=candidate_commit,
        previous_active_commit=previous_active_commit,
        dependency_files_changed=dependency_changes,
        restart_command=_restart_guidance(clean_mode),
        rollback_command=f"restore previous active commit {previous_active_commit}",
        history=(
            UpdateEvent(
                status="planned",
                message="Self-update application plan created; no runtime changes were made.",
                created_at=_utc_timestamp(),
            ),
        ),
    )
    _write_update_records(layout.task_dir, state)
    return state


def prepare_self_update(
    task_id: str,
    *,
    approval_text: str,
    project_root: str | Path,
    worktree_path: str | None = None,
) -> SelfUpdateApplicationState:
    """Record user approval and candidate preparation intent."""
    require_explicit_approval(approval_text)
    root = require_git_repository(project_root)
    layout = build_task_record_layout(root, task_id)
    state = _read_update_state(layout.task_dir)
    _require_status(state, {"planned"})
    candidate_path = str(Path(worktree_path).expanduser()) if worktree_path else str(layout.temp_dir / "update-candidate")
    updated = _replace_state(
        state,
        status="prepared",
        approved_by_user=True,
        worktree_path=candidate_path,
        event="Candidate application record prepared; build and health checks are still pending.",
    )
    _write_update_records(layout.task_dir, updated)
    return updated


def record_self_update_build(
    task_id: str,
    *,
    project_root: str | Path,
    build_summary: str = "No build required for Python source update.",
) -> SelfUpdateApplicationState:
    """Record a build result without executing build commands."""
    root = require_git_repository(project_root)
    layout = build_task_record_layout(root, task_id)
    state = _read_update_state(layout.task_dir)
    _require_status(state, {"prepared"})
    updated = _replace_state(
        state,
        status="built",
        build_commands=(str(build_summary or "").strip() or "No build summary provided.",),
        event="Candidate build status recorded; no build command was executed by this tool.",
    )
    _write_update_records(layout.task_dir, updated)
    return updated


def record_self_update_health_check(
    task_id: str,
    *,
    project_root: str | Path,
    checks: list[str],
    conclusion: Literal["passed", "failed", "inconclusive"],
) -> SelfUpdateApplicationState:
    """Record health-check evidence for the prepared candidate."""
    root = require_git_repository(project_root)
    layout = build_task_record_layout(root, task_id)
    state = _read_update_state(layout.task_dir)
    _require_status(state, {"built", "verified", "blocked"})
    clean_checks = tuple(str(check).strip() for check in checks if str(check).strip())
    if not clean_checks:
        raise SelfUpdateApplicationError("at least one health check is required")
    clean_conclusion = str(conclusion or "").strip().lower()
    if clean_conclusion not in VALID_HEALTH_CONCLUSIONS:
        raise SelfUpdateApplicationError("conclusion must be passed, failed, or inconclusive")
    status = "verified" if clean_conclusion == "passed" else "blocked"
    blocked_reason = "" if status == "verified" else f"health check {clean_conclusion}"
    updated = _replace_state(
        state,
        status=status,
        health_checks=clean_checks,
        blocked_reason=blocked_reason,
        event=f"Health checks recorded with conclusion: {clean_conclusion}.",
    )
    _write_update_records(layout.task_dir, updated)
    return updated


def activate_self_update(
    task_id: str,
    *,
    approval_text: str,
    project_root: str | Path,
) -> SelfUpdateApplicationState:
    """Record activation approval and leave runtime restart pending."""
    require_explicit_approval(approval_text)
    root = require_git_repository(project_root)
    layout = build_task_record_layout(root, task_id)
    state = _read_update_state(layout.task_dir)
    _require_status(state, {"verified"})
    updated = _replace_state(
        state,
        status="restart_pending",
        restart_required=True,
        approved_by_user=True,
        event="Activation approved; restart remains a controlled follow-up and was not executed.",
    )
    _write_update_records(layout.task_dir, updated)
    return updated


def rollback_self_update(
    task_id: str,
    *,
    approval_text: str,
    project_root: str | Path,
    reason: str = "",
) -> SelfUpdateApplicationState:
    """Record rollback approval for the previously active commit."""
    require_explicit_approval(approval_text)
    root = require_git_repository(project_root)
    layout = build_task_record_layout(root, task_id)
    state = _read_update_state(layout.task_dir)
    clean_reason = str(reason or "").strip()
    updated = _replace_state(
        state,
        status="rolled_back",
        restart_required=True,
        blocked_reason=clean_reason,
        event=(
            f"Rollback approved to previous active commit {state.previous_active_commit}."
            + (f" Reason: {clean_reason}" if clean_reason else "")
        ),
    )
    _write_update_records(layout.task_dir, updated)
    return updated


def describe_self_update_application(task_id: str, *, project_root: str | Path) -> dict:
    """Return self-update application audit paths and state."""
    root = require_git_repository(project_root)
    layout = build_task_record_layout(root, task_id)
    state_path = layout.task_dir / UPDATE_STATE_FILE_NAME
    application_path = layout.task_dir / UPDATE_APPLICATION_FILE_NAME
    state = _read_update_state(layout.task_dir) if state_path.exists() else None
    return {
        "task_id": layout.task_id,
        "has_update_application": application_path.exists(),
        "has_update_state": state_path.exists(),
        "update_application_path": str(application_path),
        "update_state_path": str(state_path),
        "state": asdict(state) if state else None,
    }


def _require_integrated_task(state_path: Path) -> ExecutionState:
    if not state_path.exists():
        raise SelfUpdateApplicationError("execution state is missing; finalize the code task first")
    state = read_state(state_path)
    if state.status != "integrated":
        raise SelfUpdateApplicationError("self-update application requires an integrated task")
    return state


def _resolve_commit(project_root: Path, ref: str) -> str:
    clean_ref = str(ref or "").strip()
    if not clean_ref:
        raise SelfUpdateApplicationError("git ref is required")
    return run_git(project_root, "rev-parse", clean_ref).stdout.strip()


def _changed_dependency_files(
    project_root: Path,
    previous_commit: str,
    candidate_commit: str,
) -> tuple[str, ...]:
    if previous_commit == candidate_commit:
        return ()
    output = run_git(project_root, "diff", "--name-only", previous_commit, candidate_commit).stdout
    changed = {line.strip() for line in output.splitlines() if line.strip()}
    return tuple(path for path in DEPENDENCY_LOCK_FILES if path in changed)


def _read_update_state(task_dir: Path) -> SelfUpdateApplicationState:
    path = task_dir / UPDATE_STATE_FILE_NAME
    if not path.exists():
        raise SelfUpdateApplicationError("self-update application plan is missing")
    payload = json.loads(path.read_text(encoding="utf-8"))
    history = tuple(UpdateEvent(**event) for event in payload.get("history", []))
    return SelfUpdateApplicationState(
        task_id=payload["task_id"],
        status=payload["status"],
        project_root=payload["project_root"],
        mode=payload["mode"],
        candidate_commit=payload["candidate_commit"],
        previous_active_commit=payload["previous_active_commit"],
        approved_by_user=bool(payload.get("approved_by_user", False)),
        dependency_files_changed=tuple(payload.get("dependency_files_changed", [])),
        worktree_path=str(payload.get("worktree_path", "")),
        build_commands=tuple(payload.get("build_commands", [])),
        health_checks=tuple(payload.get("health_checks", [])),
        restart_command=str(payload.get("restart_command", "")),
        rollback_command=str(payload.get("rollback_command", "")),
        blocked_reason=str(payload.get("blocked_reason", "")),
        restart_required=bool(payload.get("restart_required", False)),
        history=history,
    )


def _write_update_records(task_dir: Path, state: SelfUpdateApplicationState) -> None:
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / UPDATE_STATE_FILE_NAME).write_text(
        json.dumps(asdict(state), indent=2) + "\n",
        encoding="utf-8",
    )
    (task_dir / UPDATE_APPLICATION_FILE_NAME).write_text(
        _format_update_application(state),
        encoding="utf-8",
    )


def _format_update_application(state: SelfUpdateApplicationState) -> str:
    dependency_text = ", ".join(state.dependency_files_changed) or "none"
    health_text = "\n".join(f"- {check}" for check in state.health_checks) or "- not recorded"
    history_text = "\n".join(
        f"- {event.created_at} `{event.status}`: {event.message}"
        for event in state.history
    )
    return (
        "# Self-Update Application\n\n"
        f"Task: `{state.task_id}`\n\n"
        f"Status: `{state.status}`\n\n"
        f"Mode: `{state.mode}`\n\n"
        f"Candidate commit: `{state.candidate_commit}`\n\n"
        f"Previous active commit: `{state.previous_active_commit}`\n\n"
        f"Dependency files changed: {dependency_text}\n\n"
        f"Worktree path: `{state.worktree_path or 'not prepared'}`\n\n"
        f"Restart command: {state.restart_command or 'not defined'}\n\n"
        f"Rollback command: {state.rollback_command or 'not defined'}\n\n"
        "## Health Checks\n\n"
        f"{health_text}\n\n"
        "## History\n\n"
        f"{history_text}\n"
    )


def _replace_state(
    state: SelfUpdateApplicationState,
    *,
    status: str,
    event: str,
    approved_by_user: bool | None = None,
    dependency_files_changed: tuple[str, ...] | None = None,
    worktree_path: str | None = None,
    build_commands: tuple[str, ...] | None = None,
    health_checks: tuple[str, ...] | None = None,
    blocked_reason: str | None = None,
    restart_required: bool | None = None,
) -> SelfUpdateApplicationState:
    return SelfUpdateApplicationState(
        task_id=state.task_id,
        status=status,
        project_root=state.project_root,
        mode=state.mode,
        candidate_commit=state.candidate_commit,
        previous_active_commit=state.previous_active_commit,
        approved_by_user=state.approved_by_user if approved_by_user is None else approved_by_user,
        dependency_files_changed=state.dependency_files_changed
        if dependency_files_changed is None
        else dependency_files_changed,
        worktree_path=state.worktree_path if worktree_path is None else worktree_path,
        build_commands=state.build_commands if build_commands is None else build_commands,
        health_checks=state.health_checks if health_checks is None else health_checks,
        restart_command=state.restart_command,
        rollback_command=state.rollback_command,
        blocked_reason=state.blocked_reason if blocked_reason is None else blocked_reason,
        restart_required=state.restart_required if restart_required is None else restart_required,
        history=(
            *state.history,
            UpdateEvent(status=status, message=event, created_at=_utc_timestamp()),
        ),
    )


def _require_status(state: SelfUpdateApplicationState, allowed: set[str]) -> None:
    if state.status not in allowed:
        raise SelfUpdateApplicationError(
            f"self-update application status must be one of {', '.join(sorted(allowed))}"
        )


def _normalize_mode(mode: str) -> str:
    clean_mode = str(mode or "manual").strip().lower()
    if clean_mode not in VALID_UPDATE_MODES:
        raise SelfUpdateApplicationError("mode must be manual, cli, gateway, or cron")
    return clean_mode


def _restart_guidance(mode: str) -> str:
    if mode == "cli":
        return "restart the CLI after the current turn"
    if mode == "gateway":
        return "drain active gateway runs, then restart the gateway supervisor"
    if mode == "cron":
        return "pause scheduled jobs, activate the candidate, then resume scheduling"
    return "manual restart required after activation approval"


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat()

"""Execution state for approved self-evolution tasks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import re

from .git_workflow import (
    GitWorkflowError,
    commit_explicit_files,
    create_or_switch_development_branch,
    current_branch,
    current_commit,
    merge_development_branch,
    normalize_files,
    require_clean_worktree,
    require_git_repository,
)
from .governance import DEFAULT_INTEGRATION_BRANCH, build_task_record_layout


STATE_FILE_NAME = "execution-state.json"


class CodeTaskExecutionError(RuntimeError):
    """Raised when an approved code task cannot continue."""


@dataclass(frozen=True)
class CommitRecord:
    commit_hash: str
    summary: str
    files: tuple[str, ...]
    verification_summary: str


@dataclass(frozen=True)
class PlanStepRecord:
    description: str
    status: str = "pending"
    commit_hash: str = ""


@dataclass(frozen=True)
class ExecutionState:
    task_id: str
    status: str
    project_root: str
    base_branch: str
    base_commit: str
    development_branch: str
    integration_branch: str = DEFAULT_INTEGRATION_BRANCH
    commits: tuple[CommitRecord, ...] = ()
    approved_areas: tuple[str, ...] = ()
    plan_steps: tuple[PlanStepRecord, ...] = ()
    documentation_updates: tuple[str, ...] = ()


def start_approved_task(
    task_id: str,
    *,
    approval_text: str,
    project_root: str | Path,
    install_prefix: str | Path | None = None,
    workspace_dir: str | Path | None = None,
    base_branch: str | None = None,
) -> ExecutionState:
    root = require_git_repository(project_root)
    layout = build_task_record_layout(
        root,
        task_id,
        install_prefix=install_prefix,
        workspace_dir=workspace_dir,
    )
    # Execution only continues records produced by the approval planner; it
    # never creates a fresh task record while preparing git changes.
    require_approval_record(layout.plan_path, layout.approval_path)
    require_explicit_approval(approval_text)
    require_clean_worktree(root)

    original_branch = current_branch(root)
    start_branch = base_branch or original_branch
    base_commit = current_commit(root)
    development_branch = read_development_branch(layout.plan_path)
    approved_areas = read_markdown_bullets(layout.plan_path, "Affected Areas")
    documentation_updates = read_documentation_updates(layout.plan_path)
    plan_steps = tuple(
        PlanStepRecord(description=description)
        for description in read_markdown_bullets(layout.plan_path, "Tasks")
    )
    create_or_switch_development_branch(root, development_branch, base_branch=base_branch)
    # Persist state outside git so a later tool call can resume without parsing
    # the human-facing change log.
    state = ExecutionState(
        task_id=layout.task_id,
        status="branch_created",
        project_root=str(root),
        base_branch=start_branch,
        base_commit=base_commit,
        development_branch=development_branch,
        approved_areas=approved_areas,
        plan_steps=plan_steps,
        documentation_updates=documentation_updates,
    )
    write_state(layout.task_dir / STATE_FILE_NAME, state)
    append_change_log(
        layout.change_log_path,
        "branch_created",
        [
            f"Base branch: `{start_branch}`",
            f"Base commit: `{base_commit}`",
            f"Development branch: `{development_branch}`",
            f"Approved areas: {', '.join(approved_areas) or 'not specified'}",
            f"Planned steps: {len(plan_steps)}",
            f"Documentation update candidates: {', '.join(documentation_updates) or 'none'}",
        ],
    )
    return state


def commit_task_step(
    task_id: str,
    *,
    summary: str,
    files: list[str],
    verification_summary: str = "",
    plan_step_index: int | None = None,
    project_root: str | Path,
    install_prefix: str | Path | None = None,
    workspace_dir: str | Path | None = None,
) -> tuple[ExecutionState, str]:
    root = require_git_repository(project_root)
    layout = build_task_record_layout(
        root,
        task_id,
        install_prefix=install_prefix,
        workspace_dir=workspace_dir,
    )
    state = read_state(layout.task_dir / STATE_FILE_NAME)
    # Commits are only valid from the task branch; this prevents a delayed tool
    # call from committing unrelated changes on the user's current branch.
    require_task_branch(root, state.development_branch)
    require_open_state(state)
    normalized_files = normalize_files(root, files)
    require_approved_files(normalized_files, state.approved_areas)
    commit_hash = commit_explicit_files(
        root,
        task_id=state.task_id,
        summary=summary,
        files=normalized_files,
        verification_summary=verification_summary,
    )
    record = CommitRecord(
        commit_hash=commit_hash,
        summary=summary.strip(),
        files=tuple(normalized_files),
        verification_summary=verification_summary.strip() or "not run",
    )
    updated_steps = mark_plan_step_completed(state.plan_steps, commit_hash, plan_step_index)
    updated = replace_state_status(
        state,
        "committed",
        commits=(*state.commits, record),
        plan_steps=updated_steps,
    )
    write_state(layout.task_dir / STATE_FILE_NAME, updated)
    append_change_log(
        layout.change_log_path,
        "committed",
        [
            f"Commit: `{commit_hash}`",
            f"Summary: {record.summary}",
            f"Files: {', '.join(record.files)}",
            f"Verification: {record.verification_summary}",
            f"Completed plan step: {completed_step_text(updated_steps, commit_hash)}",
        ],
    )
    return updated, commit_hash


def finalize_task_branch(
    task_id: str,
    *,
    project_root: str | Path,
    install_prefix: str | Path | None = None,
    workspace_dir: str | Path | None = None,
) -> ExecutionState:
    root = require_git_repository(project_root)
    layout = build_task_record_layout(
        root,
        task_id,
        install_prefix=install_prefix,
        workspace_dir=workspace_dir,
    )
    state = read_state(layout.task_dir / STATE_FILE_NAME)
    require_task_branch(root, state.development_branch)
    require_open_state(state)
    if not state.commits:
        raise CodeTaskExecutionError("at least one task commit is required before finalizing")
    require_passed_verification(layout.verification_path)
    try:
        merge_development_branch(
            root,
            development_branch=state.development_branch,
            base_ref=state.base_commit,
            integration_branch=state.integration_branch,
        )
    except GitWorkflowError as exc:
        # Record blocked merges before surfacing the error so the audit trail
        # remains useful even when the agent cannot complete the flow.
        blocked = replace_state_status(state, "blocked")
        write_state(layout.task_dir / STATE_FILE_NAME, blocked)
        append_change_log(layout.change_log_path, "blocked", [str(exc)])
        raise CodeTaskExecutionError(str(exc)) from exc

    integrated = replace_state_status(state, "integrated")
    write_state(layout.task_dir / STATE_FILE_NAME, integrated)
    write_final_report(layout.final_report_path, integrated)
    append_change_log(
        layout.change_log_path,
        "integrated",
        [
            f"Development branch: `{state.development_branch}`",
            f"Integration branch: `{state.integration_branch}`",
        ],
    )
    return integrated


def describe_task_execution(
    task_id: str,
    *,
    project_root: str | Path,
    install_prefix: str | Path | None = None,
    workspace_dir: str | Path | None = None,
) -> dict:
    root = require_git_repository(project_root)
    layout = build_task_record_layout(
        root,
        task_id,
        install_prefix=install_prefix,
        workspace_dir=workspace_dir,
    )
    state_path = layout.task_dir / STATE_FILE_NAME
    state = read_state(state_path) if state_path.exists() else None
    verification_status = read_latest_verification_status(layout.verification_path)
    return {
        "task_id": layout.task_id,
        "has_plan": layout.plan_path.exists(),
        "has_approval": layout.approval_path.exists(),
        "has_change_log": layout.change_log_path.exists(),
        "has_verification": layout.verification_path.exists(),
        "state_path": str(state_path),
        "change_log_path": str(layout.change_log_path),
        "verification_path": str(layout.verification_path),
        "verification_status": verification_status,
        "state": asdict(state) if state else None,
    }


def require_approval_record(plan_path: Path, approval_path: Path) -> None:
    missing = [str(path) for path in (plan_path, approval_path) if not path.exists()]
    if missing:
        raise CodeTaskExecutionError(f"approval record is missing: {', '.join(missing)}")


def require_explicit_approval(approval_text: str) -> None:
    normalized = approval_text.strip().lower()
    # Negative approval phrases win over short positive tokens such as "approved"
    # in "not approved".
    blocked_phrases = ("do not approve", "not approved", "reject", "rejected")
    approval_terms = ("approve", "approved", "yes", "proceed", "go ahead", "confirmed")
    if not normalized or any(phrase in normalized for phrase in blocked_phrases):
        raise CodeTaskExecutionError("explicit user approval is required")
    if not any(term in normalized for term in approval_terms):
        raise CodeTaskExecutionError("explicit user approval is required")


def read_development_branch(plan_path: Path) -> str:
    text = plan_path.read_text(encoding="utf-8")
    match = re.search(r"Development branch:\s*`([^`]+)`", text)
    if not match:
        raise CodeTaskExecutionError("development branch is missing from the approval plan")
    return match.group(1).strip()


def read_markdown_bullets(path: Path, heading: str) -> tuple[str, ...]:
    text = path.read_text(encoding="utf-8")
    match = re.search(rf"^## {re.escape(heading)}\n\n(?P<body>.*?)(?=\n## |\Z)", text, re.M | re.S)
    if not match:
        return ()
    bullets = []
    for line in match.group("body").splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            bullets.append(stripped[2:].strip())
    return tuple(item for item in bullets if item)


def read_state(path: Path) -> ExecutionState:
    if not path.exists():
        raise CodeTaskExecutionError("execution state is missing; start the approved task first")
    data = json.loads(path.read_text(encoding="utf-8"))
    commits = tuple(CommitRecord(**item) for item in data.pop("commits", []))
    plan_steps = tuple(PlanStepRecord(**item) for item in data.pop("plan_steps", []))
    approved_areas = tuple(data.pop("approved_areas", []))
    documentation_updates = tuple(data.pop("documentation_updates", []))
    return ExecutionState(
        **data,
        commits=commits,
        approved_areas=approved_areas,
        plan_steps=plan_steps,
        documentation_updates=documentation_updates,
    )


def write_state(path: Path, state: ExecutionState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")


def replace_state_status(
    state: ExecutionState,
    status: str,
    *,
    commits: tuple[CommitRecord, ...] | None = None,
    plan_steps: tuple[PlanStepRecord, ...] | None = None,
) -> ExecutionState:
    return ExecutionState(
        task_id=state.task_id,
        status=status,
        project_root=state.project_root,
        base_branch=state.base_branch,
        base_commit=state.base_commit,
        development_branch=state.development_branch,
        integration_branch=state.integration_branch,
        commits=state.commits if commits is None else commits,
        approved_areas=state.approved_areas,
        plan_steps=state.plan_steps if plan_steps is None else plan_steps,
        documentation_updates=state.documentation_updates,
    )


def require_open_state(state: ExecutionState) -> None:
    if state.status in {"integrated", "blocked"}:
        raise CodeTaskExecutionError(f"task cannot continue from status {state.status}")


def require_task_branch(project_root: str | Path, development_branch: str) -> None:
    branch = current_branch(project_root)
    if branch != development_branch:
        raise CodeTaskExecutionError(f"current branch must be {development_branch}")


def require_approved_files(files: list[str], approved_areas: tuple[str, ...]) -> None:
    concrete_areas = tuple(
        area.replace("\\", "/").rstrip("/")
        for area in approved_areas
        if area and "to be confirmed" not in area.lower()
    )
    if not concrete_areas:
        return
    for file_name in files:
        if not any(file_name == area or file_name.startswith(f"{area}/") for area in concrete_areas):
            raise CodeTaskExecutionError(f"file is outside the approved areas: {file_name}")


def mark_plan_step_completed(
    steps: tuple[PlanStepRecord, ...],
    commit_hash: str,
    plan_step_index: int | None,
) -> tuple[PlanStepRecord, ...]:
    if not steps:
        return steps
    index = plan_step_index if plan_step_index is not None else next_pending_step_index(steps)
    if index is None:
        return steps
    if index < 0 or index >= len(steps):
        raise CodeTaskExecutionError("plan_step_index is out of range")
    return tuple(
        PlanStepRecord(
            description=step.description,
            status="completed" if position == index else step.status,
            commit_hash=commit_hash if position == index else step.commit_hash,
        )
        for position, step in enumerate(steps)
    )


def next_pending_step_index(steps: tuple[PlanStepRecord, ...]) -> int | None:
    for index, step in enumerate(steps):
        if step.status == "pending":
            return index
    return None


def completed_step_text(steps: tuple[PlanStepRecord, ...], commit_hash: str) -> str:
    for index, step in enumerate(steps):
        if step.commit_hash == commit_hash:
            return f"{index}: {step.description}"
    return "none"


def write_final_report(path: Path, state: ExecutionState) -> None:
    verification_path = path.parent / "verification.md"
    verification_status = read_latest_verification_status(verification_path)
    lines = [
        "# Final Report",
        "",
        f"- Task ID: `{state.task_id}`",
        f"- Status: `{state.status}`",
        f"- Development branch: `{state.development_branch}`",
        f"- Integration branch: `{state.integration_branch}`",
        f"- Verification: `{verification_status or 'not recorded'}`",
        "",
        "## Commits",
        "",
    ]
    if state.commits:
        for commit in state.commits:
            lines.append(f"- `{commit.commit_hash}` {commit.summary}")
    else:
        lines.append("- None.")
    lines.extend(["", "## Plan Steps", ""])
    if state.plan_steps:
        for step in state.plan_steps:
            suffix = f" (`{step.commit_hash}`)" if step.commit_hash else ""
            lines.append(f"- `{step.status}` {step.description}{suffix}")
    else:
        lines.append("- None recorded.")
    lines.extend(["", "## Verification", ""])
    if verification_path.exists():
        lines.append(f"- Verification record: `{verification_path}`")
        lines.append(f"- Latest status: `{verification_status or 'unknown'}`")
    else:
        lines.append("- No stage 4 verification record exists.")
    lines.extend(["", "## Documentation Sync", ""])
    lines.extend(documentation_sync_lines(state))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_documentation_updates(plan_path: Path) -> tuple[str, ...]:
    """Return documentation update candidates recorded in the approval plan."""
    text = plan_path.read_text(encoding="utf-8")
    match = re.search(
        r"^- Documentation updates:\n(?P<body>(?:  - .+\n?)*)",
        text,
        re.M,
    )
    if not match:
        return ()
    updates = []
    for line in match.group("body").splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            value = stripped[2:].strip()
            if value and value.lower() != "none identified.":
                updates.append(value)
    return tuple(updates)


def documentation_sync_lines(state: ExecutionState) -> list[str]:
    """Render documentation candidates and which of them were committed."""
    if not state.documentation_updates:
        return ["- No documentation updates were identified in the approval plan."]
    committed_files = {
        file_name
        for commit in state.commits
        for file_name in commit.files
    }
    updated = tuple(
        path for path in state.documentation_updates if path in committed_files
    )
    pending = tuple(
        path for path in state.documentation_updates if path not in committed_files
    )
    lines = [
        "- Candidates from approval plan:",
        *[f"  - {path}" for path in state.documentation_updates],
        "- Updated in task commits:",
    ]
    lines.extend(f"  - {path}" for path in updated) if updated else lines.append("  - None.")
    lines.append("- Pending or intentionally unchanged:")
    lines.extend(f"  - {path}" for path in pending) if pending else lines.append("  - None.")
    return lines


def append_change_log(path: Path, status: str, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).isoformat()
    # The log is append-only and human-readable; execution-state.json is the
    # machine-readable source for later tool calls.
    rendered_lines = [f"# Change Log\n"] if not path.exists() else []
    rendered_lines.extend([f"## {timestamp} - {status}", ""])
    rendered_lines.extend(f"- {line}" for line in lines)
    rendered_lines.append("")
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(rendered_lines))
        handle.write("\n")


def read_latest_verification_status(path: Path) -> str | None:
    state_path = path.parent / "verification-state.json"
    if state_path.exists():
        try:
            return json.loads(state_path.read_text(encoding="utf-8")).get("status")
        except (OSError, json.JSONDecodeError):
            return "unreadable"
    if not path.exists():
        return None
    statuses = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## ") and " - " in line:
            statuses.append(line.rsplit(" - ", 1)[-1].strip())
    return statuses[-1] if statuses else "recorded"


def require_passed_verification(path: Path) -> None:
    state_path = path.parent / "verification-state.json"
    if not state_path.exists():
        raise CodeTaskExecutionError("stage 4 verification must pass before finalizing")
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CodeTaskExecutionError("stage 4 verification state is unreadable") from exc
    results = data.get("command_results") or []
    if not results:
        raise CodeTaskExecutionError("stage 4 verification must pass before finalizing")
    failed_required = [
        result
        for result in results
        if result.get("required", True) and result.get("status") != "passed"
    ]
    if failed_required:
        raise CodeTaskExecutionError("stage 4 verification must pass before finalizing")

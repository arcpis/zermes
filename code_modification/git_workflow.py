"""Git helpers for approved self-evolution tasks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess

from .governance import DEFAULT_DEVELOPMENT_BRANCH_PREFIX, DEFAULT_INTEGRATION_BRANCH


class GitWorkflowError(RuntimeError):
    """Raised when an approved task cannot safely advance in git."""


@dataclass(frozen=True)
class GitCommandResult:
    stdout: str
    stderr: str


def require_git_repository(project_root: str | Path) -> Path:
    root = Path(project_root).resolve()
    result = run_git(root, "rev-parse", "--show-toplevel")
    repo_root = Path(result.stdout.strip()).resolve()
    # Keep callers honest: all paths, audit records, and branch operations assume
    # the supplied root is the repository root, not a nested package directory.
    if repo_root != root:
        raise GitWorkflowError(f"project_root must be the git root: {repo_root}")
    return root


def require_clean_worktree(project_root: str | Path) -> None:
    result = run_git(project_root, "status", "--porcelain")
    if result.stdout.strip():
        raise GitWorkflowError("working tree must be clean before continuing")


def current_branch(project_root: str | Path) -> str:
    result = run_git(project_root, "branch", "--show-current")
    branch = result.stdout.strip()
    if not branch:
        raise GitWorkflowError("current git checkout is detached")
    return branch


def current_commit(project_root: str | Path) -> str:
    return run_git(project_root, "rev-parse", "HEAD").stdout.strip()


def create_or_switch_development_branch(
    project_root: str | Path,
    branch_name: str,
    *,
    base_branch: str | None = None,
) -> str:
    if not branch_name.startswith(f"{DEFAULT_DEVELOPMENT_BRANCH_PREFIX}/"):
        raise GitWorkflowError("development branch must use the self-evolution/dev namespace")
    require_clean_worktree(project_root)
    # Switching the base branch is optional, but when requested it must happen
    # before the task branch is created so the task has an auditable starting point.
    if base_branch:
        run_git(project_root, "switch", base_branch)
        require_clean_worktree(project_root)
    if branch_exists(project_root, branch_name):
        run_git(project_root, "switch", branch_name)
    else:
        run_git(project_root, "switch", "-c", branch_name)
    return current_commit(project_root)


def commit_explicit_files(
    project_root: str | Path,
    *,
    task_id: str,
    summary: str,
    files: list[str],
    verification_summary: str = "",
) -> str:
    clean_files = normalize_files(project_root, files)
    # The double dash prevents a file path that starts with "-" from being
    # interpreted as another git option.
    run_git(project_root, "add", "--", *clean_files)
    message = build_commit_message(
        task_id=task_id,
        summary=summary,
        files=clean_files,
        verification_summary=verification_summary,
    )
    run_git(project_root, "commit", "-m", message)
    return current_commit(project_root)


def merge_development_branch(
    project_root: str | Path,
    *,
    development_branch: str,
    base_ref: str,
    integration_branch: str = DEFAULT_INTEGRATION_BRANCH,
) -> None:
    require_clean_worktree(project_root)
    if not development_branch.startswith(f"{DEFAULT_DEVELOPMENT_BRANCH_PREFIX}/"):
        raise GitWorkflowError("development branch must use the self-evolution/dev namespace")
    if integration_branch != DEFAULT_INTEGRATION_BRANCH:
        raise GitWorkflowError("integration branch must be self-evolution/main")

    # The integration branch is created from the task base commit, then receives
    # only approved self-evolution task branches. It is never the product main branch.
    if branch_exists(project_root, integration_branch):
        run_git(project_root, "switch", integration_branch)
    else:
        run_git(project_root, "switch", "-c", integration_branch, base_ref)
    require_clean_worktree(project_root)
    try:
        run_git(
            project_root,
            "merge",
            "--no-ff",
            development_branch,
            "-m",
            f"Integrate self-evolution task from {development_branch}",
        )
    except GitWorkflowError as exc:
        raise GitWorkflowError(f"merge blocked: {exc}") from exc


def branch_exists(project_root: str | Path, branch_name: str) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", branch_name],
        cwd=Path(project_root),
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def normalize_files(project_root: str | Path, files: list[str]) -> list[str]:
    if not isinstance(files, list) or not files:
        raise GitWorkflowError("files must be a non-empty list")

    root = Path(project_root).resolve()
    normalized: list[str] = []
    for raw_file in files:
        file_text = str(raw_file).strip()
        if not file_text:
            continue
        # Broad staging would make the audit log unreliable because unrelated
        # local edits could be swept into the task commit.
        if file_text in {".", "*"} or any(char in file_text for char in "*?[]"):
            raise GitWorkflowError("files must name explicit paths")
        file_path = Path(file_text)
        resolved = file_path.resolve() if file_path.is_absolute() else (root / file_path).resolve()
        try:
            # Resolve before comparing so symlinks cannot escape the project root.
            relative = resolved.relative_to(root)
        except ValueError as exc:
            raise GitWorkflowError("files must stay inside project_root") from exc
        normalized.append(relative.as_posix())

    if not normalized:
        raise GitWorkflowError("files must be a non-empty list")
    return normalized


def build_commit_message(
    *,
    task_id: str,
    summary: str,
    files: list[str],
    verification_summary: str,
) -> str:
    clean_summary = summary.strip()
    if not clean_summary:
        raise GitWorkflowError("summary is required")
    verification = verification_summary.strip() or "not run"
    files_text = ", ".join(files)
    return (
        f"chore(self-evolution): {clean_summary}\n\n"
        f"Task: {task_id}\n"
        f"Files: {files_text}\n"
        f"Verification: {verification}"
    )


def run_git(project_root: str | Path, *args: str) -> GitCommandResult:
    # Use argv form instead of shell=True so branch names and file paths are not
    # reinterpreted by the user's shell.
    result = subprocess.run(
        ["git", *args],
        cwd=Path(project_root),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "git command failed").strip()
        raise GitWorkflowError(message)
    return GitCommandResult(stdout=result.stdout, stderr=result.stderr)

"""Governance rules for Hermes self-evolution.

This module only defines naming and safety policy. It does not create branches,
write audit documents, or modify product code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any


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
PROJECT_ROOT_CONFIG_PATH = ("self_evolution", "source_repo")
INVALID_PROJECT_ROOT_HINT = (
    "Pass project_root with the development source repository path, or configure "
    "self_evolution.source_repo."
)
RUNTIME_COPY_ERROR = (
    "The current path is a Zermes runtime release/candidate source copy and "
    "cannot be used as the self-evolution development repository. "
    f"{INVALID_PROJECT_ROOT_HINT}"
)


class ProjectRootResolutionError(RuntimeError):
    """Raised when self-evolution cannot resolve a safe development repository."""


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


def get_evolution_workspace(
    project_root: str | Path,
    *,
    install_prefix: str | Path | None = None,
    workspace_dir: str | Path | None = None,
) -> Path:
    """Return the self-evolution audit workspace for a source repository."""
    if workspace_dir:
        return Path(workspace_dir).expanduser().resolve()
    prefix = Path(install_prefix).expanduser().resolve() if install_prefix else None
    for candidate in _installer_self_evolution_workspace_candidates(prefix):
        return candidate
    if prefix is not None:
        return prefix / "data" / EVOLUTION_WORKSPACE_NAME
    raise ProjectRootResolutionError(
        "install_prefix is required to resolve the self-evolution audit workspace."
    )


def resolve_self_evolution_project_root(
    explicit_project_root: str | Path | None = None,
    install_prefix: str | Path | None = None,
    *,
    allow_cwd: bool = True,
) -> Path:
    """Resolve and validate the editable self-evolution source repository.

    The resolver intentionally accepts only an explicit development repository,
    a valid cwd, an installer state source_repo.path, or the configured
    self_evolution.source_repo path. It never treats runtime active source
    copies as editable repositories.
    """
    prefix = Path(install_prefix).expanduser().resolve() if install_prefix else None
    errors: list[str] = []

    if explicit_project_root:
        return validate_self_evolution_project_root(explicit_project_root, install_prefix=prefix)

    if allow_cwd:
        try:
            return validate_self_evolution_project_root(Path.cwd(), install_prefix=prefix)
        except ProjectRootResolutionError as exc:
            errors.append(f"cwd: {exc}")

    for candidate in _installer_source_repo_candidates(prefix):
        try:
            return validate_self_evolution_project_root(candidate, install_prefix=prefix)
        except ProjectRootResolutionError as exc:
            errors.append(f"installer state {candidate}: {exc}")

    configured = _configured_source_repo_path()
    if configured:
        try:
            return validate_self_evolution_project_root(configured, install_prefix=prefix)
        except ProjectRootResolutionError as exc:
            errors.append(f"configured source_repo {configured}: {exc}")

    detail = f" Details: {'; '.join(errors)}" if errors else ""
    raise ProjectRootResolutionError(
        "Unable to resolve a self-evolution development source repository. "
        f"{INVALID_PROJECT_ROOT_HINT}{detail}"
    )


def validate_self_evolution_project_root(
    project_root: str | Path,
    *,
    install_prefix: str | Path | None = None,
) -> Path:
    """Validate that project_root is the editable Hermes/Zermes git root."""
    root = Path(project_root).expanduser().resolve()
    prefix = Path(install_prefix).expanduser().resolve() if install_prefix else None
    if _is_runtime_source_copy(root, prefix):
        raise ProjectRootResolutionError(RUNTIME_COPY_ERROR)
    if not root.exists():
        raise ProjectRootResolutionError(f"Project root does not exist: {root}. {INVALID_PROJECT_ROOT_HINT}")
    if not root.is_dir():
        raise ProjectRootResolutionError(f"Project root is not a directory: {root}. {INVALID_PROJECT_ROOT_HINT}")
    git_root = _git_repository_root(root)
    if git_root != root:
        raise ProjectRootResolutionError(
            f"Project root must be a git repository root: {root}. {INVALID_PROJECT_ROOT_HINT}"
        )
    missing = [path for path in _project_markers() if not (root / path).exists()]
    if missing:
        raise ProjectRootResolutionError(
            f"Project root does not look like a Hermes/Zermes source repository; "
            f"missing {', '.join(missing)}. {INVALID_PROJECT_ROOT_HINT}"
        )
    return root


def make_task_id(requirement: str, *, now: datetime | None = None) -> str:
    """Build a readable task id from a requirement and timestamp."""
    timestamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    return f"{timestamp}-{_slugify(requirement)}"


def build_development_branch_name(task_id: str) -> str:
    """Build the dedicated development branch name for one task."""
    return f"{DEFAULT_DEVELOPMENT_BRANCH_PREFIX}/{_slugify(task_id, max_length=80)}"


def build_task_record_layout(
    project_root: str | Path,
    task_id: str,
    *,
    install_prefix: str | Path | None = None,
    workspace_dir: str | Path | None = None,
) -> TaskRecordLayout:
    """Return the audit file layout for a self-evolution task.

    The function only describes paths. It does not create files or directories.
    """
    resolved_workspace_dir = get_evolution_workspace(
        project_root,
        install_prefix=install_prefix,
        workspace_dir=workspace_dir,
    )
    safe_task_id = _slugify(task_id, max_length=80)
    task_dir = resolved_workspace_dir / TASKS_DIR_NAME / safe_task_id
    temp_dir = task_dir / TEMP_DIR_NAME
    return TaskRecordLayout(
        task_id=safe_task_id,
        workspace_dir=resolved_workspace_dir,
        task_dir=task_dir,
        temp_dir=temp_dir,
        thinking_path=task_dir / AUDIT_FILE_NAMES["thinking"],
        plan_path=task_dir / AUDIT_FILE_NAMES["plan"],
        approval_path=task_dir / AUDIT_FILE_NAMES["approval"],
        change_log_path=task_dir / AUDIT_FILE_NAMES["change_log"],
        verification_path=task_dir / AUDIT_FILE_NAMES["verification"],
        final_report_path=task_dir / AUDIT_FILE_NAMES["final_report"],
    )


def _installer_source_repo_candidates(install_prefix: Path | None) -> list[Path]:
    if install_prefix is None:
        return []
    runtime_dir = install_prefix / "runtime"
    candidates: list[Path] = []
    install_state = _read_json_file(runtime_dir / "install-state.json")
    install_path = _source_repo_path_from_payload(install_state)
    if install_path:
        candidates.append(install_path)
    active_state = _read_json_file(runtime_dir / "active.json")
    active_path = _source_repo_path_from_payload(active_state)
    if active_path:
        candidates.append(active_path)
    return candidates


def _installer_self_evolution_workspace_candidates(install_prefix: Path | None) -> list[Path]:
    if install_prefix is None:
        return []
    runtime_dir = install_prefix / "runtime"
    candidates: list[Path] = []
    active_workspace = _self_evolution_workspace_from_payload(
        _read_json_file(runtime_dir / "active.json")
    )
    if active_workspace:
        candidates.append(active_workspace)
    install_workspace = _self_evolution_workspace_from_payload(
        _read_json_file(runtime_dir / "install-state.json")
    )
    if install_workspace:
        candidates.append(install_workspace)
    return candidates


def _source_repo_from_config(config: Any) -> Path | None:
    current: Any = config
    for key in PROJECT_ROOT_CONFIG_PATH:
        current = current.get(key, {}) if isinstance(current, dict) else {}
    if isinstance(current, str) and current.strip():
        return Path(current.strip())
    if isinstance(current, dict):
        path = current.get("path")
        if isinstance(path, str) and path.strip():
            return Path(path.strip())
    return None


def _configured_source_repo_path() -> Path | None:
    try:
        from hermes_cli.config import load_config

        config: Any = load_config()
    except Exception:
        config = {}
    configured = _source_repo_from_config(config)
    if configured:
        return configured

    zermes_home = os.getenv("ZERMES_HOME", "").strip()
    hermes_home = os.getenv("HERMES_HOME", "").strip()
    if zermes_home and zermes_home != hermes_home:
        try:
            import yaml

            path = Path(zermes_home) / "config.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
        except Exception:
            data = {}
        configured = _source_repo_from_config(data)
        if configured:
            return configured
    return None


def _source_repo_path_from_payload(payload: dict[str, Any] | None) -> Path | None:
    if not isinstance(payload, dict):
        return None
    source_repo = payload.get("source_repo")
    if not isinstance(source_repo, dict):
        return None
    path = source_repo.get("path")
    return Path(path) if isinstance(path, str) and path.strip() else None


def _self_evolution_workspace_from_payload(payload: dict[str, Any] | None) -> Path | None:
    if not isinstance(payload, dict):
        return None
    path = payload.get("self_evolution_data_dir")
    return Path(path).expanduser().resolve() if isinstance(path, str) and path.strip() else None


def _read_json_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _git_repository_root(path: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=path,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    output = result.stdout.strip()
    return Path(output).resolve() if output else None


def _project_markers() -> tuple[Path, ...]:
    return (
        Path("pyproject.toml"),
        Path("install.py"),
        Path("code_modification"),
        Path("tools") / "code_modification_tool.py",
    )


def _is_runtime_source_copy(root: Path, install_prefix: Path | None) -> bool:
    if install_prefix is not None and _matches_runtime_source_layout(root, install_prefix):
        return True
    metadata_path = root.parent / "metadata.json"
    metadata = _read_json_file(metadata_path)
    if metadata and root.name == "source" and root.parent.parent.name in {"releases", "candidates"}:
        return True
    return False


def _matches_runtime_source_layout(root: Path, install_prefix: Path) -> bool:
    runtime_dir = install_prefix / "runtime"
    for bucket in ("releases", "candidates"):
        try:
            relative = root.relative_to(runtime_dir / bucket)
        except ValueError:
            continue
        if len(relative.parts) == 2 and relative.parts[1] == "source":
            return True
    return False


def _slugify(value: str, *, max_length: int = 48) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        slug = "task"
    return slug[:max_length].strip("-") or "task"

"""Repository-level locks for approved self-evolution code tasks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
from typing import Any

from .git_workflow import require_git_repository
from .governance import get_evolution_workspace


REPO_LOCK_SCHEMA_VERSION = 1
LOCKS_DIR_NAME = "locks"
REPOSITORY_LOCKS_DIR_NAME = "repositories"
LOCK_HISTORY_DIR_NAME = "history"
LOCK_OPERATION = "self_evolution_code_task"


class RepoLockError(RuntimeError):
    """Raised when a self-evolution repository lock cannot be managed."""


class RepoLockConflictError(RepoLockError):
    """Raised when another task already holds the repository lock."""


@dataclass(frozen=True)
class RepoLock:
    repo_key: str
    project_root: str
    git_common_dir: str
    task_id: str
    development_branch: str
    operation: str
    created_at: str
    updated_at: str
    pid: int
    hostname: str
    holder: str
    status: str = "active"
    schema_version: int = REPO_LOCK_SCHEMA_VERSION


@dataclass(frozen=True)
class RepoLockStatus:
    locked: bool
    repo_key: str
    lock_path: str
    history_path: str
    lock: RepoLock | None
    message: str


@dataclass(frozen=True)
class RepoLockPaths:
    repo_key: str
    project_root: Path
    git_common_dir: str
    lock_path: Path
    history_path: Path


def repo_lock_status(
    project_root: str | Path,
    *,
    install_prefix: str | Path | None = None,
    workspace_dir: str | Path | None = None,
) -> RepoLockStatus:
    paths = resolve_repo_lock_paths(
        project_root,
        install_prefix=install_prefix,
        workspace_dir=workspace_dir,
    )
    lock = read_repo_lock(paths.lock_path) if paths.lock_path.exists() else None
    return RepoLockStatus(
        locked=lock is not None,
        repo_key=paths.repo_key,
        lock_path=str(paths.lock_path),
        history_path=str(paths.history_path),
        lock=lock,
        message=_status_message(paths.project_root, lock),
    )


def acquire_repo_lock(
    project_root: str | Path,
    *,
    task_id: str,
    development_branch: str,
    install_prefix: str | Path | None = None,
    workspace_dir: str | Path | None = None,
    holder: str = "start_approved_code_task",
) -> RepoLockStatus:
    clean_task_id = _require_value(task_id, "task_id")
    clean_branch = _require_value(development_branch, "development_branch")
    paths = resolve_repo_lock_paths(
        project_root,
        install_prefix=install_prefix,
        workspace_dir=workspace_dir,
    )
    paths.lock_path.parent.mkdir(parents=True, exist_ok=True)
    paths.history_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = _utc_timestamp()
    lock = RepoLock(
        repo_key=paths.repo_key,
        project_root=str(paths.project_root),
        git_common_dir=paths.git_common_dir,
        task_id=clean_task_id,
        development_branch=clean_branch,
        operation=LOCK_OPERATION,
        created_at=timestamp,
        updated_at=timestamp,
        pid=os.getpid(),
        hostname=socket.gethostname(),
        holder=str(holder or "self_evolution").strip() or "self_evolution",
    )
    payload = _lock_to_payload(lock)
    try:
        fd = os.open(str(paths.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        existing = read_repo_lock(paths.lock_path)
        if existing.task_id == clean_task_id:
            _require_matching_holder(existing, paths, clean_task_id, clean_branch)
            refreshed = heartbeat_repo_lock(
                project_root,
                task_id=clean_task_id,
                development_branch=clean_branch,
                install_prefix=install_prefix,
                workspace_dir=workspace_dir,
                holder=holder,
            )
            return refreshed
        _append_history(
            paths.history_path,
            "conflict",
            requested_task_id=clean_task_id,
            locked_by=existing.task_id,
            lock=_lock_to_payload(existing),
        )
        raise RepoLockConflictError(_lock_conflict_message(paths, existing)) from exc
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2) + "\n")
    _append_history(paths.history_path, "acquire", task_id=clean_task_id, lock=payload)
    return RepoLockStatus(
        locked=True,
        repo_key=paths.repo_key,
        lock_path=str(paths.lock_path),
        history_path=str(paths.history_path),
        lock=lock,
        message=f"repository lock acquired for task {clean_task_id}",
    )


def heartbeat_repo_lock(
    project_root: str | Path,
    *,
    task_id: str,
    development_branch: str,
    install_prefix: str | Path | None = None,
    workspace_dir: str | Path | None = None,
    holder: str = "self_evolution_repo_lock",
) -> RepoLockStatus:
    clean_task_id = _require_value(task_id, "task_id")
    clean_branch = _require_value(development_branch, "development_branch")
    paths = resolve_repo_lock_paths(
        project_root,
        install_prefix=install_prefix,
        workspace_dir=workspace_dir,
    )
    existing = read_repo_lock(paths.lock_path)
    _require_matching_holder(existing, paths, clean_task_id, clean_branch)
    refreshed = RepoLock(
        repo_key=existing.repo_key,
        project_root=existing.project_root,
        git_common_dir=existing.git_common_dir,
        task_id=existing.task_id,
        development_branch=existing.development_branch,
        operation=existing.operation,
        created_at=existing.created_at,
        updated_at=_utc_timestamp(),
        pid=existing.pid,
        hostname=existing.hostname,
        holder=str(holder or existing.holder).strip() or existing.holder,
        status=existing.status,
        schema_version=existing.schema_version,
    )
    paths.lock_path.write_text(json.dumps(_lock_to_payload(refreshed), indent=2) + "\n", encoding="utf-8")
    _append_history(paths.history_path, "heartbeat", task_id=clean_task_id, lock=_lock_to_payload(refreshed))
    return RepoLockStatus(
        locked=True,
        repo_key=paths.repo_key,
        lock_path=str(paths.lock_path),
        history_path=str(paths.history_path),
        lock=refreshed,
        message=f"repository lock heartbeat recorded for task {clean_task_id}",
    )


def require_repo_lock_holder(
    project_root: str | Path,
    *,
    task_id: str,
    development_branch: str,
    install_prefix: str | Path | None = None,
    workspace_dir: str | Path | None = None,
) -> RepoLock:
    clean_task_id = _require_value(task_id, "task_id")
    clean_branch = _require_value(development_branch, "development_branch")
    paths = resolve_repo_lock_paths(
        project_root,
        install_prefix=install_prefix,
        workspace_dir=workspace_dir,
    )
    lock = read_repo_lock(paths.lock_path)
    _require_matching_holder(lock, paths, clean_task_id, clean_branch)
    return lock


def release_repo_lock(
    project_root: str | Path,
    *,
    task_id: str,
    install_prefix: str | Path | None = None,
    workspace_dir: str | Path | None = None,
) -> RepoLockStatus:
    clean_task_id = _require_value(task_id, "task_id")
    paths = resolve_repo_lock_paths(
        project_root,
        install_prefix=install_prefix,
        workspace_dir=workspace_dir,
    )
    lock = read_repo_lock(paths.lock_path)
    _require_matching_holder(lock, paths, clean_task_id, lock.development_branch)
    payload = _lock_to_payload(lock)
    if read_repo_lock(paths.lock_path) != lock:
        raise RepoLockError("repository lock changed while releasing; retry after checking status")
    paths.lock_path.unlink()
    _append_history(paths.history_path, "release", task_id=clean_task_id, lock=payload)
    return RepoLockStatus(
        locked=False,
        repo_key=paths.repo_key,
        lock_path=str(paths.lock_path),
        history_path=str(paths.history_path),
        lock=None,
        message=f"repository lock released for task {clean_task_id}",
    )


def force_release_repo_lock(
    project_root: str | Path,
    *,
    approval_text: str,
    reason: str,
    install_prefix: str | Path | None = None,
    workspace_dir: str | Path | None = None,
) -> RepoLockStatus:
    _require_force_approval(approval_text)
    clean_reason = _require_value(reason, "reason")
    paths = resolve_repo_lock_paths(
        project_root,
        install_prefix=install_prefix,
        workspace_dir=workspace_dir,
    )
    lock = read_repo_lock(paths.lock_path)
    payload = _lock_to_payload(lock)
    paths.lock_path.unlink()
    _append_history(
        paths.history_path,
        "force_release",
        reason=clean_reason,
        approval_text=str(approval_text or "").strip(),
        lock=payload,
    )
    return RepoLockStatus(
        locked=False,
        repo_key=paths.repo_key,
        lock_path=str(paths.lock_path),
        history_path=str(paths.history_path),
        lock=None,
        message=f"repository lock force released; previous task was {lock.task_id}",
    )


def resolve_repo_lock_paths(
    project_root: str | Path,
    *,
    install_prefix: str | Path | None = None,
    workspace_dir: str | Path | None = None,
) -> RepoLockPaths:
    root = require_git_repository(project_root)
    git_common_dir = _git_common_dir(root)
    identity = _normalize_identity(git_common_dir or str(root))
    repo_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    workspace = get_evolution_workspace(
        root,
        install_prefix=install_prefix,
        workspace_dir=workspace_dir,
    )
    lock_root = workspace / LOCKS_DIR_NAME
    return RepoLockPaths(
        repo_key=repo_key,
        project_root=root,
        git_common_dir=git_common_dir,
        lock_path=lock_root / REPOSITORY_LOCKS_DIR_NAME / f"{repo_key}.lock",
        history_path=lock_root / LOCK_HISTORY_DIR_NAME / f"{repo_key}.jsonl",
    )


def read_repo_lock(path: Path) -> RepoLock:
    if not path.exists():
        raise RepoLockError(f"repository lock does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RepoLockError(f"repository lock is unreadable: {path}") from exc
    if not isinstance(payload, dict):
        raise RepoLockError(f"repository lock is invalid: {path}")
    try:
        return RepoLock(
            schema_version=int(payload.get("schema_version", REPO_LOCK_SCHEMA_VERSION)),
            repo_key=str(payload.get("repo_key") or ""),
            project_root=str(payload.get("project_root") or ""),
            git_common_dir=str(payload.get("git_common_dir") or ""),
            task_id=str(payload.get("task_id") or ""),
            development_branch=str(payload.get("development_branch") or ""),
            operation=str(payload.get("operation") or ""),
            created_at=str(payload.get("created_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
            pid=int(payload.get("pid") or 0),
            hostname=str(payload.get("hostname") or ""),
            holder=str(payload.get("holder") or ""),
            status=str(payload.get("status") or "active"),
        )
    except (TypeError, ValueError) as exc:
        raise RepoLockError(f"repository lock is invalid: {path}") from exc


def repo_lock_status_to_dict(status: RepoLockStatus) -> dict[str, Any]:
    return {
        "locked": status.locked,
        "repo_key": status.repo_key,
        "lock_path": status.lock_path,
        "history_path": status.history_path,
        "lock": _lock_to_payload(status.lock) if status.lock else None,
        "message": status.message,
    }


def _git_common_dir(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    output = result.stdout.strip()
    return str(Path(output).resolve()) if output else ""


def _normalize_identity(value: str) -> str:
    resolved = str(Path(value).expanduser().resolve())
    return os.path.normcase(resolved)


def _lock_to_payload(lock: RepoLock | None) -> dict[str, Any] | None:
    return asdict(lock) if lock else None


def _require_matching_holder(
    lock: RepoLock,
    paths: RepoLockPaths,
    task_id: str,
    development_branch: str,
) -> None:
    if lock.repo_key != paths.repo_key or _normalize_identity(lock.project_root) != _normalize_identity(str(paths.project_root)):
        raise RepoLockError(
            "repository lock does not match the requested repository "
            f"(lock_path={paths.lock_path})"
        )
    if lock.git_common_dir and paths.git_common_dir and _normalize_identity(lock.git_common_dir) != _normalize_identity(paths.git_common_dir):
        raise RepoLockError(
            "repository lock git common dir does not match the requested repository "
            f"(lock_path={paths.lock_path})"
        )
    if lock.task_id != task_id:
        raise RepoLockConflictError(_lock_conflict_message(paths, lock))
    if lock.development_branch != development_branch:
        raise RepoLockError(
            "repository lock development branch mismatch "
            f"(expected={development_branch}, locked={lock.development_branch})"
        )
    if lock.operation != LOCK_OPERATION or lock.status != "active":
        raise RepoLockError(f"repository lock is not an active self-evolution lock: {paths.lock_path}")


def _lock_conflict_message(paths: RepoLockPaths, lock: RepoLock) -> str:
    return (
        "current source repository is already locked for self-evolution: "
        f"project_root={paths.project_root}; locked_by_task={lock.task_id}; "
        f"development_branch={lock.development_branch}; created_at={lock.created_at}; "
        f"updated_at={lock.updated_at}; lock_path={paths.lock_path}. "
        "finish or release the current task before starting another self-evolution task"
    )


def _status_message(project_root: Path, lock: RepoLock | None) -> str:
    if lock is None:
        return f"repository is not locked for self-evolution: {project_root}"
    return (
        f"repository is locked for self-evolution by task {lock.task_id} "
        f"on branch {lock.development_branch}"
    )


def _append_history(path: Path, event: str, **fields: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "event": event,
        "timestamp": _utc_timestamp(),
        **fields,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def _require_value(value: str, name: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        raise RepoLockError(f"{name} is required")
    return clean


def _require_force_approval(approval_text: str) -> None:
    normalized = str(approval_text or "").strip().lower()
    if "force" not in normalized or "approve" not in normalized:
        raise RepoLockError("explicit force release approval is required")


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat()

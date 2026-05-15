"""Runtime release state for governed self-update application.

This module is intentionally a narrow state-management layer. It knows how to
read and atomically switch the installer runtime pointers under
``<prefix>/runtime``; it does not copy source code, create virtual
environments, install dependencies, run verification commands, or restart
processes. Those actions belong to later, explicitly allow-listed steps.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
from typing import Any

from .git_workflow import GitWorkflowError, require_git_repository, run_git


RUNTIME_DIR_NAME = "runtime"
ACTIVE_STATE_FILE = "active.json"
PREVIOUS_STATE_FILE = "previous.json"
UPDATE_STATE_FILE = "update-state.json"
CANDIDATES_DIR_NAME = "candidates"
RELEASES_DIR_NAME = "releases"
RUNTIME_SCHEMA_VERSION = 1


class RuntimeUpdateError(RuntimeError):
    """Raised when runtime version state cannot be read or safely changed."""


@dataclass(frozen=True)
class RuntimePaths:
    """Resolved paths owned by one Zermes installation prefix."""

    prefix: Path
    runtime_dir: Path
    active_path: Path
    previous_path: Path
    update_state_path: Path
    candidates_dir: Path
    releases_dir: Path


@dataclass(frozen=True)
class RuntimeRelease:
    """A release that can be selected by ``runtime/active.json``.

    ``source_repo`` is the editable development repository that produced this
    release. It is not the same path as ``source_path`` when Zermes is installed
    into an isolated runtime prefix.
    """

    release_id: str
    source_path: str
    venv_path: str
    build_path: str
    candidate_commit: str
    source_repo: str = ""
    activated_at: str = ""
    schema_version: int = RUNTIME_SCHEMA_VERSION


@dataclass(frozen=True)
class RuntimeCandidate:
    """A candidate runtime tree created from a specific source commit."""

    candidate_id: str
    source_path: str
    venv_path: str
    build_path: str
    logs_path: str
    candidate_commit: str
    source_repo: str
    task_id: str = ""
    created_at: str = ""
    schema_version: int = RUNTIME_SCHEMA_VERSION


@dataclass(frozen=True)
class RuntimeUpdateState:
    """Machine-readable progress for the latest runtime update attempt."""

    status: str
    task_id: str = ""
    candidate_id: str = ""
    release_id: str = ""
    source_repo: str = ""
    candidate_commit: str = ""
    old_release_id: str = ""
    steps: tuple[str, ...] = ()
    health_checks: tuple[str, ...] = ()
    error: str = ""
    schema_version: int = RUNTIME_SCHEMA_VERSION
    updated_at: str = ""


def resolve_runtime_paths(prefix: str | Path) -> RuntimePaths:
    """Return normalized runtime paths for an installation prefix."""
    resolved_prefix = Path(prefix).expanduser().resolve()
    runtime_dir = resolved_prefix / RUNTIME_DIR_NAME
    return RuntimePaths(
        prefix=resolved_prefix,
        runtime_dir=runtime_dir,
        active_path=runtime_dir / ACTIVE_STATE_FILE,
        previous_path=runtime_dir / PREVIOUS_STATE_FILE,
        update_state_path=runtime_dir / UPDATE_STATE_FILE,
        candidates_dir=runtime_dir / CANDIDATES_DIR_NAME,
        releases_dir=runtime_dir / RELEASES_DIR_NAME,
    )


def read_active_release(prefix: str | Path) -> RuntimeRelease:
    """Read and validate the active runtime release."""
    paths = resolve_runtime_paths(prefix)
    release = _read_release(paths.active_path)
    validate_release_directory(paths, release)
    return release


def read_previous_release(prefix: str | Path) -> RuntimeRelease | None:
    """Read the previous runtime release if rollback metadata exists."""
    paths = resolve_runtime_paths(prefix)
    if not paths.previous_path.exists():
        return None
    release = _read_release(paths.previous_path)
    validate_release_directory(paths, release)
    return release


def read_release(prefix: str | Path, release_id: str) -> RuntimeRelease:
    """Read and validate a release by id from runtime/releases."""
    paths = resolve_runtime_paths(prefix)
    clean_release = _safe_id(release_id, "release")
    release_root = _release_root(paths, clean_release)
    release = _read_release(release_root / "metadata.json")
    if release.release_id != clean_release:
        raise RuntimeUpdateError("release metadata id does not match requested release")
    validate_release_directory(paths, release)
    return release


def write_runtime_update_state(prefix: str | Path, state: RuntimeUpdateState) -> None:
    """Atomically write the latest runtime update state."""
    paths = resolve_runtime_paths(prefix)
    updated = RuntimeUpdateState(
        status=state.status,
        task_id=state.task_id,
        candidate_id=state.candidate_id,
        release_id=state.release_id,
        source_repo=state.source_repo,
        candidate_commit=state.candidate_commit,
        old_release_id=state.old_release_id,
        steps=state.steps,
        health_checks=state.health_checks,
        error=state.error,
        schema_version=state.schema_version,
        updated_at=state.updated_at or _utc_timestamp(),
    )
    _atomic_write_json(paths.update_state_path, _state_to_payload(updated))


def generate_candidate_id(now: datetime | None, commit: str) -> str:
    """Generate a stable candidate id from a timestamp and commit."""
    timestamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    short_commit = _short_commit(commit)
    return f"update-{timestamp}-{short_commit}" if short_commit else f"update-{timestamp}"


def generate_release_id(candidate_id: str, commit: str) -> str:
    """Generate a release id derived from a candidate id and commit."""
    clean_candidate = _safe_id(candidate_id, "release")
    short_commit = _short_commit(commit)
    if short_commit and not clean_candidate.endswith(short_commit):
        return f"{clean_candidate}-{short_commit}"
    return clean_candidate


def prepare_candidate_source(
    prefix: str | Path,
    candidate_id: str,
    *,
    source_repo: str | Path,
    git_ref: str,
    task_id: str = "",
    old_release_id: str = "",
) -> RuntimeCandidate:
    """Create a candidate runtime source tree from a Git commit.

    This is the first real runtime-update step after the audit plan. It copies
    only Git-tracked files from the editable development repository into
    ``runtime/candidates/<candidate-id>/source``. It deliberately does not
    install dependencies or run verification; later allow-listed steps own that
    work.
    """
    paths = resolve_runtime_paths(prefix)
    clean_candidate = _safe_id(candidate_id, "candidate")
    candidate_root = _candidate_root(paths, clean_candidate)
    if candidate_root.exists():
        raise RuntimeUpdateError(f"candidate already exists: {candidate_root}")
    try:
        repo_root = require_git_repository(source_repo)
        candidate_commit = run_git(repo_root, "rev-parse", str(git_ref).strip()).stdout.strip()
    except GitWorkflowError as exc:
        raise RuntimeUpdateError(str(exc)) from exc
    candidate = RuntimeCandidate(
        candidate_id=clean_candidate,
        source_path=str(candidate_root / "source"),
        venv_path=str(candidate_root / "venv"),
        build_path=str(candidate_root / "build"),
        logs_path=str(candidate_root / "logs"),
        candidate_commit=candidate_commit,
        source_repo=str(repo_root),
        task_id=str(task_id or "").strip(),
        created_at=_utc_timestamp(),
    )
    try:
        _create_candidate_directories(candidate_root)
        _extract_git_archive(repo_root, candidate_commit, Path(candidate.source_path))
        _atomic_write_json(candidate_root / "metadata.json", _candidate_to_payload(candidate))
        state = RuntimeUpdateState(
            status="source_synced",
            task_id=candidate.task_id,
            candidate_id=candidate.candidate_id,
            source_repo=candidate.source_repo,
            candidate_commit=candidate.candidate_commit,
            old_release_id=str(old_release_id or "").strip(),
            steps=("source_synced",),
        )
        _atomic_write_json(candidate_root / UPDATE_STATE_FILE, _state_to_payload(state))
        write_runtime_update_state(paths.prefix, state)
    except Exception as exc:
        if isinstance(exc, RuntimeUpdateError):
            raise
        raise RuntimeUpdateError(f"candidate source preparation failed: {exc}") from exc
    return candidate


def mark_candidate_verified(
    prefix: str | Path,
    candidate_id: str,
    *,
    health_checks: list[str],
) -> RuntimeUpdateState:
    """Mark a prepared candidate as verified.

    The caller must provide the health-check evidence gathered by a separate
    allow-listed runner. This function only records that evidence and advances
    the candidate state so promotion can happen later.
    """
    checks = _clean_health_checks(health_checks)
    if not checks:
        raise RuntimeUpdateError("at least one health check is required")
    return _write_candidate_status(
        prefix,
        candidate_id,
        status="verified",
        health_checks=checks,
        error="",
    )


def mark_candidate_blocked(
    prefix: str | Path,
    candidate_id: str,
    *,
    reason: str,
    health_checks: list[str] | None = None,
) -> RuntimeUpdateState:
    """Record that a candidate cannot be promoted.

    Blocking a candidate is also a state transition: active.json is not touched,
    but both candidate-local and runtime-level update-state files explain why
    the update stopped.
    """
    clean_reason = str(reason or "").strip()
    if not clean_reason:
        raise RuntimeUpdateError("blocked reason is required")
    return _write_candidate_status(
        prefix,
        candidate_id,
        status="blocked",
        health_checks=_clean_health_checks(health_checks or []),
        error=clean_reason,
    )


def validate_release_directory(paths: RuntimePaths, release: RuntimeRelease) -> None:
    """Validate that a release points to complete paths inside releases/.

    Runtime switching must never select arbitrary paths. The active release is
    only valid when its source, venv, and build paths remain inside the
    installation prefix's ``runtime/releases/<release-id>/`` directory.
    """
    release_root = _release_root(paths, release.release_id)
    source_path = _required_child_path(release.source_path, release_root, "source_path")
    venv_path = _required_child_path(release.venv_path, release_root, "venv_path")
    build_path = _required_child_path(release.build_path, release_root, "build_path")
    metadata_path = release_root / "metadata.json"
    missing = [
        str(path)
        for path in (source_path, venv_path, build_path, metadata_path)
        if not path.exists()
    ]
    if missing:
        raise RuntimeUpdateError(f"release {release.release_id} is incomplete: {', '.join(missing)}")
    non_directories = [
        str(path)
        for path in (source_path, venv_path, build_path)
        if not path.is_dir()
    ]
    if non_directories:
        raise RuntimeUpdateError(
            f"release {release.release_id} paths must be directories: {', '.join(non_directories)}"
        )


def promote_candidate_to_release(
    prefix: str | Path,
    candidate_id: str,
    release_id: str,
) -> RuntimeRelease:
    """Promote a prepared candidate directory into releases/.

    The function performs only a local directory move and metadata read. It
    assumes earlier steps have already created and verified the candidate.
    """
    paths = resolve_runtime_paths(prefix)
    clean_candidate = _safe_id(candidate_id, "candidate")
    clean_release = _safe_id(release_id, "release")
    candidate_root = _candidate_root(paths, clean_candidate)
    release_root = _release_root(paths, clean_release)
    if not candidate_root.exists():
        raise RuntimeUpdateError(f"candidate does not exist: {candidate_root}")
    if release_root.exists():
        raise RuntimeUpdateError(f"release already exists: {release_root}")
    _require_verified_candidate(candidate_root)
    metadata = _read_json(candidate_root / "metadata.json")
    candidate_commit = str(metadata.get("candidate_commit") or metadata.get("commit") or "").strip()
    source_repo = _source_repo_from_payload(metadata)
    release_root.parent.mkdir(parents=True, exist_ok=True)
    candidate_root.replace(release_root)
    release = RuntimeRelease(
        release_id=clean_release,
        source_path=str(release_root / "source"),
        venv_path=str(release_root / "venv"),
        build_path=str(release_root / "build"),
        candidate_commit=candidate_commit,
        source_repo=source_repo,
        activated_at="",
    )
    validate_release_directory(paths, release)
    _atomic_write_json(release_root / "metadata.json", _release_to_payload(release))
    return release


def activate_release(
    prefix: str | Path,
    release: RuntimeRelease,
    *,
    expected_old_release_id: str | None = None,
) -> RuntimeRelease:
    """Atomically switch active.json to a validated release.

    ``expected_old_release_id`` is a lightweight compare-and-swap guard. It
    prevents one update process from replacing another process's newer active
    release after planning against stale state.
    """
    paths = resolve_runtime_paths(prefix)
    validate_release_directory(paths, release)
    current = _read_release(paths.active_path) if paths.active_path.exists() else None
    if expected_old_release_id and (
        current is None or current.release_id != expected_old_release_id
    ):
        raise RuntimeUpdateError("active release changed since the update was planned")
    if current is not None:
        _atomic_write_json(paths.previous_path, _release_to_payload(current))
    activated = RuntimeRelease(
        release_id=release.release_id,
        source_path=release.source_path,
        venv_path=release.venv_path,
        build_path=release.build_path,
        candidate_commit=release.candidate_commit,
        source_repo=release.source_repo,
        activated_at=_utc_timestamp(),
        schema_version=release.schema_version,
    )
    _atomic_write_json(paths.active_path, _release_to_payload(activated))
    return activated


def rollback_active_release(prefix: str | Path) -> RuntimeRelease:
    """Restore previous.json into active.json without deleting any release."""
    paths = resolve_runtime_paths(prefix)
    if not paths.previous_path.exists():
        raise RuntimeUpdateError("previous release metadata is missing")
    current = _read_release(paths.active_path) if paths.active_path.exists() else None
    previous = _read_release(paths.previous_path)
    validate_release_directory(paths, previous)
    if current is not None:
        _atomic_write_json(paths.previous_path, _release_to_payload(current))
    _atomic_write_json(paths.active_path, _release_to_payload(previous))
    return previous


def _read_release(path: Path) -> RuntimeRelease:
    payload = _read_json(path)
    release_id = str(payload.get("release_id") or "").strip()
    if not release_id:
        raise RuntimeUpdateError(f"release_id is missing from {path}")
    return RuntimeRelease(
        release_id=_safe_id(release_id, "release"),
        source_path=str(payload.get("source_path") or ""),
        venv_path=str(payload.get("venv_path") or ""),
        build_path=str(payload.get("build_path") or ""),
        candidate_commit=str(payload.get("candidate_commit") or payload.get("commit") or "").strip(),
        source_repo=_source_repo_from_payload(payload),
        activated_at=str(payload.get("activated_at") or ""),
        schema_version=int(payload.get("schema_version") or RUNTIME_SCHEMA_VERSION),
    )


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeUpdateError(f"JSON file does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeUpdateError(f"JSON file is unreadable: {path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeUpdateError(f"JSON file must contain an object: {path}")
    return payload


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)


def _release_to_payload(release: RuntimeRelease) -> dict[str, Any]:
    payload = asdict(release)
    payload["source_repo"] = {"path": release.source_repo} if release.source_repo else {}
    return payload


def _candidate_to_payload(candidate: RuntimeCandidate) -> dict[str, Any]:
    payload = asdict(candidate)
    payload["source_repo"] = {"path": candidate.source_repo}
    return payload


def _state_to_payload(state: RuntimeUpdateState) -> dict[str, Any]:
    payload = asdict(state)
    payload["steps"] = list(state.steps)
    payload["health_checks"] = list(state.health_checks)
    return payload


def _source_repo_from_payload(payload: dict[str, Any]) -> str:
    source_repo = payload.get("source_repo")
    if isinstance(source_repo, str):
        return source_repo.strip()
    if isinstance(source_repo, dict):
        path = source_repo.get("path")
        return str(path).strip() if path else ""
    return ""


def _create_candidate_directories(candidate_root: Path) -> None:
    # The directory names are stable because later build and promote steps will
    # rely on this layout rather than rediscovering paths from arbitrary input.
    for name in ("source", "venv", "build", "logs"):
        (candidate_root / name).mkdir(parents=True, exist_ok=False)


def _require_verified_candidate(candidate_root: Path) -> None:
    state = _read_json(candidate_root / UPDATE_STATE_FILE)
    if state.get("status") != "verified":
        raise RuntimeUpdateError("candidate must be verified before promotion")


def _extract_git_archive(repo_root: Path, commit: str, destination: Path) -> None:
    result = subprocess.run(
        ["git", "archive", "--format=tar", commit],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or b"git archive failed").decode(
            errors="replace"
        ).strip()
        raise RuntimeUpdateError(message)
    with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:") as archive:
        for member in archive.getmembers():
            target = _archive_member_target(destination, member)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise RuntimeUpdateError(f"archive member is unreadable: {member.name}")
                target.write_bytes(source.read())
                continue
            # Symlinks, hardlinks, devices, and other special entries are not
            # needed for the current Python source runtime and are risky to
            # recreate inside an installation prefix without a dedicated policy.
            raise RuntimeUpdateError(f"unsupported archive member type: {member.name}")


def _archive_member_target(destination: Path, member: tarfile.TarInfo) -> Path:
    name = str(member.name or "")
    if not name or name.startswith("/") or "\\" in name:
        raise RuntimeUpdateError(f"unsafe archive member path: {name}")
    target = (destination / name).resolve()
    try:
        target.relative_to(destination.resolve())
    except ValueError as exc:
        raise RuntimeUpdateError(f"archive member escapes destination: {name}") from exc
    return target


def _candidate_root(paths: RuntimePaths, candidate_id: str) -> Path:
    return _runtime_child(paths, paths.candidates_dir / candidate_id)


def _release_root(paths: RuntimePaths, release_id: str) -> Path:
    return _runtime_child(paths, paths.releases_dir / release_id)


def _write_candidate_status(
    prefix: str | Path,
    candidate_id: str,
    *,
    status: str,
    health_checks: tuple[str, ...],
    error: str,
) -> RuntimeUpdateState:
    paths = resolve_runtime_paths(prefix)
    candidate_root = _candidate_root(paths, _safe_id(candidate_id, "candidate"))
    if not candidate_root.exists():
        raise RuntimeUpdateError(f"candidate does not exist: {candidate_root}")
    metadata = _read_json(candidate_root / "metadata.json")
    previous_state = _read_json(candidate_root / UPDATE_STATE_FILE)
    previous_status = str(previous_state.get("status") or "").strip()
    if previous_status not in {"source_synced", "blocked", "verified"}:
        raise RuntimeUpdateError(f"candidate cannot be marked from status {previous_status or 'unknown'}")
    steps = _append_step(tuple(previous_state.get("steps") or ()), status)
    state = RuntimeUpdateState(
        status=status,
        task_id=str(previous_state.get("task_id") or metadata.get("task_id") or "").strip(),
        candidate_id=_safe_id(candidate_id, "candidate"),
        release_id=str(previous_state.get("release_id") or "").strip(),
        source_repo=_source_repo_from_payload(metadata),
        candidate_commit=str(metadata.get("candidate_commit") or metadata.get("commit") or "").strip(),
        old_release_id=str(previous_state.get("old_release_id") or "").strip(),
        steps=steps,
        health_checks=health_checks,
        error=error,
    )
    _atomic_write_json(candidate_root / UPDATE_STATE_FILE, _state_to_payload(state))
    write_runtime_update_state(paths.prefix, state)
    return state


def _clean_health_checks(health_checks: list[str]) -> tuple[str, ...]:
    return tuple(str(check).strip() for check in health_checks if str(check).strip())


def _append_step(steps: tuple[str, ...], step: str) -> tuple[str, ...]:
    clean_steps = tuple(str(item).strip() for item in steps if str(item).strip())
    return clean_steps if clean_steps and clean_steps[-1] == step else (*clean_steps, step)


def _required_child_path(value: str, parent: Path, field_name: str) -> Path:
    if not str(value or "").strip():
        raise RuntimeUpdateError(f"{field_name} is missing")
    path = Path(value).expanduser().resolve()
    try:
        path.relative_to(parent)
    except ValueError as exc:
        raise RuntimeUpdateError(f"{field_name} must stay inside {parent}") from exc
    return path


def _runtime_child(paths: RuntimePaths, path: Path) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(paths.runtime_dir)
    except ValueError as exc:
        raise RuntimeUpdateError(f"path escapes runtime directory: {resolved}") from exc
    return resolved


def _short_commit(commit: str) -> str:
    clean_commit = re.sub(r"[^0-9a-fA-F]", "", str(commit or ""))
    return clean_commit[:7].lower()


def _safe_id(value: str, fallback: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "")).strip(".-_")
    return safe or fallback


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat()

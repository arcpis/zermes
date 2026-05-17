"""Source installer implementation for Zermes.

The installer owns the stable runtime directory model for source-based Zermes
installs. It keeps install, update, and rollback concerns explicit so a random
checkout is never silently applied to a long-running runtime.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile


EXCLUDED_SOURCE_DIR_NAMES = frozenset(
    {
        ".git",
        ".hermes-analysis-cache",
        ".pytest_cache",
        ".venv",
        "__pycache__",
        "node_modules",
        "temp_vision_images",
        "venv",
    }
)

@dataclass(frozen=True)
class InstallerPlan:
    """Dry-run description of a future source installation."""

    repo_root: str
    prefix: str
    data_dir: str
    install_data_dir: str
    self_evolution_data_dir: str
    release_id: str
    runtime_dir: str
    release_dir: str
    source_dir: str
    venv_dir: str
    build_dir: str
    bin_dir: str
    python_path: str
    use_venv: bool
    active_path: str
    previous_path: str
    dry_run: bool


@dataclass(frozen=True)
class CommandResult:
    """Result from an installer-managed command."""

    command: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""
    dry_run: bool = False


@dataclass(frozen=True)
class GlobalCommandResult:
    """Result from making the zermes command visible on PATH."""

    status: str
    method: str
    path: str | None
    message: str


@dataclass(frozen=True)
class UpdateSource:
    """Resolved source checkout for an update candidate."""

    kind: str
    path: str
    active_release_id: str | None = None
    active_source_path: str | None = None


@dataclass(frozen=True)
class UpdateCandidateState:
    """Durable status record for a single update candidate."""

    mode: str
    candidate_id: str
    source_kind: str
    source_path: str
    old_release_id: str | None
    new_release_id: str
    status: str
    activated: bool
    restart_requested: bool
    error: str | None


class InstallerCommandError(RuntimeError):
    """Raised when an installer command fails."""

    def __init__(self, result: CommandResult):
        command_text = " ".join(result.command)
        super().__init__(f"installer command failed ({result.returncode}): {command_text}")
        self.result = result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="install.py",
        description="Install, update, or roll back Zermes from a source checkout.",
    )
    _add_install_options(parser)
    subparsers = parser.add_subparsers(dest="command")
    install_parser = subparsers.add_parser(
        "install",
        help="Install Zermes from this source checkout.",
        description="Install Zermes from this source checkout.",
    )
    _add_install_options(install_parser)
    update_parser = subparsers.add_parser(
        "update",
        help="Build an update candidate from an explicit source checkout.",
        description="Build an update candidate from an explicit source checkout.",
    )
    _add_update_options(update_parser)
    rollback_parser = subparsers.add_parser(
        "rollback",
        help="Point active.json back to the previous release.",
        description="Point active.json back to the previous release.",
    )
    rollback_parser.add_argument(
        "--prefix",
        type=Path,
        default=None,
        help="Software installation directory.",
    )
    rollback_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print rollback intent without writing files.",
    )
    uninstall_parser = subparsers.add_parser(
        "uninstall",
        help="Remove an installed Zermes runtime.",
        description="Remove an installed Zermes runtime while preserving user data by default.",
    )
    uninstall_parser.add_argument(
        "--prefix",
        type=Path,
        default=None,
        help="Software installation directory.",
    )
    uninstall_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print uninstall intent without deleting files.",
    )
    uninstall_parser.add_argument(
        "--remove-data",
        action="store_true",
        help="Also remove the data directory recorded in active.json.",
    )
    uninstall_parser.add_argument(
        "--remove-global-command",
        action="store_true",
        help="Remove the user-level global zermes command created by the installer.",
    )
    uninstall_parser.add_argument(
        "--global-bin-dir",
        type=Path,
        default=None,
        help="User-level directory used for the global zermes command.",
    )
    return parser


def _add_install_options(parser: argparse.ArgumentParser) -> None:
    """Add options shared by the install command and the legacy root form."""

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the installation plan without writing files.",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Use defaults for missing options instead of prompting.",
    )
    parser.add_argument(
        "--prefix",
        type=Path,
        default=None,
        help="Software installation directory.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="User configuration and data directory.",
    )
    parser.add_argument(
        "--release-id",
        default="source-install",
        help="Initial release identifier.",
    )
    parser.add_argument(
        "--python",
        type=Path,
        default=None,
        help="Python executable to use for creating the release virtual environment.",
    )
    parser.add_argument(
        "--no-venv",
        action="store_true",
        help="Skip virtual environment creation and use the selected Python directly.",
    )
    deps_group = parser.add_mutually_exclusive_group()
    deps_group.add_argument(
        "--install-deps",
        dest="install_deps",
        action="store_true",
        default=True,
        help="Install Python dependencies into the release environment.",
    )
    deps_group.add_argument(
        "--no-install-deps",
        dest="install_deps",
        action="store_false",
        help="Skip Python dependency installation.",
    )
    launchers_group = parser.add_mutually_exclusive_group()
    launchers_group.add_argument(
        "--create-launchers",
        dest="create_launchers",
        action="store_true",
        default=True,
        help="Create command-line launcher scripts.",
    )
    launchers_group.add_argument(
        "--no-create-launchers",
        dest="create_launchers",
        action="store_false",
        help="Skip command-line launcher script creation.",
    )
    global_group = parser.add_mutually_exclusive_group()
    global_group.add_argument(
        "--global-command",
        dest="global_command",
        action="store_true",
        default=None,
        help="Configure the current user environment so zermes is available from any directory.",
    )
    global_group.add_argument(
        "--no-global-command",
        dest="global_command",
        action="store_false",
        help="Do not configure a global zermes command.",
    )
    parser.add_argument(
        "--global-bin-dir",
        type=Path,
        default=None,
        help="User-level directory used for the global zermes command.",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip post-install runtime verification.",
    )


def _add_update_options(parser: argparse.ArgumentParser) -> None:
    """Add update command options before the update executor exists."""

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the update plan without writing files.",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Fail instead of prompting when update source details are missing.",
    )
    parser.add_argument(
        "--prefix",
        type=Path,
        default=None,
        help="Software installation directory.",
    )
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument(
        "--source",
        type=Path,
        default=None,
        help="Source checkout to build as an update candidate.",
    )
    source_group.add_argument(
        "--current-source",
        action="store_true",
        help="Use the source checkout containing this installer.",
    )
    parser.add_argument(
        "--release-id",
        default=None,
        help="Release identifier for the update candidate.",
    )
    deps_group = parser.add_mutually_exclusive_group()
    deps_group.add_argument(
        "--install-deps",
        dest="install_deps",
        action="store_true",
        default=True,
        help="Install Python dependencies into the candidate environment.",
    )
    deps_group.add_argument(
        "--no-install-deps",
        dest="install_deps",
        action="store_false",
        help="Skip Python dependency installation for the candidate.",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip candidate runtime verification.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow explicitly guarded update operations.",
    )
    activate_group = parser.add_mutually_exclusive_group()
    activate_group.add_argument(
        "--activate",
        dest="activate",
        action="store_true",
        default=True,
        help="Activate the candidate after verification.",
    )
    activate_group.add_argument(
        "--no-activate",
        dest="activate",
        action="store_false",
        help="Build and verify the candidate without changing active.json.",
    )
    restart_group = parser.add_mutually_exclusive_group()
    restart_group.add_argument(
        "--restart",
        dest="restart",
        action="store_true",
        default=False,
        help="Request a controlled restart after activation.",
    )
    restart_group.add_argument(
        "--no-restart",
        dest="restart",
        action="store_false",
        help="Do not request a restart after activation.",
    )


def default_prefix(*, platform: str | None = None, home: Path | None = None) -> Path:
    platform_name = platform or sys.platform
    home_dir = home or Path.home()
    if platform_name == "win32":
        base = home_dir / "AppData" / "Local"
        return base / "Zermes"
    if platform_name == "darwin":
        return home_dir / "Applications" / "Zermes"
    return home_dir / ".local" / "share" / "zermes"


def default_data_dir(*, home: Path | None = None) -> Path:
    return (home or Path.home()) / ".hermes"


def active_metadata_path(prefix: Path) -> Path:
    """Return the active release pointer for a software prefix."""

    return prefix.expanduser().resolve() / "runtime" / "active.json"


def runtime_update_state_path(prefix: Path) -> Path:
    """Return the runtime-level update status file for a software prefix."""

    return prefix.expanduser().resolve() / "runtime" / "update-state.json"


def rollback_state_path(prefix: Path) -> Path:
    """Return the rollback audit state path for a software prefix."""

    return prefix.expanduser().resolve() / "runtime" / "rollback-state.json"


def uninstall_state_path(prefix: Path) -> Path:
    """Return the uninstall audit state path for a software prefix."""

    return prefix.expanduser().resolve() / "runtime" / "uninstall-state.json"


def read_active_metadata(prefix: Path) -> dict | None:
    """Read active release metadata when an installed runtime exists."""

    path = active_metadata_path(prefix)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def rollback_release(prefix: Path, *, dry_run: bool = False) -> dict:
    """Point active.json back to previous.json without deleting releases."""

    resolved_prefix = prefix.expanduser().resolve()
    active_path = active_metadata_path(resolved_prefix)
    previous_path = resolved_prefix / "runtime" / "previous.json"
    if not previous_path.exists():
        raise ValueError("cannot rollback because previous.json does not exist")
    previous_payload = json.loads(previous_path.read_text(encoding="utf-8"))
    current_payload = (
        json.loads(active_path.read_text(encoding="utf-8"))
        if active_path.exists()
        else None
    )
    state = {
        "mode": "rollback",
        "status": "rolled-back",
        "rolled_back_from": current_payload,
        "rolled_back_to": previous_payload,
        "restart_required": True,
    }
    if dry_run:
        return state
    atomic_write_json(rollback_state_path(resolved_prefix), state)
    atomic_write_json(active_path, previous_payload)
    return state


def _remove_path_entry(path_value: str, directory: Path, *, platform: str) -> str:
    separator = ";" if platform == "windows" else os.pathsep
    target = os.path.normcase(os.path.normpath(str(directory.expanduser())))
    if platform == "windows":
        target = target.lower()
    kept: list[str] = []
    for entry in path_value.split(separator):
        if not entry:
            continue
        candidate = os.path.normcase(os.path.normpath(str(Path(entry).expanduser())))
        if platform == "windows":
            candidate = candidate.lower()
        if candidate != target:
            kept.append(entry)
    return separator.join(kept)


def remove_global_command(
    prefix: Path,
    *,
    global_bin_dir: Path | None = None,
    platform: str | None = None,
    env_path: str | None = None,
    dry_run: bool = False,
    windows_path_writer=None,
) -> GlobalCommandResult:
    """Remove user-level global command configuration owned by this installer."""

    resolved_prefix = prefix.expanduser().resolve()
    current_platform = platform or ("windows" if os.name == "nt" else "posix")
    if current_platform == "windows":
        path_dir = (global_bin_dir or (resolved_prefix / "bin")).expanduser()
        current_path = read_user_windows_path() if env_path is None else env_path
        if not _path_contains(path_dir, current_path, platform="windows"):
            return GlobalCommandResult(
                status="skipped",
                method="user-path",
                path=str(path_dir),
                message="The zermes launcher directory was not present on the user PATH.",
            )
        new_path = _remove_path_entry(current_path, path_dir, platform="windows")
        if not dry_run:
            if windows_path_writer is None:
                windows_path_writer = write_user_windows_path
            windows_path_writer(new_path)
        return GlobalCommandResult(
            status="removed",
            method="user-path",
            path=str(path_dir),
            message="Removed the zermes launcher directory from the user PATH.",
        )

    path_dir = (global_bin_dir or (Path.home() / ".local" / "bin")).expanduser()
    link_path = path_dir / "zermes"
    expected_launcher = resolved_prefix / "bin" / "zermes"
    if not link_path.is_symlink():
        return GlobalCommandResult(
            status="skipped",
            method="symlink",
            path=str(link_path),
            message="No installer-owned zermes symlink was found.",
        )
    try:
        target = link_path.resolve(strict=False)
    except OSError:
        target = Path(os.readlink(link_path))
        if not target.is_absolute():
            target = (link_path.parent / target).resolve(strict=False)
    if target != expected_launcher:
        return GlobalCommandResult(
            status="skipped",
            method="symlink",
            path=str(link_path),
            message="Existing zermes symlink points outside this installation.",
        )
    if not dry_run:
        link_path.unlink()
    return GlobalCommandResult(
        status="removed",
        method="symlink",
        path=str(link_path),
        message="Removed the user-level zermes symlink.",
    )


def uninstall_runtime(
    prefix: Path,
    *,
    remove_data: bool = False,
    remove_global: bool = False,
    global_bin_dir: Path | None = None,
    dry_run: bool = False,
) -> dict:
    """Remove an installed runtime while preserving user data by default."""

    resolved_prefix = prefix.expanduser().resolve()
    active_metadata = read_active_metadata(resolved_prefix)
    if active_metadata is None:
        raise ValueError(f"cannot uninstall because active.json does not exist under {resolved_prefix}")
    data_dir_value = active_metadata.get("data_dir")
    data_dir = Path(data_dir_value).expanduser().resolve() if data_dir_value else None
    global_command = (
        remove_global_command(
            resolved_prefix,
            global_bin_dir=global_bin_dir,
            dry_run=dry_run,
        )
        if remove_global
        else GlobalCommandResult(
            status="skipped",
            method="none",
            path=None,
            message="Global zermes command removal was not requested.",
        )
    )
    state = {
        "mode": "uninstall",
        "status": "uninstalled",
        "install_prefix": str(resolved_prefix),
        "data_dir": str(data_dir) if data_dir is not None else None,
        "removed_data": bool(remove_data and data_dir is not None),
        "global_command": asdict(global_command),
    }
    if dry_run:
        return state
    atomic_write_json(uninstall_state_path(resolved_prefix), state)
    if remove_data and data_dir is not None and data_dir.exists():
        shutil.rmtree(data_dir)
    shutil.rmtree(resolved_prefix)
    return state


def default_candidate_id(*, now: datetime | None = None) -> str:
    """Build a sortable candidate id from a UTC timestamp."""

    timestamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    return f"update-{timestamp}"


def build_update_candidate_plan(
    args: argparse.Namespace,
    update_source: UpdateSource,
    *,
    candidate_id: str | None = None,
    now: datetime | None = None,
) -> InstallerPlan:
    """Create an installer plan rooted under runtime/candidates/<candidate_id>."""

    prefix = (args.prefix or default_prefix()).expanduser()
    data_dir = (getattr(args, "data_dir", None) or default_data_dir()).expanduser()
    selected_candidate_id = candidate_id or default_candidate_id(now=now)
    release_id = args.release_id or selected_candidate_id
    runtime_dir = prefix / "runtime"
    candidate_dir = runtime_dir / "candidates" / selected_candidate_id
    source_dir = candidate_dir / "source"
    venv_dir = candidate_dir / "venv"
    build_dir = candidate_dir / "build"
    return InstallerPlan(
        repo_root=str(Path(update_source.path).resolve()),
        prefix=str(prefix.resolve()),
        data_dir=str(data_dir.resolve()),
        install_data_dir=str((prefix / "data").resolve()),
        self_evolution_data_dir=str((prefix / "data" / "self-evolution").resolve()),
        release_id=str(release_id),
        runtime_dir=str(runtime_dir.resolve()),
        release_dir=str(candidate_dir.resolve()),
        source_dir=str(source_dir.resolve()),
        venv_dir=str(venv_dir.resolve()),
        build_dir=str(build_dir.resolve()),
        bin_dir=str((prefix / "bin").resolve()),
        python_path=str(venv_python_path(venv_dir).expanduser()),
        use_venv=True,
        active_path=str((runtime_dir / "active.json").resolve()),
        previous_path=str((runtime_dir / "previous.json").resolve()),
        dry_run=bool(getattr(args, "dry_run", False)),
    )


def release_plan_from_candidate(plan: InstallerPlan) -> InstallerPlan:
    """Return the final release plan for an already-built candidate."""

    prefix = Path(plan.prefix)
    runtime_dir = Path(plan.runtime_dir)
    release_dir = runtime_dir / "releases" / plan.release_id
    source_dir = release_dir / "source"
    venv_dir = release_dir / "venv"
    build_dir = release_dir / "build"
    return InstallerPlan(
        repo_root=plan.repo_root,
        prefix=plan.prefix,
        data_dir=plan.data_dir,
        install_data_dir=plan.install_data_dir,
        self_evolution_data_dir=plan.self_evolution_data_dir,
        release_id=plan.release_id,
        runtime_dir=plan.runtime_dir,
        release_dir=str(release_dir.resolve()),
        source_dir=str(source_dir.resolve()),
        venv_dir=str(venv_dir.resolve()),
        build_dir=str(build_dir.resolve()),
        bin_dir=str((prefix / "bin").resolve()),
        python_path=str(venv_python_path(venv_dir).expanduser()),
        use_venv=plan.use_venv,
        active_path=plan.active_path,
        previous_path=plan.previous_path,
        dry_run=plan.dry_run,
    )


def candidate_directories(plan: InstallerPlan) -> tuple[Path, ...]:
    """Return the directories owned by an update candidate."""

    return (
        Path(plan.release_dir),
        Path(plan.source_dir),
        Path(plan.venv_dir),
        Path(plan.build_dir),
    )


def create_candidate_directories(
    plan: InstallerPlan,
    *,
    dry_run: bool = False,
) -> tuple[Path, ...]:
    """Create runtime/candidates/<candidate_id> without touching active release files."""

    directories = candidate_directories(plan)
    if dry_run:
        return directories
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
    return directories


def build_update_state(
    plan: InstallerPlan,
    update_source: UpdateSource,
    *,
    candidate_id: str,
    status: str = "planned",
    activated: bool = False,
    restart_requested: bool = False,
    error: str | None = None,
) -> UpdateCandidateState:
    """Create the update state payload shared by candidate and runtime state files."""

    return UpdateCandidateState(
        mode="update",
        candidate_id=candidate_id,
        source_kind=update_source.kind,
        source_path=update_source.path,
        old_release_id=update_source.active_release_id,
        new_release_id=plan.release_id,
        status=status,
        activated=activated,
        restart_requested=restart_requested,
        error=error,
    )


def write_update_state(
    plan: InstallerPlan,
    state: UpdateCandidateState,
    *,
    dry_run: bool = False,
) -> dict:
    """Atomically write candidate and runtime update state."""

    payload = asdict(state)
    if dry_run:
        return payload
    atomic_write_json(Path(plan.release_dir) / "update-state.json", payload)
    atomic_write_json(runtime_update_state_path(Path(plan.prefix)), payload)
    return payload


def write_candidate_metadata(plan: InstallerPlan, *, now: datetime | None = None) -> dict:
    """Write candidate metadata without changing active or previous pointers."""

    metadata = release_metadata(plan, now=now)
    atomic_write_json(Path(plan.release_dir) / "metadata.json", metadata)
    return metadata


def activate_update_candidate(
    plan: InstallerPlan,
    update_source: UpdateSource,
    *,
    candidate_id: str,
    restart_requested: bool = False,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict:
    """Promote a verified candidate to a release and point active.json at it."""

    release_plan = release_plan_from_candidate(plan)
    if not dry_run:
        shutil.copytree(Path(plan.release_dir), Path(release_plan.release_dir), dirs_exist_ok=True)
        write_release_metadata(release_plan, now=now)
        create_launcher_scripts(release_plan)
    activated_state = build_update_state(
        plan,
        update_source,
        candidate_id=candidate_id,
        status="activated",
        activated=True,
        restart_requested=restart_requested,
    )
    payload = write_update_state(plan, activated_state, dry_run=dry_run)
    if restart_requested and not dry_run:
        payload["restart_intent"] = write_restart_intent(
            release_plan,
            mode="cli",
            argv=("zermes", "chat"),
            cwd=Path.cwd(),
        )
    return payload


def build_update_candidate(
    args: argparse.Namespace,
    *,
    repo_root: Path,
    candidate_id: str | None = None,
    now: datetime | None = None,
) -> dict:
    """Build and verify an update candidate without activating it."""

    update_source = resolve_update_source(args, repo_root=repo_root)
    selected_candidate_id = candidate_id or default_candidate_id(now=now)
    plan = build_update_candidate_plan(
        args,
        update_source,
        candidate_id=selected_candidate_id,
    )
    dry_run = bool(getattr(args, "dry_run", False))

    # The state file is the user's first place to inspect a failed candidate.
    try:
        create_candidate_directories(plan, dry_run=dry_run)
        sync_source_to_release(plan, dry_run=dry_run)
        create_virtual_environment(plan, dry_run=dry_run)
        install_python_dependencies(
            plan,
            install_deps=getattr(args, "install_deps", True),
            dry_run=dry_run,
        )
        verify_installed_runtime(
            plan,
            skip_verify=getattr(args, "skip_verify", False),
            dry_run=dry_run,
        )
        if not dry_run:
            write_candidate_metadata(plan, now=now)
        ready_state = build_update_state(
            plan,
            update_source,
            candidate_id=selected_candidate_id,
            status="ready",
            restart_requested=bool(getattr(args, "restart", False)),
        )
        write_update_state(plan, ready_state, dry_run=dry_run)
        if getattr(args, "activate", False):
            return activate_update_candidate(
                plan,
                update_source,
                candidate_id=selected_candidate_id,
                restart_requested=bool(getattr(args, "restart", False)),
                dry_run=dry_run,
                now=now,
            )
        return asdict(ready_state)
    except Exception as exc:
        blocked_state = build_update_state(
            plan,
            update_source,
            candidate_id=selected_candidate_id,
            status="blocked",
            restart_requested=bool(getattr(args, "restart", False)),
            error=str(exc),
        )
        write_update_state(plan, blocked_state, dry_run=dry_run)
        raise


def resolve_update_source(
    args: argparse.Namespace,
    *,
    repo_root: Path,
    input_fn=input,
) -> UpdateSource:
    """Resolve the explicit checkout used to build an update candidate."""

    prefix = args.prefix or default_prefix()
    active_metadata = read_active_metadata(prefix)
    active_release_id = active_metadata.get("release_id") if active_metadata else None
    active_source_path = active_metadata.get("source_path") if active_metadata else None

    source_kind: str
    source_path: Path | None = None
    if getattr(args, "source", None) is not None:
        source_kind = "explicit"
        source_path = args.source
    elif getattr(args, "current_source", False):
        source_kind = "current-source"
        source_path = repo_root
    elif getattr(args, "non_interactive", False):
        raise ValueError("non-interactive update requires --source or --current-source")
    elif active_source_path and prompt_yes_no(
        f"Use active release source at {active_source_path}? [y/N] ",
        default=False,
        input_fn=input_fn,
    ):
        source_kind = "active-metadata"
        source_path = Path(active_source_path)
    else:
        raise ValueError("update source is required")

    resolved_source = source_path.expanduser().resolve()
    if active_source_path and resolved_source == Path(active_source_path).expanduser().resolve():
        if not getattr(args, "force", False):
            raise ValueError("refusing to update from the active release source without --force")
    return UpdateSource(
        kind=source_kind,
        path=str(resolved_source),
        active_release_id=active_release_id,
        active_source_path=active_source_path,
    )


def prompt_yes_no(prompt: str, *, default: bool = False, input_fn=input) -> bool:
    answer = input_fn(prompt).strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes", "1", "true", "是", "好"}


def prompt_path(prompt: str, *, default: Path, input_fn=input) -> Path:
    """Prompt for a path, returning the default when the user presses enter."""

    answer = input_fn(f"{prompt} [{default}]: ").strip()
    return Path(answer).expanduser() if answer else default


def prepare_interactive_install_args(
    args: argparse.Namespace,
    *,
    input_fn=input,
) -> argparse.Namespace:
    """Fill missing install options for an interactive install run."""

    if getattr(args, "non_interactive", False) or getattr(args, "dry_run", False):
        return args

    if args.prefix is None:
        args.prefix = prompt_path(
            "Installation directory",
            default=default_prefix(),
            input_fn=input_fn,
        )
    if args.data_dir is None:
        args.data_dir = prompt_path(
            "User data directory",
            default=default_data_dir(),
            input_fn=input_fn,
        )
    if not getattr(args, "no_venv", False):
        create_venv = prompt_yes_no(
            "Create a Python virtual environment? [Y/n] ",
            default=True,
            input_fn=input_fn,
        )
        args.no_venv = not create_venv
    if getattr(args, "install_deps", True):
        args.install_deps = prompt_yes_no(
            "Install Python dependencies now? [Y/n] ",
            default=True,
            input_fn=input_fn,
        )
    if getattr(args, "create_launchers", True):
        args.create_launchers = prompt_yes_no(
            "Create command-line launchers? [Y/n] ",
            default=True,
            input_fn=input_fn,
        )
    if getattr(args, "create_launchers", True) and getattr(args, "global_command", None) is None:
        args.global_command = prompt_yes_no(
            "Enable the global zermes command for this user? [Y/n] ",
            default=True,
            input_fn=input_fn,
        )
    return args


def has_command(name: str) -> bool:
    return shutil.which(name) is not None


def run_command(
    command: list[str] | tuple[str, ...],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    dry_run: bool = False,
) -> CommandResult:
    command_tuple = tuple(str(part) for part in command)
    if dry_run:
        return CommandResult(command=command_tuple, returncode=0, dry_run=True)
    try:
        completed = subprocess.run(
            list(command_tuple),
            cwd=cwd,
            env={**os.environ, **env} if env else None,
            text=True,
            capture_output=True,
            check=False,
            shell=False,
        )
    except FileNotFoundError as exc:
        raise InstallerCommandError(
            CommandResult(command=command_tuple, returncode=127, stderr=str(exc))
        ) from exc
    result = CommandResult(
        command=command_tuple,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
    if completed.returncode != 0:
        raise InstallerCommandError(result)
    return result


def venv_python_path(venv_dir: Path, *, platform: str | None = None) -> Path:
    platform_name = platform or sys.platform
    if platform_name == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def create_virtual_environment(
    plan: InstallerPlan,
    *,
    python_executable: Path | str | None = None,
    dry_run: bool = False,
) -> CommandResult:
    if not plan.use_venv:
        return CommandResult(command=(), returncode=0, dry_run=dry_run)
    selected_python = str(python_executable or sys.executable)
    return run_command(
        [selected_python, "-m", "venv", plan.venv_dir],
        dry_run=dry_run,
    )


def dependency_install_commands(plan: InstallerPlan) -> tuple[list[str], ...]:
    source_dir = Path(plan.source_dir)
    uv_pip_install_all = [
        "uv",
        "pip",
        "install",
        "--python",
        plan.python_path,
        "-e",
        ".[all]",
    ]
    uv_pip_install_base = [
        "uv",
        "pip",
        "install",
        "--python",
        plan.python_path,
        "-e",
        ".",
    ]
    pip_install_all = [plan.python_path, "-m", "pip", "install", "-e", ".[all]"]
    pip_install_base = [plan.python_path, "-m", "pip", "install", "-e", "."]
    if (source_dir / "uv.lock").exists():
        return (
            ["uv", "sync", "--all-extras", "--locked"],
            uv_pip_install_all,
            uv_pip_install_base,
            pip_install_all,
            pip_install_base,
        )
    return (
        uv_pip_install_all,
        uv_pip_install_base,
        pip_install_all,
        pip_install_base,
    )


def install_python_dependencies(
    plan: InstallerPlan,
    *,
    install_deps: bool = True,
    dry_run: bool = False,
) -> CommandResult:
    if not install_deps:
        return CommandResult(command=(), returncode=0, dry_run=dry_run)
    commands = dependency_install_commands(plan)
    last_error: InstallerCommandError | None = None
    for index, command in enumerate(commands):
        try:
            if command[:2] == ["uv", "sync"]:
                result = run_command(
                    command,
                    cwd=Path(plan.source_dir),
                    env={"UV_PROJECT_ENVIRONMENT": plan.venv_dir},
                    dry_run=dry_run,
                )
            elif len(command) >= 4 and command[1:4] == ["-m", "pip", "install"]:
                result = run_command(
                    command,
                    cwd=Path(plan.source_dir),
                    dry_run=dry_run,
                )
            else:
                result = run_command(
                    command,
                    cwd=Path(plan.source_dir),
                    dry_run=dry_run,
                )
            return result
        except InstallerCommandError as exc:
            last_error = exc
            if index == len(commands) - 1:
                raise
    if last_error is not None:
        raise last_error
    raise RuntimeError("no dependency installation commands were planned")


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def release_metadata(plan: InstallerPlan, *, now: datetime | None = None) -> dict:
    timestamp = (now or datetime.now(UTC)).isoformat()
    return {
        "schema_version": 1,
        "release_id": plan.release_id,
        "install_prefix": plan.prefix,
        "data_dir": plan.data_dir,
        "install_data_dir": plan.install_data_dir,
        "self_evolution_data_dir": plan.self_evolution_data_dir,
        "source_path": plan.source_dir,
        "venv_path": plan.venv_dir,
        "build_path": plan.build_dir,
        "python_path": plan.python_path,
        "candidate_commit": git_commit_or_empty(Path(plan.repo_root)),
        "source_repo": {"path": plan.repo_root},
        "created_at": timestamp,
        "activated_at": timestamp,
        "installer_version": "source-installer-v1",
    }


def git_commit_or_empty(repo_root: Path) -> str:
    """Return the current Git commit for metadata, or empty for non-Git tests."""

    if not repo_root.exists():
        return ""
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
        shell=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def write_release_metadata(plan: InstallerPlan, *, now: datetime | None = None) -> dict:
    metadata = release_metadata(plan, now=now)
    metadata_path = Path(plan.release_dir) / "metadata.json"
    active_path = Path(plan.active_path)
    previous_path = Path(plan.previous_path)
    if active_path.exists():
        previous_payload = json.loads(active_path.read_text(encoding="utf-8"))
        atomic_write_json(previous_path, previous_payload)
    atomic_write_json(metadata_path, metadata)
    atomic_write_json(active_path, metadata)
    return metadata


def write_restart_intent(
    plan: InstallerPlan,
    *,
    mode: str,
    argv: tuple[str, ...],
    cwd: Path | None = None,
    now: datetime | None = None,
) -> dict:
    """Write the governed launcher restart intent for an activated release."""

    active_path = Path(plan.active_path)
    active_payload = json.loads(active_path.read_text(encoding="utf-8"))
    timestamp = (now or datetime.now(UTC)).isoformat()
    intent = {
        "schema_version": 1,
        "status": "requested",
        "mode": mode,
        "release_id": active_payload.get("release_id", ""),
        "active_release_digest": _json_digest(active_payload),
        "requested_by": "installer",
        "approved_by_user": True,
        "argv": list(argv),
        "cwd": str((cwd or Path.cwd()).expanduser().resolve()),
        "profile_home": plan.data_dir,
        "reason": "installer update requested restart",
        "created_at": timestamp,
    }
    atomic_write_json(Path(plan.runtime_dir) / "restart-intent.json", intent)
    return intent


def _json_digest(payload: dict) -> str:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def posix_launcher_text(plan: InstallerPlan) -> str:
    launcher_path = Path(plan.prefix) / "launcher" / "zermes_launcher.py"
    return (
        "#!/usr/bin/env sh\n"
        f"export ZERMES_INSTALL_PREFIX=\"{plan.prefix}\"\n"
        f"exec \"{plan.python_path}\" \"{launcher_path}\" cli \"$@\"\n"
    )


def posix_gateway_launcher_text(plan: InstallerPlan) -> str:
    launcher_path = Path(plan.prefix) / "launcher" / "zermes_launcher.py"
    return (
        "#!/usr/bin/env sh\n"
        f"export ZERMES_INSTALL_PREFIX=\"{plan.prefix}\"\n"
        f"exec \"{plan.python_path}\" \"{launcher_path}\" gateway \"$@\"\n"
    )


def windows_launcher_text(plan: InstallerPlan) -> str:
    launcher_path = Path(plan.prefix) / "launcher" / "zermes_launcher.py"
    return (
        "@echo off\r\n"
        f"set ZERMES_INSTALL_PREFIX={plan.prefix}\r\n"
        f"\"{plan.python_path}\" \"{launcher_path}\" cli %*\r\n"
    )


def windows_gateway_launcher_text(plan: InstallerPlan) -> str:
    launcher_path = Path(plan.prefix) / "launcher" / "zermes_launcher.py"
    return (
        "@echo off\r\n"
        f"set ZERMES_INSTALL_PREFIX={plan.prefix}\r\n"
        f"\"{plan.python_path}\" \"{launcher_path}\" gateway %*\r\n"
    )


def create_launcher_scripts(
    plan: InstallerPlan,
    *,
    create_launchers: bool = True,
    dry_run: bool = False,
) -> tuple[Path, ...]:
    if not create_launchers:
        return ()
    launcher_source = Path(plan.source_dir) / "launcher" / "zermes_launcher.py"
    launcher_path = Path(plan.prefix) / "launcher" / "zermes_launcher.py"
    posix_path = Path(plan.bin_dir) / "zermes"
    posix_gateway_path = Path(plan.bin_dir) / "zermes-gateway"
    windows_path = Path(plan.bin_dir) / "zermes.bat"
    windows_gateway_path = Path(plan.bin_dir) / "zermes-gateway.bat"
    if dry_run:
        return (launcher_path, posix_path, posix_gateway_path, windows_path, windows_gateway_path)
    if not launcher_source.exists():
        raise ValueError(f"launcher source does not exist: {launcher_source}")
    launcher_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(launcher_source, launcher_path)
    launcher_path.chmod(0o755)
    posix_path.parent.mkdir(parents=True, exist_ok=True)
    posix_path.write_text(posix_launcher_text(plan), encoding="utf-8")
    posix_gateway_path.write_text(posix_gateway_launcher_text(plan), encoding="utf-8")
    windows_path.write_text(windows_launcher_text(plan), encoding="utf-8")
    windows_gateway_path.write_text(windows_gateway_launcher_text(plan), encoding="utf-8")
    posix_path.chmod(0o755)
    posix_gateway_path.chmod(0o755)
    return (launcher_path, posix_path, posix_gateway_path, windows_path, windows_gateway_path)


def _path_contains(directory: Path, path_value: str, *, platform: str) -> bool:
    separator = ";" if platform == "windows" else os.pathsep
    target = os.path.normcase(os.path.normpath(str(directory.expanduser())))
    if platform == "windows":
        target = target.lower()
    for entry in path_value.split(separator):
        if not entry:
            continue
        candidate = os.path.normcase(os.path.normpath(str(Path(entry).expanduser())))
        if platform == "windows":
            candidate = candidate.lower()
        if candidate == target:
            return True
    return False


def _append_path_entry(path_value: str, directory: Path, *, platform: str) -> str:
    separator = ";" if platform == "windows" else os.pathsep
    if not path_value:
        return str(directory)
    return f"{path_value}{separator}{directory}"


def read_user_windows_path() -> str:
    """Read the current user's persistent Windows PATH value."""

    if os.name != "nt":
        return ""
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        try:
            value, _value_type = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            return ""
    return str(value)


def write_user_windows_path(path_value: str) -> None:
    """Persist the current user's Windows PATH value."""

    if os.name != "nt":
        return
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, path_value)


def configure_global_command(
    plan: InstallerPlan,
    *,
    enabled: bool = False,
    global_bin_dir: Path | None = None,
    platform: str | None = None,
    env_path: str | None = None,
    dry_run: bool = False,
    windows_path_writer=write_user_windows_path,
) -> GlobalCommandResult:
    """Make the installed zermes launcher discoverable from arbitrary directories."""

    if not enabled:
        return GlobalCommandResult(
            status="skipped",
            method="none",
            path=None,
            message="Global zermes command was not requested.",
        )

    current_platform = platform or ("windows" if os.name == "nt" else "posix")
    if current_platform == "windows":
        path_dir = (global_bin_dir or Path(plan.bin_dir)).expanduser()
        current_path = read_user_windows_path() if env_path is None else env_path
        if _path_contains(path_dir, current_path, platform="windows"):
            return GlobalCommandResult(
                status="already_configured",
                method="user-path",
                path=str(path_dir),
                message="The zermes launcher directory is already on the user PATH.",
            )
        if not dry_run:
            windows_path_writer(_append_path_entry(current_path, path_dir, platform="windows"))
        return GlobalCommandResult(
            status="enabled",
            method="user-path",
            path=str(path_dir),
            message="Added the zermes launcher directory to the user PATH. Open a new terminal before running zermes.",
        )

    path_dir = (global_bin_dir or (Path.home() / ".local" / "bin")).expanduser()
    link_path = path_dir / "zermes"
    launcher_path = Path(plan.bin_dir) / "zermes"
    current_path = os.environ.get("PATH", "") if env_path is None else env_path
    path_ready = _path_contains(path_dir, current_path, platform="posix")
    if not dry_run:
        path_dir.mkdir(parents=True, exist_ok=True)
        if link_path.exists() or link_path.is_symlink():
            link_path.unlink()
        link_path.symlink_to(launcher_path)
    if path_ready:
        return GlobalCommandResult(
            status="enabled",
            method="symlink",
            path=str(link_path),
            message="Created a user-level zermes command on PATH.",
        )
    return GlobalCommandResult(
        status="manual_action_required",
        method="symlink",
        path=str(link_path),
        message=f"Created {link_path}; add {path_dir} to PATH or open a shell where it is already configured.",
    )


def verification_commands(
    plan: InstallerPlan,
    *,
    verify_cli: bool = True,
) -> tuple[list[str], ...]:
    commands = [
        [plan.python_path, "-c", "import sys; print(sys.version)"],
        [plan.python_path, "-m", "pip", "--version"],
    ]
    if verify_cli:
        commands.append([plan.python_path, "-m", "hermes_cli.main", "--help"])
    return tuple(commands)


def verify_installed_runtime(
    plan: InstallerPlan,
    *,
    skip_verify: bool = False,
    verify_cli: bool = True,
    dry_run: bool = False,
) -> tuple[CommandResult, ...]:
    if skip_verify:
        return ()
    results: list[CommandResult] = []
    for command in verification_commands(plan, verify_cli=verify_cli):
        results.append(
            run_command(
                command,
                cwd=Path(plan.source_dir),
                dry_run=dry_run,
            )
        )
    return tuple(results)


def create_data_directory(plan: InstallerPlan, *, dry_run: bool = False) -> Path:
    """Create the user data directory recorded in launcher environment."""

    data_dir = Path(plan.data_dir)
    if not dry_run:
        data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def install_data_directories(plan: InstallerPlan) -> tuple[Path, ...]:
    """Return install-local runtime data directories owned by the installer."""

    self_evolution_data_dir = Path(plan.self_evolution_data_dir)
    return (
        Path(plan.install_data_dir),
        self_evolution_data_dir,
        self_evolution_data_dir / "tasks",
        self_evolution_data_dir / "candidates",
        self_evolution_data_dir / "locks",
        self_evolution_data_dir / "locks" / "repositories",
        self_evolution_data_dir / "reports",
        Path(plan.install_data_dir) / "tmp",
    )


def install_directories(plan: InstallerPlan) -> tuple[Path, ...]:
    return (
        Path(plan.prefix) / "launcher",
        Path(plan.runtime_dir),
        Path(plan.release_dir),
        Path(plan.source_dir),
        Path(plan.build_dir),
        Path(plan.bin_dir),
        Path(plan.prefix) / "logs",
        *install_data_directories(plan),
    )


def create_install_directories(plan: InstallerPlan, *, dry_run: bool = False) -> tuple[Path, ...]:
    directories = install_directories(plan)
    if dry_run:
        return directories
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
    return directories


def sync_source_to_release(plan: InstallerPlan, *, dry_run: bool = False) -> list[Path]:
    repo_root = Path(plan.repo_root).resolve()
    target_root = Path(plan.source_dir).resolve()
    if target_root == repo_root or target_root in repo_root.parents:
        raise ValueError("source release directory must not be the repository root or its parent")
    try:
        target_root.relative_to(repo_root)
    except ValueError:
        pass
    else:
        raise ValueError("source release directory must not be inside the repository root")

    copied: list[Path] = []
    if dry_run:
        return copied
    archived = sync_git_archive_to_release(repo_root, target_root)
    if archived is not None:
        return archived
    target_root.mkdir(parents=True, exist_ok=True)
    for current_root, dir_names, file_names in os.walk(repo_root):
        current_path = Path(current_root)
        dir_names[:] = [
            name for name in dir_names
            if name not in EXCLUDED_SOURCE_DIR_NAMES
        ]
        relative_root = current_path.relative_to(repo_root)
        destination_root = target_root / relative_root
        destination_root.mkdir(parents=True, exist_ok=True)
        for file_name in file_names:
            source_file = current_path / file_name
            destination_file = destination_root / file_name
            shutil.copy2(source_file, destination_file)
            copied.append(destination_file)
    return copied


def sync_git_archive_to_release(repo_root: Path, target_root: Path) -> list[Path] | None:
    """Copy tracked source files with git archive when the source is a git checkout."""

    if not (repo_root / ".git").exists():
        return None
    completed = subprocess.run(
        ["git", "archive", "--format=tar", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        check=False,
        shell=False,
    )
    if completed.returncode != 0:
        return None

    target_root.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    with tarfile.open(fileobj=BytesIO(completed.stdout), mode="r:") as archive:
        for member in archive.getmembers():
            destination = (target_root / member.name).resolve()
            try:
                destination.relative_to(target_root)
            except ValueError as exc:
                raise ValueError(f"refusing to extract unsafe archive path: {member.name}") from exc
            archive.extract(member, target_root)
            if member.isfile():
                extracted.append(destination)
    return extracted


def build_plan(args: argparse.Namespace, *, repo_root: Path) -> InstallerPlan:
    prefix = (args.prefix or default_prefix()).expanduser()
    data_dir = (args.data_dir or default_data_dir()).expanduser()
    use_venv = not bool(getattr(args, "no_venv", False))
    runtime_dir = prefix / "runtime"
    release_dir = runtime_dir / "releases" / str(args.release_id)
    source_dir = release_dir / "source"
    venv_dir = release_dir / "venv"
    build_dir = release_dir / "build"
    bin_dir = prefix / "bin"
    install_data_dir = prefix / "data"
    self_evolution_data_dir = install_data_dir / "self-evolution"
    selected_python = getattr(args, "python", None)
    python_path = venv_python_path(venv_dir) if use_venv else Path(selected_python or sys.executable)
    resolved_python_path = python_path.expanduser()
    if not use_venv:
        resolved_python_path = resolved_python_path.resolve()
    return InstallerPlan(
        repo_root=str(repo_root.resolve()),
        prefix=str(prefix.resolve()),
        data_dir=str(data_dir.resolve()),
        install_data_dir=str(install_data_dir.resolve()),
        self_evolution_data_dir=str(self_evolution_data_dir.resolve()),
        release_id=str(args.release_id),
        runtime_dir=str(runtime_dir.resolve()),
        release_dir=str(release_dir.resolve()),
        source_dir=str(source_dir.resolve()),
        venv_dir=str(venv_dir.resolve()),
        build_dir=str(build_dir.resolve()),
        bin_dir=str(bin_dir.resolve()),
        python_path=str(resolved_python_path),
        use_venv=use_venv,
        active_path=str((runtime_dir / "active.json").resolve()),
        previous_path=str((runtime_dir / "previous.json").resolve()),
        dry_run=bool(args.dry_run),
    )


def emit_plan(plan: InstallerPlan) -> None:
    print(json.dumps(asdict(plan), ensure_ascii=False, indent=2))


def run_install_workflow(
    args: argparse.Namespace,
    *,
    repo_root: Path,
    input_fn=input,
    now: datetime | None = None,
) -> dict:
    """Run the source install workflow from directory creation to optional start."""

    plan = build_plan(args, repo_root=repo_root)
    if plan.dry_run:
        return asdict(plan)

    steps: list[dict[str, object]] = []

    def mark(step: str, detail: object | None = None) -> None:
        payload: dict[str, object] = {"step": step, "status": "done"}
        if detail is not None:
            payload["detail"] = detail
        steps.append(payload)

    def announce(message: str) -> None:
        if not getattr(args, "non_interactive", False):
            print(message, file=sys.stderr, flush=True)

    announce(f"Creating install directories under {plan.prefix}...")
    create_install_directories(plan)
    mark("create-install-directories")
    announce(f"Creating user data directory at {plan.data_dir}...")
    create_data_directory(plan)
    mark("create-data-directory", plan.data_dir)
    announce("Copying source files into the release directory...")
    copied_files = sync_source_to_release(plan)
    mark("sync-source", {"files": len(copied_files)})
    announce("Creating Python virtual environment...")
    create_virtual_environment(plan, python_executable=getattr(args, "python", None))
    mark("create-virtual-environment", {"enabled": plan.use_venv})
    announce("Installing Python dependencies...")
    install_python_dependencies(
        plan,
        install_deps=getattr(args, "install_deps", True),
    )
    mark("install-python-dependencies", {"enabled": getattr(args, "install_deps", True)})
    announce("Writing release metadata...")
    metadata = write_release_metadata(plan, now=now)
    mark("write-release-metadata", {"release_id": plan.release_id})
    announce("Creating launcher scripts...")
    launchers = create_launcher_scripts(
        plan,
        create_launchers=getattr(args, "create_launchers", True),
    )
    mark("create-launchers", [str(path) for path in launchers])
    announce("Configuring global zermes command...")
    global_command = configure_global_command(
        plan,
        enabled=bool(getattr(args, "global_command", False)),
        global_bin_dir=getattr(args, "global_bin_dir", None),
    )
    mark("configure-global-command", asdict(global_command))
    announce("Verifying the installed runtime...")
    verification_results = verify_installed_runtime(
        plan,
        skip_verify=getattr(args, "skip_verify", False),
        verify_cli=getattr(args, "install_deps", True),
    )
    mark("verify-runtime", {"commands": len(verification_results)})
    return {
        "status": "installed",
        "plan": asdict(plan),
        "steps": steps,
        "metadata": metadata,
        "launchers": [str(path) for path in launchers],
        "global_command": asdict(global_command),
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = getattr(args, "command", None)
    if command is None and getattr(args, "non_interactive", False):
        parser.error("non-interactive mode requires install, update, rollback, or uninstall")
    if command is None:
        args.command = "install"
    repo_root = Path(__file__).resolve().parents[1]
    if args.command == "update":
        try:
            update_state = build_update_candidate(args, repo_root=repo_root)
        except (ValueError, InstallerCommandError) as exc:
            parser.error(str(exc))
        print(json.dumps(update_state, ensure_ascii=False, indent=2))
        return 0
    if args.command == "rollback":
        try:
            rollback_state = rollback_release(
                args.prefix or default_prefix(),
                dry_run=bool(args.dry_run),
            )
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps(rollback_state, ensure_ascii=False, indent=2))
        return 0
    if args.command == "uninstall":
        try:
            uninstall_state = uninstall_runtime(
                args.prefix or default_prefix(),
                remove_data=bool(args.remove_data),
                remove_global=bool(args.remove_global_command),
                global_bin_dir=args.global_bin_dir,
                dry_run=bool(args.dry_run),
            )
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps(uninstall_state, ensure_ascii=False, indent=2))
        return 0
    try:
        args = prepare_interactive_install_args(args)
        install_result = run_install_workflow(args, repo_root=repo_root)
    except (ValueError, InstallerCommandError) as exc:
        parser.error(str(exc))
    print(json.dumps(install_result, ensure_ascii=False, indent=2))
    return 0

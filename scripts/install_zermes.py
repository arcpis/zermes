"""Source installer implementation for Zermes.

The installer owns the stable runtime directory model for source-based Zermes
installs. It keeps install, update, and rollback concerns explicit so a random
checkout is never silently applied to a long-running runtime.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


SUPPORTED_LANGUAGES = ("zh-CN", "en-US")
DEFAULT_LANGUAGE = "zh-CN"
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

MESSAGES = {
    "zh-CN": {
        "language_prompt": "请选择安装器语言 / Choose installer language [1=中文, 2=English] (默认 1): ",
    },
    "en-US": {
        "language_prompt": "Choose installer language [1=Chinese, 2=English] (default 1): ",
    },
}


@dataclass(frozen=True)
class InstallerPlan:
    """Dry-run description of a future source installation."""

    repo_root: str
    language: str
    prefix: str
    data_dir: str
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
class UpdateSource:
    """Resolved source checkout for an update candidate."""

    kind: str
    path: str
    active_release_id: str | None = None
    active_source_path: str | None = None


class InstallerCommandError(RuntimeError):
    """Raised when an installer command fails."""

    def __init__(self, result: CommandResult):
        command_text = " ".join(result.command)
        super().__init__(f"installer command failed ({result.returncode}): {command_text}")
        self.result = result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="install.py",
        description=(
            "Install, update, or roll back Zermes from a source checkout. "
            "Installer language only affects installer messages, not runtime language."
        ),
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
        "--language",
        choices=SUPPORTED_LANGUAGES,
        default=None,
        help="Installer language.",
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
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip post-install runtime verification.",
    )
    start_group = parser.add_mutually_exclusive_group()
    start_group.add_argument(
        "--start",
        dest="start",
        action="store_true",
        default=None,
        help="Start Zermes after installation completes.",
    )
    start_group.add_argument(
        "--no-start",
        dest="start",
        action="store_false",
        help="Do not start Zermes after installation completes.",
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


def read_active_metadata(prefix: Path) -> dict | None:
    """Read active release metadata when an installed runtime exists."""

    path = active_metadata_path(prefix)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


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


def normalize_language(value: str | None) -> str:
    if value is None or not value.strip():
        return DEFAULT_LANGUAGE
    clean = value.strip()
    if clean == "1":
        return "zh-CN"
    if clean == "2":
        return "en-US"
    if clean in SUPPORTED_LANGUAGES:
        return clean
    raise ValueError(f"unsupported language: {value}")


def prompt_language(input_fn=input) -> str:
    answer = input_fn(MESSAGES[DEFAULT_LANGUAGE]["language_prompt"])
    return normalize_language(answer)


def prompt_yes_no(prompt: str, *, default: bool = False, input_fn=input) -> bool:
    answer = input_fn(prompt).strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes", "1", "true", "是", "好"}


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
    completed = subprocess.run(
        list(command_tuple),
        cwd=cwd,
        env={**os.environ, **env} if env else None,
        text=True,
        capture_output=True,
        check=False,
        shell=False,
    )
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
    if (source_dir / "uv.lock").exists():
        return (
            ["uv", "sync", "--all-extras", "--locked"],
            ["uv", "pip", "install", "-e", ".[all]"],
            ["uv", "pip", "install", "-e", "."],
        )
    return (
        ["uv", "pip", "install", "-e", ".[all]"],
        ["uv", "pip", "install", "-e", "."],
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
        "release_id": plan.release_id,
        "install_prefix": plan.prefix,
        "data_dir": plan.data_dir,
        "source_path": plan.source_dir,
        "venv_path": plan.venv_dir,
        "python_path": plan.python_path,
        "created_at": timestamp,
        "installer_version": "source-installer-v1",
    }


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


def posix_launcher_text(plan: InstallerPlan) -> str:
    return (
        "#!/usr/bin/env sh\n"
        f"export HERMES_HOME=\"{plan.data_dir}\"\n"
        f"exec \"{plan.python_path}\" -m hermes_cli.main \"$@\"\n"
    )


def windows_launcher_text(plan: InstallerPlan) -> str:
    return (
        "@echo off\r\n"
        f"set HERMES_HOME={plan.data_dir}\r\n"
        f"\"{plan.python_path}\" -m hermes_cli.main %*\r\n"
    )


def create_launcher_scripts(
    plan: InstallerPlan,
    *,
    create_launchers: bool = True,
    dry_run: bool = False,
) -> tuple[Path, ...]:
    if not create_launchers:
        return ()
    posix_path = Path(plan.bin_dir) / "zermes"
    windows_path = Path(plan.bin_dir) / "zermes.bat"
    if dry_run:
        return (posix_path, windows_path)
    posix_path.parent.mkdir(parents=True, exist_ok=True)
    posix_path.write_text(posix_launcher_text(plan), encoding="utf-8")
    windows_path.write_text(windows_launcher_text(plan), encoding="utf-8")
    posix_path.chmod(0o755)
    return (posix_path, windows_path)


def verification_commands(plan: InstallerPlan) -> tuple[list[str], ...]:
    return (
        [plan.python_path, "-c", "import sys; print(sys.version)"],
        [plan.python_path, "-m", "pip", "--version"],
        [plan.python_path, "-m", "hermes_cli.main", "--help"],
    )


def verify_installed_runtime(
    plan: InstallerPlan,
    *,
    skip_verify: bool = False,
    dry_run: bool = False,
) -> tuple[CommandResult, ...]:
    if skip_verify:
        return ()
    results: list[CommandResult] = []
    for command in verification_commands(plan):
        results.append(
            run_command(
                command,
                cwd=Path(plan.source_dir),
                dry_run=dry_run,
            )
        )
    return tuple(results)


def should_start_after_install(args: argparse.Namespace, *, input_fn=input) -> bool:
    if args.start is not None:
        return bool(args.start)
    if getattr(args, "non_interactive", False):
        return False
    return prompt_yes_no("Start Zermes now? [y/N] ", default=False, input_fn=input_fn)


def start_zermes(
    plan: InstallerPlan,
    *,
    start: bool = False,
    dry_run: bool = False,
) -> CommandResult:
    if not start:
        return CommandResult(command=(), returncode=0, dry_run=dry_run)
    launcher = Path(plan.bin_dir) / ("zermes.bat" if sys.platform == "win32" else "zermes")
    return run_command([str(launcher)], dry_run=dry_run)


def install_directories(plan: InstallerPlan) -> tuple[Path, ...]:
    return (
        Path(plan.prefix) / "launcher",
        Path(plan.runtime_dir),
        Path(plan.release_dir),
        Path(plan.source_dir),
        Path(plan.build_dir),
        Path(plan.bin_dir),
        Path(plan.prefix) / "logs",
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


def build_plan(args: argparse.Namespace, *, repo_root: Path) -> InstallerPlan:
    prefix = (args.prefix or default_prefix()).expanduser()
    data_dir = (args.data_dir or default_data_dir()).expanduser()
    language = normalize_language(args.language)
    use_venv = not bool(getattr(args, "no_venv", False))
    runtime_dir = prefix / "runtime"
    release_dir = runtime_dir / "releases" / str(args.release_id)
    source_dir = release_dir / "source"
    venv_dir = release_dir / "venv"
    build_dir = release_dir / "build"
    bin_dir = prefix / "bin"
    selected_python = getattr(args, "python", None)
    python_path = venv_python_path(venv_dir) if use_venv else Path(selected_python or sys.executable)
    return InstallerPlan(
        repo_root=str(repo_root.resolve()),
        language=language,
        prefix=str(prefix.resolve()),
        data_dir=str(data_dir.resolve()),
        release_id=str(args.release_id),
        runtime_dir=str(runtime_dir.resolve()),
        release_dir=str(release_dir.resolve()),
        source_dir=str(source_dir.resolve()),
        venv_dir=str(venv_dir.resolve()),
        build_dir=str(build_dir.resolve()),
        bin_dir=str(bin_dir.resolve()),
        python_path=str(python_path.expanduser().resolve()),
        use_venv=use_venv,
        active_path=str((runtime_dir / "active.json").resolve()),
        previous_path=str((runtime_dir / "previous.json").resolve()),
        dry_run=bool(args.dry_run),
    )


def emit_plan(plan: InstallerPlan) -> None:
    print(json.dumps(asdict(plan), ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = getattr(args, "command", None)
    if command is None and getattr(args, "non_interactive", False):
        parser.error("non-interactive mode requires install, update, or rollback")
    if command is None:
        args.command = "install"
    if args.language is None and not args.non_interactive:
        try:
            args.language = prompt_language()
        except ValueError as exc:
            parser.error(str(exc))
    repo_root = Path(__file__).resolve().parents[1]
    if args.command == "update":
        try:
            update_source = resolve_update_source(args, repo_root=repo_root)
        except ValueError as exc:
            parser.error(str(exc))
        print(
            json.dumps(
                {
                    "command": "update",
                    "dry_run": bool(args.dry_run),
                    "source_kind": update_source.kind,
                    "source_path": update_source.path,
                },
                indent=2,
            )
        )
        if args.dry_run:
            return 0
        parser.error("update execution is not implemented yet")
    if args.command == "rollback":
        print(json.dumps({"command": "rollback", "dry_run": bool(args.dry_run)}, indent=2))
        if args.dry_run:
            return 0
        parser.error("rollback execution is not implemented yet")
    plan = build_plan(args, repo_root=repo_root)
    emit_plan(plan)
    if args.dry_run:
        return 0
    parser.error("real installation is not implemented yet; use --dry-run")
    return 2

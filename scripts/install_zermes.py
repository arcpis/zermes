"""Source installer implementation for Zermes.

This first slice intentionally supports only planning and dry-run output. Later
installer steps will reuse this entry point for real directory creation,
environment setup, dependency installation, and launcher generation.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import shutil
import subprocess
import sys


SUPPORTED_LANGUAGES = ("zh-CN", "en-US")
DEFAULT_LANGUAGE = "zh-CN"

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


class InstallerCommandError(RuntimeError):
    """Raised when an installer command fails."""

    def __init__(self, result: CommandResult):
        command_text = " ".join(result.command)
        super().__init__(f"installer command failed ({result.returncode}): {command_text}")
        self.result = result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="install.py",
        description="Install Zermes from this source checkout.",
    )
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
    return parser


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


def has_command(name: str) -> bool:
    return shutil.which(name) is not None


def run_command(
    command: list[str] | tuple[str, ...],
    *,
    cwd: Path | None = None,
    dry_run: bool = False,
) -> CommandResult:
    command_tuple = tuple(str(part) for part in command)
    if dry_run:
        return CommandResult(command=command_tuple, returncode=0, dry_run=True)
    completed = subprocess.run(
        list(command_tuple),
        cwd=cwd,
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


def build_plan(args: argparse.Namespace, *, repo_root: Path) -> InstallerPlan:
    prefix = (args.prefix or default_prefix()).expanduser()
    data_dir = (args.data_dir or default_data_dir()).expanduser()
    language = normalize_language(args.language)
    runtime_dir = prefix / "runtime"
    release_dir = runtime_dir / "releases" / str(args.release_id)
    source_dir = release_dir / "source"
    venv_dir = release_dir / "venv"
    build_dir = release_dir / "build"
    bin_dir = prefix / "bin"
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
        active_path=str((runtime_dir / "active.json").resolve()),
        previous_path=str((runtime_dir / "previous.json").resolve()),
        dry_run=bool(args.dry_run),
    )


def emit_plan(plan: InstallerPlan) -> None:
    print(json.dumps(asdict(plan), ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.language is None and not args.non_interactive:
        try:
            args.language = prompt_language()
        except ValueError as exc:
            parser.error(str(exc))
    repo_root = Path(__file__).resolve().parents[1]
    plan = build_plan(args, repo_root=repo_root)
    emit_plan(plan)
    if args.dry_run:
        return 0
    parser.error("real installation is not implemented yet; use --dry-run")
    return 2

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
import sys


SUPPORTED_LANGUAGES = ("zh-CN", "en-US")
DEFAULT_LANGUAGE = "zh-CN"


@dataclass(frozen=True)
class InstallerPlan:
    """Dry-run description of a future source installation."""

    repo_root: str
    language: str
    prefix: str
    data_dir: str
    release_id: str
    dry_run: bool


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
        default=DEFAULT_LANGUAGE,
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


def default_prefix() -> Path:
    if sys.platform == "win32":
        base = Path.home() / "AppData" / "Local"
        return base / "Zermes"
    if sys.platform == "darwin":
        return Path.home() / "Applications" / "Zermes"
    return Path.home() / ".local" / "share" / "zermes"


def default_data_dir() -> Path:
    return Path.home() / ".hermes"


def build_plan(args: argparse.Namespace, *, repo_root: Path) -> InstallerPlan:
    prefix = (args.prefix or default_prefix()).expanduser()
    data_dir = (args.data_dir or default_data_dir()).expanduser()
    return InstallerPlan(
        repo_root=str(repo_root.resolve()),
        language=args.language,
        prefix=str(prefix.resolve()),
        data_dir=str(data_dir.resolve()),
        release_id=str(args.release_id),
        dry_run=bool(args.dry_run),
    )


def emit_plan(plan: InstallerPlan) -> None:
    print(json.dumps(asdict(plan), ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    plan = build_plan(args, repo_root=repo_root)
    emit_plan(plan)
    if args.dry_run:
        return 0
    parser.error("real installation is not implemented yet; use --dry-run")
    return 2

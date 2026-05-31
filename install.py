#!/usr/bin/env python3
"""Source installer entry point for Zermes."""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_repo_root_on_path() -> None:
    repo_root = Path(__file__).resolve().parent
    repo_root_text = str(repo_root)
    if repo_root_text not in sys.path:
        sys.path.insert(0, repo_root_text)


def main(argv: list[str] | None = None) -> int:
    _ensure_repo_root_on_path()
    from scripts.install_zermes import main as installer_main

    return installer_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())

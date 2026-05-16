#!/usr/bin/env python3
"""Launch the active source-installed Zermes runtime.

The small scripts in ``<prefix>/bin`` should stay stable across runtime
updates. They enter this launcher, and this launcher reads
``<prefix>/runtime/active.json`` to exec the currently active release.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    mode = args.pop(0) if args and args[0] in {"cli", "gateway"} else "cli"
    prefix = _resolve_prefix()
    active = _read_active_metadata(prefix)
    python_path = _active_python(active)
    source_path = _required_path(active, "source_path")
    data_dir = str(active.get("data_dir") or "").strip()

    env = os.environ.copy()
    if data_dir:
        env["HERMES_HOME"] = data_dir
        env["ZERMES_HOME"] = data_dir
    env["ZERMES_INSTALL_PREFIX"] = str(prefix)
    env["ZERMES_ACTIVE_RELEASE"] = str(active.get("release_id") or "")
    env["PYTHONPATH"] = _prepend_pythonpath(source_path, env.get("PYTHONPATH"))

    command = [str(python_path), "-m", "hermes_cli.main"]
    if mode == "gateway":
        command.append("gateway")
    command.extend(args)
    os.chdir(source_path)
    os.execve(str(python_path), command, env)
    return 127


def _resolve_prefix() -> Path:
    configured = os.environ.get("ZERMES_INSTALL_PREFIX")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


def _read_active_metadata(prefix: Path) -> dict:
    active_path = prefix / "runtime" / "active.json"
    try:
        payload = json.loads(active_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"active runtime metadata is missing: {active_path}") from None
    except json.JSONDecodeError as exc:
        raise SystemExit(f"active runtime metadata is invalid: {active_path}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"active runtime metadata must be a JSON object: {active_path}")
    return payload


def _active_python(active: dict) -> Path:
    python_path = str(active.get("python_path") or "").strip()
    if python_path:
        return _existing_file(Path(python_path).expanduser(), "python_path")
    venv_path = str(active.get("venv_path") or "").strip()
    if not venv_path:
        raise SystemExit("active runtime metadata is missing python_path or venv_path")
    venv = Path(venv_path).expanduser()
    candidate = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return _existing_file(candidate, "venv python")


def _required_path(active: dict, field_name: str) -> str:
    value = str(active.get(field_name) or "").strip()
    if not value:
        raise SystemExit(f"active runtime metadata is missing {field_name}")
    path = Path(value).expanduser()
    if not path.exists():
        raise SystemExit(f"active runtime {field_name} does not exist: {path}")
    return str(path.resolve())


def _existing_file(path: Path, label: str) -> Path:
    resolved = path.resolve()
    if not resolved.is_file():
        raise SystemExit(f"active runtime {label} does not exist: {resolved}")
    return resolved


def _prepend_pythonpath(source_path: str, current: str | None) -> str:
    if not current:
        return source_path
    return os.pathsep.join((source_path, current))


if __name__ == "__main__":
    raise SystemExit(main())

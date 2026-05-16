#!/usr/bin/env python3
"""Launch the active source-installed Zermes runtime.

The small scripts in ``<prefix>/bin`` should stay stable across runtime
updates. They enter this launcher, and this launcher reads
``<prefix>/runtime/active.json`` to exec the currently active release.
"""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "restart-intent":
        args.pop(0)
        return _exec_restart_intent(args)
    mode = args.pop(0) if args and args[0] in {"cli", "gateway"} else "cli"
    prefix = _resolve_prefix()
    active = _read_active_metadata(prefix)
    return _exec_active_release(prefix, active, mode=mode, args=args)


def _exec_restart_intent(args: list[str]) -> int:
    if args:
        raise SystemExit("restart-intent does not accept command arguments")
    prefix = _resolve_prefix()
    active = _read_active_metadata(prefix)
    intent = _read_restart_intent(prefix)
    _validate_restart_intent(active, intent)
    mode = str(intent.get("mode") or "cli").strip().lower()
    restart_args = _restart_args(intent)
    return _exec_active_release(prefix, active, mode=mode, args=restart_args, intent=intent)


def _exec_active_release(
    prefix: Path,
    active: dict,
    *,
    mode: str,
    args: list[str],
    intent: dict | None = None,
) -> int:
    python_path = _active_python(active)
    source_path = _required_path(active, "source_path")
    data_dir = str(active.get("data_dir") or "").strip()
    restart_cwd = _restart_cwd(intent) if intent else ""
    restart_profile_home = _restart_profile_home(intent) if intent else ""

    env = os.environ.copy()
    profile_home = restart_profile_home or data_dir
    if profile_home:
        env["HERMES_HOME"] = profile_home
        env["ZERMES_HOME"] = profile_home
    env["ZERMES_INSTALL_PREFIX"] = str(prefix)
    env["ZERMES_ACTIVE_RELEASE"] = str(active.get("release_id") or "")
    env["PYTHONPATH"] = _prepend_pythonpath(source_path, env.get("PYTHONPATH"))

    command = [str(python_path), "-m", "hermes_cli.main"]
    if mode == "gateway":
        command.append("gateway")
    command.extend(args)
    os.chdir(restart_cwd or source_path)
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


def _read_restart_intent(prefix: Path) -> dict:
    intent_path = prefix / "runtime" / "restart-intent.json"
    try:
        payload = json.loads(intent_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"restart intent is missing: {intent_path}") from None
    except json.JSONDecodeError as exc:
        raise SystemExit(f"restart intent is invalid: {intent_path}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"restart intent must be a JSON object: {intent_path}")
    return payload


def _validate_restart_intent(active: dict, intent: dict) -> None:
    if intent.get("status") != "requested":
        raise SystemExit("restart intent status must be requested")
    if not intent.get("approved_by_user"):
        raise SystemExit("restart intent is missing user approval")
    mode = str(intent.get("mode") or "").strip().lower()
    if mode not in {"cli", "gateway"}:
        raise SystemExit("restart intent mode must be cli or gateway")
    if str(intent.get("release_id") or "") != str(active.get("release_id") or ""):
        raise SystemExit("restart intent release does not match active release")
    expected_digest = str(intent.get("active_release_digest") or "").strip()
    if not expected_digest:
        raise SystemExit("restart intent is missing active release digest")
    if expected_digest != _json_digest(active):
        raise SystemExit("restart intent active release digest is stale")


def _restart_args(intent: dict) -> list[str]:
    raw = intent.get("argv") or []
    if not isinstance(raw, list):
        raise SystemExit("restart intent argv must be a list")
    args = [str(item) for item in raw if str(item)]
    if any("\x00" in item for item in args):
        raise SystemExit("restart intent argv contains an invalid NUL byte")
    if args and Path(args[0]).name in {"zermes", "zermes.exe", "zermes.bat", "hermes"}:
        args = args[1:]
    if args and args[0] in {"cli", "gateway"}:
        args = args[1:]
    return args


def _restart_cwd(intent: dict | None) -> str:
    cwd = str((intent or {}).get("cwd") or "").strip()
    if not cwd:
        return ""
    path = Path(cwd).expanduser().resolve()
    if not path.is_dir():
        raise SystemExit(f"restart intent cwd does not exist: {path}")
    return str(path)


def _restart_profile_home(intent: dict | None) -> str:
    profile_home = str((intent or {}).get("profile_home") or "").strip()
    if not profile_home:
        return ""
    path = Path(profile_home).expanduser().resolve()
    if not path.is_dir():
        raise SystemExit(f"restart intent profile_home does not exist: {path}")
    return str(path)


def _json_digest(payload: dict) -> str:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


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

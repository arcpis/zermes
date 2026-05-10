from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from scripts import install_zermes


def _args(tmp_path, source):
    """Build update args for candidate orchestration tests."""

    return argparse.Namespace(
        prefix=tmp_path / "app",
        data_dir=tmp_path / "data",
        source=source,
        current_source=False,
        release_id="next-release",
        non_interactive=True,
        force=False,
        dry_run=False,
        install_deps=True,
        skip_verify=False,
        restart=False,
    )


def test_build_update_candidate_runs_steps_in_order(monkeypatch, tmp_path):
    source = tmp_path / "checkout"
    source.mkdir()
    args = _args(tmp_path, source)
    calls: list[str] = []

    def record(name):
        def wrapper(*_args, **_kwargs):
            calls.append(name)
            if name == "verify":
                return ()
            return None

        return wrapper

    monkeypatch.setattr(install_zermes, "create_candidate_directories", record("dirs"))
    monkeypatch.setattr(install_zermes, "sync_source_to_release", record("sync"))
    monkeypatch.setattr(install_zermes, "create_virtual_environment", record("venv"))
    monkeypatch.setattr(install_zermes, "install_python_dependencies", record("deps"))
    monkeypatch.setattr(install_zermes, "verify_installed_runtime", record("verify"))

    state = install_zermes.build_update_candidate(
        args,
        repo_root=tmp_path / "repo",
        candidate_id="candidate-one",
    )

    assert calls == ["dirs", "sync", "venv", "deps", "verify"]
    assert state["status"] == "ready"
    assert state["candidate_id"] == "candidate-one"
    assert json.loads(
        (tmp_path / "app" / "runtime" / "candidates" / "candidate-one" / "metadata.json")
        .read_text(encoding="utf-8")
    )["release_id"] == "next-release"


def test_build_update_candidate_marks_state_blocked_on_failure(monkeypatch, tmp_path):
    source = tmp_path / "checkout"
    source.mkdir()
    args = _args(tmp_path, source)

    def fail_sync(*_args, **_kwargs):
        raise RuntimeError("sync failed")

    monkeypatch.setattr(install_zermes, "sync_source_to_release", fail_sync)

    with pytest.raises(RuntimeError, match="sync failed"):
        install_zermes.build_update_candidate(
            args,
            repo_root=tmp_path / "repo",
            candidate_id="candidate-one",
        )

    state_path = tmp_path / "app" / "runtime" / "candidates" / "candidate-one" / "update-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["status"] == "blocked"
    assert state["error"] == "sync failed"
    assert not (tmp_path / "app" / "runtime" / "active.json").exists()


def test_build_update_candidate_dry_run_does_not_modify_active(tmp_path):
    source = tmp_path / "checkout"
    source.mkdir()
    args = _args(tmp_path, source)
    args.dry_run = True

    state = install_zermes.build_update_candidate(
        args,
        repo_root=tmp_path / "repo",
        candidate_id="candidate-one",
    )

    assert state["status"] == "ready"
    assert not (tmp_path / "app" / "runtime" / "active.json").exists()
    assert not (tmp_path / "app" / "runtime" / "candidates" / "candidate-one").exists()

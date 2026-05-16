from __future__ import annotations



# From test_rollback.py

import json
from pathlib import Path

import pytest

from scripts import install_zermes


def test_rollback_release_points_active_to_previous(tmp_path):
    prefix = tmp_path / "app"
    current = {"release_id": "new-release"}
    previous = {"release_id": "old-release"}
    install_zermes.atomic_write_json(install_zermes.active_metadata_path(prefix), current)
    install_zermes.atomic_write_json(prefix / "runtime" / "previous.json", previous)

    state = install_zermes.rollback_release(prefix)

    active = json.loads(install_zermes.active_metadata_path(prefix).read_text(encoding="utf-8"))
    rollback_state = json.loads(
        install_zermes.rollback_state_path(prefix).read_text(encoding="utf-8")
    )
    assert active == previous
    assert state == rollback_state
    assert state["rolled_back_from"] == current
    assert state["rolled_back_to"] == previous
    assert state["restart_required"] is True


def test_rollback_release_requires_previous(tmp_path):
    with pytest.raises(ValueError, match="previous.json"):
        install_zermes.rollback_release(tmp_path / "app")


def test_rollback_release_does_not_delete_release_directories(tmp_path):
    prefix = tmp_path / "app"
    old_marker = prefix / "runtime" / "releases" / "old-release" / "keep.txt"
    new_marker = prefix / "runtime" / "releases" / "new-release" / "keep.txt"
    old_marker.parent.mkdir(parents=True)
    new_marker.parent.mkdir(parents=True)
    old_marker.write_text("old", encoding="utf-8")
    new_marker.write_text("new", encoding="utf-8")
    install_zermes.atomic_write_json(install_zermes.active_metadata_path(prefix), {"release_id": "new-release"})
    install_zermes.atomic_write_json(prefix / "runtime" / "previous.json", {"release_id": "old-release"})

    install_zermes.rollback_release(prefix)

    assert old_marker.read_text(encoding="utf-8") == "old"
    assert new_marker.read_text(encoding="utf-8") == "new"



# From test_update_activate.py

import argparse
import json
from pathlib import Path

from scripts import install_zermes


def _source_update_activate(tmp_path):
    """Create a resolved source record for activation tests."""

    checkout = tmp_path / "checkout"
    checkout.mkdir()
    return install_zermes.UpdateSource(
        kind="explicit",
        path=str(checkout.resolve()),
        active_release_id="old-release",
        active_source_path=None,
    )


def _plan_update_activate(tmp_path, source):
    """Create a candidate plan with a small candidate payload."""

    args = argparse.Namespace(
        prefix=tmp_path / "app",
        data_dir=tmp_path / "data",
        release_id="next-release",
        dry_run=False,
    )
    plan = install_zermes.build_update_candidate_plan(
        args,
        source,
        candidate_id="candidate-one",
    )
    candidate_source = Path(plan.source_dir)
    candidate_source.mkdir(parents=True)
    (candidate_source / "README.md").write_text("candidate", encoding="utf-8")
    launcher_source = candidate_source / "launcher" / "zermes_launcher.py"
    launcher_source.parent.mkdir()
    launcher_source.write_text("# candidate launcher\n", encoding="utf-8")
    return plan


def test_build_update_candidate_no_activate_leaves_active_unchanged(monkeypatch, tmp_path):
    source_dir = tmp_path / "checkout"
    source_dir.mkdir()
    args = argparse.Namespace(
        prefix=tmp_path / "app",
        data_dir=tmp_path / "data",
        source=source_dir,
        current_source=False,
        release_id="next-release",
        non_interactive=True,
        force=False,
        dry_run=False,
        install_deps=False,
        skip_verify=True,
        restart=False,
        activate=False,
    )

    monkeypatch.setattr(install_zermes, "sync_source_to_release", lambda *_a, **_k: [])
    monkeypatch.setattr(
        install_zermes,
        "create_virtual_environment",
        lambda *_a, **_k: install_zermes.CommandResult(command=(), returncode=0),
    )

    state = install_zermes.build_update_candidate(
        args,
        repo_root=tmp_path / "repo",
        candidate_id="candidate-one",
    )

    assert state["status"] == "ready"
    assert not (tmp_path / "app" / "runtime" / "active.json").exists()


def test_activate_update_candidate_writes_active_and_previous(tmp_path):
    source = _source_update_activate(tmp_path)
    plan = _plan_update_activate(tmp_path, source)
    old_active = {
        "release_id": "old-release",
        "source_path": str(tmp_path / "app" / "runtime" / "releases" / "old-release" / "source"),
    }
    install_zermes.atomic_write_json(Path(plan.active_path), old_active)

    state = install_zermes.activate_update_candidate(
        plan,
        source,
        candidate_id="candidate-one",
    )

    release_dir = tmp_path / "app" / "runtime" / "releases" / "next-release"
    active = json.loads(Path(plan.active_path).read_text(encoding="utf-8"))
    previous = json.loads(Path(plan.previous_path).read_text(encoding="utf-8"))
    assert state["status"] == "activated"
    assert state["activated"] is True
    assert (release_dir / "source" / "README.md").read_text(encoding="utf-8") == "candidate"
    assert active["release_id"] == "next-release"
    assert active["source_path"] == str((release_dir / "source").resolve())
    assert active["build_path"] == str((release_dir / "build").resolve())
    assert active["source_repo"]["path"] == source.path
    assert "candidate_commit" in active
    assert previous == old_active


def test_activate_update_candidate_does_not_delete_old_release(tmp_path):
    source = _source_update_activate(tmp_path)
    plan = _plan_update_activate(tmp_path, source)
    old_release_marker = tmp_path / "app" / "runtime" / "releases" / "old-release" / "keep.txt"
    old_release_marker.parent.mkdir(parents=True)
    old_release_marker.write_text("keep", encoding="utf-8")
    install_zermes.atomic_write_json(Path(plan.active_path), {"release_id": "old-release"})

    install_zermes.activate_update_candidate(
        plan,
        source,
        candidate_id="candidate-one",
    )

    assert old_release_marker.read_text(encoding="utf-8") == "keep"



# From test_update_build.py

import argparse
import json
from pathlib import Path

import pytest

from scripts import install_zermes


def _args_update_build(tmp_path, source):
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
    args = _args_update_build(tmp_path, source)
    calls: list[str] = []

    def record(name):
        def wrapper(*_args_update_build, **_kwargs):
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
    args = _args_update_build(tmp_path, source)

    def fail_sync(*_args_update_build, **_kwargs):
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
    args = _args_update_build(tmp_path, source)
    args.dry_run = True

    state = install_zermes.build_update_candidate(
        args,
        repo_root=tmp_path / "repo",
        candidate_id="candidate-one",
    )

    assert state["status"] == "ready"
    assert not (tmp_path / "app" / "runtime" / "active.json").exists()
    assert not (tmp_path / "app" / "runtime" / "candidates" / "candidate-one").exists()



# From test_update_source.py

import argparse
import json
from pathlib import Path

import pytest

from scripts import install_zermes


def _args_update_source(tmp_path, **overrides):
    """Build update args with explicit defaults for source resolution tests."""

    values = {
        "prefix": tmp_path / "app",
        "source": None,
        "current_source": False,
        "non_interactive": True,
        "force": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_resolve_update_source_uses_explicit_source(tmp_path):
    source = tmp_path / "checkout"
    source.mkdir()

    resolved = install_zermes.resolve_update_source(
        _args_update_source(tmp_path, source=source),
        repo_root=tmp_path / "repo",
    )

    assert resolved.kind == "explicit"
    assert Path(resolved.path) == source.resolve()


def test_resolve_update_source_uses_current_source(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    resolved = install_zermes.resolve_update_source(
        _args_update_source(tmp_path, current_source=True),
        repo_root=repo_root,
    )

    assert resolved.kind == "current-source"
    assert Path(resolved.path) == repo_root.resolve()


def test_resolve_update_source_requires_source_in_non_interactive_mode(tmp_path):
    with pytest.raises(ValueError, match="requires --source or --current-source"):
        install_zermes.resolve_update_source(_args_update_source(tmp_path), repo_root=tmp_path / "repo")


def test_resolve_update_source_rejects_active_release_source_without_force(tmp_path):
    active_source = tmp_path / "app" / "runtime" / "releases" / "one" / "source"
    active_source.mkdir(parents=True)
    active_path = install_zermes.active_metadata_path(tmp_path / "app")
    active_path.parent.mkdir(parents=True, exist_ok=True)
    active_path.write_text(
        json.dumps({"release_id": "one", "source_path": str(active_source)}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="active release source"):
        install_zermes.resolve_update_source(
            _args_update_source(tmp_path, source=active_source),
            repo_root=tmp_path / "repo",
        )


def test_resolve_update_source_allows_active_release_source_with_force(tmp_path):
    active_source = tmp_path / "app" / "runtime" / "releases" / "one" / "source"
    active_source.mkdir(parents=True)
    active_path = install_zermes.active_metadata_path(tmp_path / "app")
    active_path.parent.mkdir(parents=True, exist_ok=True)
    active_path.write_text(
        json.dumps({"release_id": "one", "source_path": str(active_source)}),
        encoding="utf-8",
    )

    resolved = install_zermes.resolve_update_source(
        _args_update_source(tmp_path, source=active_source, force=True),
        repo_root=tmp_path / "repo",
    )

    assert resolved.active_release_id == "one"
    assert Path(resolved.path) == active_source.resolve()



# From test_update_state.py

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path

from scripts import install_zermes


def _args_update_state(tmp_path, **overrides):
    """Build update args with explicit defaults for candidate tests."""

    values = {
        "prefix": tmp_path / "app",
        "data_dir": tmp_path / "data",
        "release_id": "next-release",
        "dry_run": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _source_update_state(tmp_path):
    """Return a resolved source record without reading the real workspace."""

    checkout = tmp_path / "checkout"
    checkout.mkdir()
    return install_zermes.UpdateSource(
        kind="explicit",
        path=str(checkout.resolve()),
        active_release_id="source-install",
        active_source_path=None,
    )


def test_default_candidate_id_uses_injected_timestamp():
    now = datetime(2026, 5, 10, 12, 0, 1, tzinfo=UTC)

    assert install_zermes.default_candidate_id(now=now) == "update-20260510-120001"


def test_update_candidate_plan_uses_candidate_layout(tmp_path):
    plan = install_zermes.build_update_candidate_plan(
        _args_update_state(tmp_path),
        _source_update_state(tmp_path),
        candidate_id="candidate-one",
    )

    candidate_dir = tmp_path / "app" / "runtime" / "candidates" / "candidate-one"
    assert Path(plan.release_dir) == candidate_dir.resolve()
    assert Path(plan.source_dir) == (candidate_dir / "source").resolve()
    assert Path(plan.venv_dir) == (candidate_dir / "venv").resolve()
    assert Path(plan.build_dir) == (candidate_dir / "build").resolve()
    assert plan.release_id == "next-release"


def test_create_candidate_directories_dry_run_does_not_write(tmp_path):
    plan = install_zermes.build_update_candidate_plan(
        _args_update_state(tmp_path),
        _source_update_state(tmp_path),
        candidate_id="candidate-one",
    )

    directories = install_zermes.create_candidate_directories(plan, dry_run=True)

    assert directories
    assert not Path(plan.release_dir).exists()


def test_write_update_state_writes_candidate_and_runtime_state(tmp_path):
    source = _source_update_state(tmp_path)
    plan = install_zermes.build_update_candidate_plan(
        _args_update_state(tmp_path),
        source,
        candidate_id="candidate-one",
    )
    install_zermes.create_candidate_directories(plan)
    state = install_zermes.build_update_state(
        plan,
        source,
        candidate_id="candidate-one",
        status="ready",
        restart_requested=True,
    )

    payload = install_zermes.write_update_state(plan, state)

    candidate_payload = json.loads(
        (Path(plan.release_dir) / "update-state.json").read_text(encoding="utf-8")
    )
    runtime_payload = json.loads(
        install_zermes.runtime_update_state_path(Path(plan.prefix)).read_text(
            encoding="utf-8"
        )
    )
    assert payload == candidate_payload == runtime_payload
    assert payload == {
        "mode": "update",
        "candidate_id": "candidate-one",
        "source_kind": "explicit",
        "source_path": source.path,
        "old_release_id": "source-install",
        "new_release_id": "next-release",
        "status": "ready",
        "activated": False,
        "restart_requested": True,
        "error": None,
    }


def test_write_update_state_dry_run_does_not_write(tmp_path):
    source = _source_update_state(tmp_path)
    plan = install_zermes.build_update_candidate_plan(
        _args_update_state(tmp_path),
        source,
        candidate_id="candidate-one",
    )
    state = install_zermes.build_update_state(plan, source, candidate_id="candidate-one")

    payload = install_zermes.write_update_state(plan, state, dry_run=True)

    assert payload["candidate_id"] == "candidate-one"
    assert not (Path(plan.release_dir) / "update-state.json").exists()
    assert not install_zermes.runtime_update_state_path(Path(plan.prefix)).exists()

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts import install_zermes


def _source(tmp_path):
    """Create a resolved source record for activation tests."""

    checkout = tmp_path / "checkout"
    checkout.mkdir()
    return install_zermes.UpdateSource(
        kind="explicit",
        path=str(checkout.resolve()),
        active_release_id="old-release",
        active_source_path=None,
    )


def _plan(tmp_path, source):
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
    source = _source(tmp_path)
    plan = _plan(tmp_path, source)
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
    assert previous == old_active


def test_activate_update_candidate_does_not_delete_old_release(tmp_path):
    source = _source(tmp_path)
    plan = _plan(tmp_path, source)
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

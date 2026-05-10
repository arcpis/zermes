from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path

from scripts import install_zermes


def _args(tmp_path, **overrides):
    """Build update args with explicit defaults for candidate tests."""

    values = {
        "prefix": tmp_path / "app",
        "data_dir": tmp_path / "data",
        "release_id": "next-release",
        "dry_run": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _source(tmp_path):
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
        _args(tmp_path),
        _source(tmp_path),
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
        _args(tmp_path),
        _source(tmp_path),
        candidate_id="candidate-one",
    )

    directories = install_zermes.create_candidate_directories(plan, dry_run=True)

    assert directories
    assert not Path(plan.release_dir).exists()


def test_write_update_state_writes_candidate_and_runtime_state(tmp_path):
    source = _source(tmp_path)
    plan = install_zermes.build_update_candidate_plan(
        _args(tmp_path),
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
    source = _source(tmp_path)
    plan = install_zermes.build_update_candidate_plan(
        _args(tmp_path),
        source,
        candidate_id="candidate-one",
    )
    state = install_zermes.build_update_state(plan, source, candidate_id="candidate-one")

    payload = install_zermes.write_update_state(plan, state, dry_run=True)

    assert payload["candidate_id"] == "candidate-one"
    assert not (Path(plan.release_dir) / "update-state.json").exists()
    assert not install_zermes.runtime_update_state_path(Path(plan.prefix)).exists()

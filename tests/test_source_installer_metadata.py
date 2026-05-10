from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path

from scripts import install_zermes


def _plan(tmp_path):
    args = argparse.Namespace(
        prefix=tmp_path / "app",
        data_dir=tmp_path / "data",
        release_id="source-install",
        language="zh-CN",
        dry_run=False,
        no_venv=False,
        python=None,
    )
    return install_zermes.build_plan(args, repo_root=tmp_path / "repo")


def test_release_metadata_contains_runtime_fields(tmp_path):
    plan = _plan(tmp_path)
    now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)

    metadata = install_zermes.release_metadata(plan, now=now)

    assert metadata == {
        "release_id": "source-install",
        "install_prefix": plan.prefix,
        "data_dir": plan.data_dir,
        "source_path": plan.source_dir,
        "venv_path": plan.venv_dir,
        "python_path": plan.python_path,
        "created_at": "2026-05-10T12:00:00+00:00",
        "installer_version": "source-installer-v1",
    }


def test_atomic_write_json_writes_complete_json(tmp_path):
    path = tmp_path / "runtime" / "active.json"

    install_zermes.atomic_write_json(path, {"release_id": "one"})

    assert json.loads(path.read_text(encoding="utf-8")) == {"release_id": "one"}
    assert not (path.parent / ".active.json.tmp").exists()


def test_write_release_metadata_writes_metadata_and_active(tmp_path):
    plan = _plan(tmp_path)
    now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)

    metadata = install_zermes.write_release_metadata(plan, now=now)

    metadata_path = Path(plan.release_dir) / "metadata.json"
    assert json.loads(metadata_path.read_text(encoding="utf-8")) == metadata
    assert json.loads(Path(plan.active_path).read_text(encoding="utf-8")) == metadata
    assert not Path(plan.previous_path).exists()


def test_write_release_metadata_preserves_previous_active(tmp_path):
    plan = _plan(tmp_path)
    active_path = Path(plan.active_path)
    active_path.parent.mkdir(parents=True)
    install_zermes.atomic_write_json(active_path, {"release_id": "old"})

    install_zermes.write_release_metadata(plan)

    assert json.loads(Path(plan.previous_path).read_text(encoding="utf-8")) == {
        "release_id": "old"
    }

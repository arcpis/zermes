from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from scripts import install_zermes


def _plan(tmp_path, repo_root):
    args = argparse.Namespace(
        prefix=tmp_path / "app",
        data_dir=tmp_path / "data",
        release_id="source-install",
        language="zh-CN",
        dry_run=False,
    )
    return install_zermes.build_plan(args, repo_root=repo_root)


def test_sync_source_to_release_copies_files_and_excludes_local_dirs(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("hello", encoding="utf-8")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "module.py").write_text("print('ok')", encoding="utf-8")
    (repo / ".git").mkdir()
    (repo / ".git" / "HEAD").write_text("ignored", encoding="utf-8")
    (repo / "venv").mkdir()
    (repo / "venv" / "pyvenv.cfg").write_text("ignored", encoding="utf-8")
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "dep.js").write_text("ignored", encoding="utf-8")

    plan = _plan(tmp_path, repo)
    copied = install_zermes.sync_source_to_release(plan)

    assert copied
    target = Path(plan.source_dir)
    assert (target / "README.md").read_text(encoding="utf-8") == "hello"
    assert (target / "pkg" / "module.py").read_text(encoding="utf-8") == "print('ok')"
    assert not (target / ".git").exists()
    assert not (target / "venv").exists()
    assert not (target / "node_modules").exists()


def test_sync_source_to_release_preserves_unknown_target_files(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("hello", encoding="utf-8")
    plan = _plan(tmp_path, repo)
    target = Path(plan.source_dir)
    target.mkdir(parents=True)
    unknown = target / "keep.txt"
    unknown.write_text("keep", encoding="utf-8")

    install_zermes.sync_source_to_release(plan)

    assert unknown.read_text(encoding="utf-8") == "keep"


def test_sync_source_to_release_dry_run_does_not_write(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("hello", encoding="utf-8")
    plan = _plan(tmp_path, repo)

    copied = install_zermes.sync_source_to_release(plan, dry_run=True)

    assert copied == []
    assert not Path(plan.source_dir).exists()


def test_sync_source_to_release_rejects_target_inside_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    args = argparse.Namespace(
        prefix=repo / "install",
        data_dir=tmp_path / "data",
        release_id="source-install",
        language="zh-CN",
        dry_run=False,
    )
    plan = install_zermes.build_plan(args, repo_root=repo)

    with pytest.raises(ValueError, match="inside the repository root"):
        install_zermes.sync_source_to_release(plan)

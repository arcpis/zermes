from __future__ import annotations

import argparse
from pathlib import Path

from scripts import install_zermes


def _plan(tmp_path):
    args = argparse.Namespace(
        prefix=tmp_path / "app",
        data_dir=tmp_path / "data",
        release_id="source-install",
        language="zh-CN",
        dry_run=False,
    )
    return install_zermes.build_plan(args, repo_root=tmp_path / "repo")


def test_create_install_directories(tmp_path):
    plan = _plan(tmp_path)

    directories = install_zermes.create_install_directories(plan)

    for directory in directories:
        assert directory.is_dir()
    assert Path(plan.source_dir).is_dir()
    assert Path(plan.build_dir).is_dir()
    assert Path(plan.bin_dir).is_dir()


def test_create_install_directories_is_idempotent(tmp_path):
    plan = _plan(tmp_path)
    unknown_file = Path(plan.prefix) / "keep.txt"
    Path(plan.prefix).mkdir(parents=True)
    unknown_file.write_text("do not delete", encoding="utf-8")

    install_zermes.create_install_directories(plan)
    install_zermes.create_install_directories(plan)

    assert unknown_file.read_text(encoding="utf-8") == "do not delete"


def test_create_install_directories_dry_run_does_not_write(tmp_path):
    plan = _plan(tmp_path)

    directories = install_zermes.create_install_directories(plan, dry_run=True)

    assert directories
    assert not Path(plan.prefix).exists()

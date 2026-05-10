from __future__ import annotations

import argparse
import os
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


def test_posix_launcher_uses_release_python_and_hermes_home(tmp_path):
    plan = _plan(tmp_path)

    text = install_zermes.posix_launcher_text(plan)

    assert text.startswith("#!/usr/bin/env sh\n")
    assert f'export HERMES_HOME="{plan.data_dir}"' in text
    assert f'exec "{plan.python_path}" -m hermes_cli.main "$@"' in text


def test_windows_launcher_uses_release_python_and_hermes_home(tmp_path):
    plan = _plan(tmp_path)

    text = install_zermes.windows_launcher_text(plan)

    assert text.startswith("@echo off\r\n")
    assert f"set HERMES_HOME={plan.data_dir}\r\n" in text
    assert f'"{plan.python_path}" -m hermes_cli.main %*\r\n' in text


def test_create_launcher_scripts_writes_posix_and_windows_launchers(tmp_path):
    plan = _plan(tmp_path)

    paths = install_zermes.create_launcher_scripts(plan)

    assert paths == (Path(plan.bin_dir) / "zermes", Path(plan.bin_dir) / "zermes.bat")
    assert (Path(plan.bin_dir) / "zermes").read_text(encoding="utf-8") == (
        install_zermes.posix_launcher_text(plan)
    )
    assert (Path(plan.bin_dir) / "zermes.bat").read_bytes().decode("utf-8") == (
        install_zermes.windows_launcher_text(plan)
    )
    assert os.access(Path(plan.bin_dir) / "zermes", os.X_OK)


def test_create_launcher_scripts_can_be_disabled(tmp_path):
    plan = _plan(tmp_path)

    paths = install_zermes.create_launcher_scripts(plan, create_launchers=False)

    assert paths == ()
    assert not Path(plan.bin_dir).exists()


def test_create_launcher_scripts_dry_run_does_not_write(tmp_path):
    plan = _plan(tmp_path)

    paths = install_zermes.create_launcher_scripts(plan, dry_run=True)

    assert paths == (Path(plan.bin_dir) / "zermes", Path(plan.bin_dir) / "zermes.bat")
    assert not Path(plan.bin_dir).exists()

from __future__ import annotations

import argparse
from pathlib import Path

from scripts import install_zermes


def _plan(tmp_path, *, no_venv=False, python_path=None):
    args = argparse.Namespace(
        prefix=tmp_path / "app",
        data_dir=tmp_path / "data",
        release_id="source-install",
        language="zh-CN",
        dry_run=False,
        no_venv=no_venv,
        python=python_path,
    )
    return install_zermes.build_plan(args, repo_root=tmp_path / "repo")


def test_venv_python_path_by_platform():
    venv = Path("/opt/zermes/venv")

    assert install_zermes.venv_python_path(venv, platform="linux") == (
        venv / "bin" / "python"
    )
    assert install_zermes.venv_python_path(venv, platform="darwin") == (
        venv / "bin" / "python"
    )
    assert install_zermes.venv_python_path(venv, platform="win32") == (
        venv / "Scripts" / "python.exe"
    )


def test_build_plan_uses_release_venv_python_by_default(tmp_path):
    plan = _plan(tmp_path)

    assert plan.use_venv is True
    assert Path(plan.python_path) == install_zermes.venv_python_path(Path(plan.venv_dir)).resolve()


def test_build_plan_no_venv_uses_selected_python(tmp_path):
    selected_python = tmp_path / "python"
    selected_python.write_text("", encoding="utf-8")

    plan = _plan(tmp_path, no_venv=True, python_path=selected_python)

    assert plan.use_venv is False
    assert Path(plan.python_path) == selected_python.resolve()


def test_create_virtual_environment_uses_command_runner(monkeypatch, tmp_path):
    calls = []
    plan = _plan(tmp_path)

    def fake_run_command(command, *, dry_run=False, cwd=None):
        calls.append((command, dry_run, cwd))
        return install_zermes.CommandResult(command=tuple(command), returncode=0, dry_run=dry_run)

    monkeypatch.setattr(install_zermes, "run_command", fake_run_command)

    result = install_zermes.create_virtual_environment(
        plan,
        python_executable="/usr/bin/python3.11",
        dry_run=True,
    )

    assert result.dry_run is True
    assert calls == [
        (
            ["/usr/bin/python3.11", "-m", "venv", plan.venv_dir],
            True,
            None,
        )
    ]


def test_create_virtual_environment_skips_when_no_venv(monkeypatch, tmp_path):
    plan = _plan(tmp_path, no_venv=True)

    def fail_run_command(*_args, **_kwargs):
        raise AssertionError("run_command should not be called")

    monkeypatch.setattr(install_zermes, "run_command", fail_run_command)

    result = install_zermes.create_virtual_environment(plan)

    assert result.returncode == 0
    assert result.command == ()

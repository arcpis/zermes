from __future__ import annotations

import argparse
from pathlib import Path

import pytest

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
    plan = install_zermes.build_plan(args, repo_root=tmp_path / "repo")
    Path(plan.source_dir).mkdir(parents=True)
    return plan


def test_dependency_install_commands_prefers_uv_lock(tmp_path):
    plan = _plan(tmp_path)
    (Path(plan.source_dir) / "uv.lock").write_text("", encoding="utf-8")

    assert install_zermes.dependency_install_commands(plan) == (
        ["uv", "sync", "--all-extras", "--locked"],
        ["uv", "pip", "install", "-e", ".[all]"],
        ["uv", "pip", "install", "-e", "."],
        [plan.python_path, "-m", "pip", "install", "-e", ".[all]"],
        [plan.python_path, "-m", "pip", "install", "-e", "."],
    )


def test_dependency_install_commands_without_lock_uses_editable_fallbacks(tmp_path):
    plan = _plan(tmp_path)

    assert install_zermes.dependency_install_commands(plan) == (
        ["uv", "pip", "install", "-e", ".[all]"],
        ["uv", "pip", "install", "-e", "."],
        [plan.python_path, "-m", "pip", "install", "-e", ".[all]"],
        [plan.python_path, "-m", "pip", "install", "-e", "."],
    )


def test_install_dependencies_uses_locked_sync_when_available(monkeypatch, tmp_path):
    plan = _plan(tmp_path)
    (Path(plan.source_dir) / "uv.lock").write_text("", encoding="utf-8")
    calls = []

    def fake_run(command, *, cwd=None, env=None, dry_run=False):
        calls.append((command, cwd, env, dry_run))
        return install_zermes.CommandResult(command=tuple(command), returncode=0)

    monkeypatch.setattr(install_zermes, "run_command", fake_run)

    result = install_zermes.install_python_dependencies(plan)

    assert result.returncode == 0
    assert calls == [
        (
            [
                "uv",
                "sync",
                "--all-extras",
                "--locked",
            ],
            Path(plan.source_dir),
            {"UV_PROJECT_ENVIRONMENT": plan.venv_dir},
            False,
        )
    ]


def test_install_dependencies_falls_back_from_locked_sync(monkeypatch, tmp_path):
    plan = _plan(tmp_path)
    (Path(plan.source_dir) / "uv.lock").write_text("", encoding="utf-8")
    calls = []

    def fake_run(command, *, cwd=None, env=None, dry_run=False):
        calls.append(command)
        if command[:2] == ["uv", "sync"]:
            raise install_zermes.InstallerCommandError(
                install_zermes.CommandResult(command=tuple(command), returncode=1)
            )
        return install_zermes.CommandResult(command=tuple(command), returncode=0)

    monkeypatch.setattr(install_zermes, "run_command", fake_run)

    result = install_zermes.install_python_dependencies(plan)

    assert result.command == ("uv", "pip", "install", "-e", ".[all]")
    assert calls == [
        ["uv", "sync", "--all-extras", "--locked"],
        ["uv", "pip", "install", "-e", ".[all]"],
    ]


def test_install_dependencies_falls_back_to_base_editable(monkeypatch, tmp_path):
    plan = _plan(tmp_path)
    calls = []

    def fake_run(command, *, cwd=None, env=None, dry_run=False):
        calls.append(command)
        if command == ["uv", "pip", "install", "-e", ".[all]"]:
            raise install_zermes.InstallerCommandError(
                install_zermes.CommandResult(command=tuple(command), returncode=1)
            )
        return install_zermes.CommandResult(command=tuple(command), returncode=0)

    monkeypatch.setattr(install_zermes, "run_command", fake_run)

    result = install_zermes.install_python_dependencies(plan)

    assert result.command == ("uv", "pip", "install", "-e", ".")
    assert calls == [
        ["uv", "pip", "install", "-e", ".[all]"],
        ["uv", "pip", "install", "-e", "."],
    ]


def test_install_dependencies_falls_back_to_python_pip(monkeypatch, tmp_path):
    plan = _plan(tmp_path)
    calls = []

    def fake_run(command, *, cwd=None, env=None, dry_run=False):
        calls.append(command)
        if command[0] == "uv":
            raise install_zermes.InstallerCommandError(
                install_zermes.CommandResult(command=tuple(command), returncode=1)
            )
        return install_zermes.CommandResult(command=tuple(command), returncode=0)

    monkeypatch.setattr(install_zermes, "run_command", fake_run)

    result = install_zermes.install_python_dependencies(plan)

    assert result.command == (plan.python_path, "-m", "pip", "install", "-e", ".[all]")
    assert calls == [
        ["uv", "pip", "install", "-e", ".[all]"],
        ["uv", "pip", "install", "-e", "."],
        [plan.python_path, "-m", "pip", "install", "-e", ".[all]"],
    ]


def test_install_dependencies_can_be_skipped(monkeypatch, tmp_path):
    plan = _plan(tmp_path)

    def fail_run(*_args, **_kwargs):
        raise AssertionError("run_command should not be called")

    monkeypatch.setattr(install_zermes, "run_command", fail_run)

    result = install_zermes.install_python_dependencies(plan, install_deps=False)

    assert result.command == ()
    assert result.returncode == 0


def test_install_dependencies_raises_last_failure(monkeypatch, tmp_path):
    plan = _plan(tmp_path)

    def fake_run(command, *, cwd=None, env=None, dry_run=False):
        raise install_zermes.InstallerCommandError(
            install_zermes.CommandResult(command=tuple(command), returncode=5, stderr="broken")
        )

    monkeypatch.setattr(install_zermes, "run_command", fake_run)

    with pytest.raises(install_zermes.InstallerCommandError) as exc_info:
        install_zermes.install_python_dependencies(plan)

    assert exc_info.value.result.returncode == 5
    assert exc_info.value.result.stderr == "broken"

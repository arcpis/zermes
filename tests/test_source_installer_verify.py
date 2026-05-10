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
        no_venv=False,
        python=None,
    )
    return install_zermes.build_plan(args, repo_root=tmp_path / "repo")


def test_verification_commands_use_release_python_and_existing_cli(tmp_path):
    plan = _plan(tmp_path)

    assert install_zermes.verification_commands(plan) == (
        [plan.python_path, "-c", "import sys; print(sys.version)"],
        [plan.python_path, "-m", "pip", "--version"],
        [plan.python_path, "-m", "hermes_cli.main", "--help"],
    )


def test_verify_installed_runtime_runs_all_commands(monkeypatch, tmp_path):
    plan = _plan(tmp_path)
    calls = []

    def fake_run(command, *, cwd=None, env=None, dry_run=False):
        calls.append((command, cwd, dry_run))
        return install_zermes.CommandResult(command=tuple(command), returncode=0)

    monkeypatch.setattr(install_zermes, "run_command", fake_run)

    results = install_zermes.verify_installed_runtime(plan)

    assert len(results) == 3
    assert calls == [
        (command, Path(plan.source_dir), False)
        for command in install_zermes.verification_commands(plan)
    ]


def test_verify_installed_runtime_can_be_skipped(monkeypatch, tmp_path):
    plan = _plan(tmp_path)

    def fail_run(*_args, **_kwargs):
        raise AssertionError("run_command should not be called")

    monkeypatch.setattr(install_zermes, "run_command", fail_run)

    assert install_zermes.verify_installed_runtime(plan, skip_verify=True) == ()


def test_verify_installed_runtime_propagates_command_failure(monkeypatch, tmp_path):
    plan = _plan(tmp_path)

    def fake_run(command, *, cwd=None, env=None, dry_run=False):
        raise install_zermes.InstallerCommandError(
            install_zermes.CommandResult(command=tuple(command), returncode=3, stderr="bad")
        )

    monkeypatch.setattr(install_zermes, "run_command", fake_run)

    try:
        install_zermes.verify_installed_runtime(plan)
    except install_zermes.InstallerCommandError as exc:
        assert exc.result.returncode == 3
        assert exc.result.stderr == "bad"
    else:
        raise AssertionError("expected InstallerCommandError")

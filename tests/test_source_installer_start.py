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


def test_should_start_honors_start_flag():
    args = argparse.Namespace(start=True, non_interactive=True)

    assert install_zermes.should_start_after_install(args) is True


def test_should_start_honors_no_start_flag():
    args = argparse.Namespace(start=False, non_interactive=False)

    assert install_zermes.should_start_after_install(args) is False


def test_should_start_non_interactive_defaults_false():
    args = argparse.Namespace(start=None, non_interactive=True)

    assert install_zermes.should_start_after_install(args) is False


def test_should_start_interactive_uses_answer():
    args = argparse.Namespace(start=None, non_interactive=False)

    assert install_zermes.should_start_after_install(args, input_fn=lambda _prompt: "y") is True
    assert install_zermes.should_start_after_install(args, input_fn=lambda _prompt: "") is False


def test_start_zermes_uses_generated_launcher(monkeypatch, tmp_path):
    plan = _plan(tmp_path)
    calls = []

    def fake_run(command, *, cwd=None, env=None, dry_run=False):
        calls.append((command, dry_run))
        return install_zermes.CommandResult(command=tuple(command), returncode=0, dry_run=dry_run)

    monkeypatch.setattr(install_zermes, "run_command", fake_run)

    result = install_zermes.start_zermes(plan, start=True, dry_run=True)

    assert result.dry_run is True
    assert calls == [([str(Path(plan.bin_dir) / "zermes")], True)]


def test_start_zermes_skips_when_disabled(monkeypatch, tmp_path):
    plan = _plan(tmp_path)

    def fail_run(*_args, **_kwargs):
        raise AssertionError("run_command should not be called")

    monkeypatch.setattr(install_zermes, "run_command", fail_run)

    result = install_zermes.start_zermes(plan, start=False)

    assert result.command == ()
    assert result.returncode == 0

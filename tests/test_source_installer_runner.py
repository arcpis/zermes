from __future__ import annotations

import subprocess

import pytest

from scripts import install_zermes


def test_run_command_dry_run_does_not_execute(monkeypatch):
    def fail_run(*_args, **_kwargs):
        raise AssertionError("subprocess.run should not be called")

    monkeypatch.setattr(subprocess, "run", fail_run)

    result = install_zermes.run_command(["python", "--version"], dry_run=True)

    assert result.command == ("python", "--version")
    assert result.returncode == 0
    assert result.dry_run is True


def test_run_command_uses_argv_form(monkeypatch, tmp_path):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = install_zermes.run_command(["python", "--version"], cwd=tmp_path)

    assert result.stdout == "ok"
    assert calls == [
        (
            ["python", "--version"],
            {
                "cwd": tmp_path,
                "text": True,
                "capture_output": True,
                "check": False,
                "shell": False,
            },
        )
    ]


def test_run_command_failure_raises_install_error(monkeypatch):
    def fake_run(command, **_kwargs):
        return subprocess.CompletedProcess(command, 7, stdout="", stderr="broken")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(install_zermes.InstallerCommandError) as exc_info:
        install_zermes.run_command(["python", "-m", "venv", "venv"])

    assert exc_info.value.result.returncode == 7
    assert exc_info.value.result.stderr == "broken"


def test_has_command_uses_shutil_which(monkeypatch):
    monkeypatch.setattr(install_zermes.shutil, "which", lambda name: f"/bin/{name}")

    assert install_zermes.has_command("uv") is True


def test_has_command_returns_false_for_missing(monkeypatch):
    monkeypatch.setattr(install_zermes.shutil, "which", lambda _name: None)

    assert install_zermes.has_command("uv") is False

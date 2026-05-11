from __future__ import annotations



# From test_entry.py

import json
from pathlib import Path

import install
from scripts import install_zermes


def test_dry_run_non_interactive_returns_success(tmp_path, capsys):
    prefix = tmp_path / "zermes-install"
    data_dir = tmp_path / "zermes-data"

    exit_code = install_zermes.main(
        [
            "install",
            "--dry-run",
            "--non-interactive",
            "--prefix",
            str(prefix),
            "--data-dir",
            str(data_dir),
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert Path(payload["prefix"]) == prefix.resolve()
    assert Path(payload["data_dir"]) == data_dir.resolve()
    assert not prefix.exists()
    assert not data_dir.exists()


def test_root_install_entry_delegates_to_installer(monkeypatch):
    calls: list[list[str] | None] = []

    def fake_main(argv):
        calls.append(argv)
        return 17

    monkeypatch.setattr(install_zermes, "main", fake_main)

    assert install.main(["install", "--dry-run"]) == 17
    assert calls == [["install", "--dry-run"]]


def test_dry_run_defaults_do_not_create_default_prefix(capsys):
    exit_code = install_zermes.main(["install", "--dry-run", "--non-interactive"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["language"] == "zh-CN"
    assert payload["release_id"] == "source-install"


def test_non_interactive_requires_explicit_command():
    try:
        install_zermes.main(["--dry-run", "--non-interactive"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected parser failure")


def test_parser_supports_install_update_and_rollback_commands(tmp_path):
    parser = install_zermes.build_parser()

    install_args = parser.parse_args(["install", "--prefix", str(tmp_path / "app")])
    update_args = parser.parse_args(
        [
            "update",
            "--prefix",
            str(tmp_path / "app"),
            "--source",
            str(tmp_path / "source"),
            "--release-id",
            "next",
            "--no-activate",
            "--restart",
        ]
    )
    rollback_args = parser.parse_args(["rollback", "--prefix", str(tmp_path / "app")])

    assert install_args.command == "install"
    assert update_args.command == "update"
    assert update_args.source == tmp_path / "source"
    assert update_args.release_id == "next"
    assert update_args.activate is False
    assert update_args.restart is True
    assert rollback_args.command == "rollback"



# From test_i18n.py

import argparse

import pytest

from scripts import install_zermes


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, "zh-CN"),
        ("", "zh-CN"),
        ("1", "zh-CN"),
        ("2", "en-US"),
        ("zh-CN", "zh-CN"),
        ("en-US", "en-US"),
    ],
)
def test_normalize_language(raw, expected):
    assert install_zermes.normalize_language(raw) == expected


def test_normalize_language_rejects_unknown():
    with pytest.raises(ValueError, match="unsupported language"):
        install_zermes.normalize_language("fr-FR")


def test_prompt_language_uses_default_on_enter():
    assert install_zermes.prompt_language(lambda _prompt: "") == "zh-CN"


def test_prompt_language_accepts_english_choice():
    assert install_zermes.prompt_language(lambda _prompt: "2") == "en-US"


def test_parser_rejects_unknown_language_choice():
    parser = install_zermes.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["--language", "fr-FR"])


def test_build_plan_defaults_language_for_non_interactive(tmp_path):
    args = argparse.Namespace(
        prefix=tmp_path / "app",
        data_dir=tmp_path / "data",
        release_id="source-install",
        language=None,
        dry_run=True,
    )

    plan = install_zermes.build_plan(args, repo_root=tmp_path / "repo")

    assert plan.language == "zh-CN"



# From test_plan.py

from pathlib import Path

from scripts import install_zermes


def test_default_prefix_by_platform():
    home = Path("/home/example")

    assert install_zermes.default_prefix(platform="linux", home=home) == (
        home / ".local" / "share" / "zermes"
    )
    assert install_zermes.default_prefix(platform="darwin", home=home) == (
        home / "Applications" / "Zermes"
    )
    assert install_zermes.default_prefix(platform="win32", home=home) == (
        home / "AppData" / "Local" / "Zermes"
    )


def test_default_data_dir_uses_hermes_home_compatibility():
    home = Path("/home/example")

    assert install_zermes.default_data_dir(home=home) == home / ".hermes"


def test_plan_computes_runtime_release_paths(tmp_path):
    prefix = tmp_path / "app"
    data_dir = tmp_path / "data"
    parser = install_zermes.build_parser()
    args = parser.parse_args(
        [
            "--dry-run",
            "--non-interactive",
            "--prefix",
            str(prefix),
            "--data-dir",
            str(data_dir),
            "--release-id",
            "source-install",
        ]
    )

    plan = install_zermes.build_plan(args, repo_root=tmp_path / "repo")

    assert Path(plan.runtime_dir) == (prefix / "runtime").resolve()
    assert Path(plan.release_dir) == (
        prefix / "runtime" / "releases" / "source-install"
    ).resolve()
    assert Path(plan.source_dir) == (
        prefix / "runtime" / "releases" / "source-install" / "source"
    ).resolve()
    assert Path(plan.venv_dir) == (
        prefix / "runtime" / "releases" / "source-install" / "venv"
    ).resolve()
    assert Path(plan.build_dir) == (
        prefix / "runtime" / "releases" / "source-install" / "build"
    ).resolve()
    assert Path(plan.bin_dir) == (prefix / "bin").resolve()
    assert Path(plan.active_path) == (prefix / "runtime" / "active.json").resolve()
    assert Path(plan.previous_path) == (prefix / "runtime" / "previous.json").resolve()



# From test_runner.py

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
                "env": None,
                "text": True,
                "capture_output": True,
                "check": False,
                "shell": False,
            },
        )
    ]


def test_run_command_merges_extra_environment(monkeypatch, tmp_path):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setenv("EXISTING_ENV", "kept")
    monkeypatch.setattr(subprocess, "run", fake_run)

    install_zermes.run_command(["uv", "sync"], cwd=tmp_path, env={"UV_PROJECT_ENVIRONMENT": "venv"})

    env = calls[0][1]["env"]
    assert env["EXISTING_ENV"] == "kept"
    assert env["UV_PROJECT_ENVIRONMENT"] == "venv"


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

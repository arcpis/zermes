from __future__ import annotations



# From test_dependencies.py

import argparse
from io import BytesIO
from pathlib import Path
import tarfile
from types import SimpleNamespace

import pytest

from scripts import install_zermes


def _plan_dependencies(tmp_path):
    args = argparse.Namespace(
        prefix=tmp_path / "app",
        data_dir=tmp_path / "data",
        release_id="source-install",
        dry_run=False,
        no_venv=False,
        python=None,
    )
    plan = install_zermes.build_plan(args, repo_root=tmp_path / "repo")
    Path(plan.source_dir).mkdir(parents=True)
    return plan


def test_dependency_install_commands_prefers_uv_lock(tmp_path):
    plan = _plan_dependencies(tmp_path)
    (Path(plan.source_dir) / "uv.lock").write_text("", encoding="utf-8")

    assert install_zermes.dependency_install_commands(plan) == (
        ["uv", "sync", "--all-extras", "--locked"],
        ["uv", "pip", "install", "--python", plan.python_path, "-e", ".[all]"],
        ["uv", "pip", "install", "--python", plan.python_path, "-e", "."],
        [plan.python_path, "-m", "pip", "install", "-e", ".[all]"],
        [plan.python_path, "-m", "pip", "install", "-e", "."],
    )


def test_dependency_install_commands_without_lock_uses_editable_fallbacks(tmp_path):
    plan = _plan_dependencies(tmp_path)

    assert install_zermes.dependency_install_commands(plan) == (
        ["uv", "pip", "install", "--python", plan.python_path, "-e", ".[all]"],
        ["uv", "pip", "install", "--python", plan.python_path, "-e", "."],
        [plan.python_path, "-m", "pip", "install", "-e", ".[all]"],
        [plan.python_path, "-m", "pip", "install", "-e", "."],
    )


def test_install_dependencies_uses_locked_sync_when_available(monkeypatch, tmp_path):
    plan = _plan_dependencies(tmp_path)
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
    plan = _plan_dependencies(tmp_path)
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

    assert result.command == (
        "uv",
        "pip",
        "install",
        "--python",
        plan.python_path,
        "-e",
        ".[all]",
    )
    assert calls == [
        ["uv", "sync", "--all-extras", "--locked"],
        ["uv", "pip", "install", "--python", plan.python_path, "-e", ".[all]"],
    ]


def test_install_dependencies_falls_back_to_base_editable(monkeypatch, tmp_path):
    plan = _plan_dependencies(tmp_path)
    calls = []

    def fake_run(command, *, cwd=None, env=None, dry_run=False):
        calls.append(command)
        if command == ["uv", "pip", "install", "--python", plan.python_path, "-e", ".[all]"]:
            raise install_zermes.InstallerCommandError(
                install_zermes.CommandResult(command=tuple(command), returncode=1)
            )
        return install_zermes.CommandResult(command=tuple(command), returncode=0)

    monkeypatch.setattr(install_zermes, "run_command", fake_run)

    result = install_zermes.install_python_dependencies(plan)

    assert result.command == (
        "uv",
        "pip",
        "install",
        "--python",
        plan.python_path,
        "-e",
        ".",
    )
    assert calls == [
        ["uv", "pip", "install", "--python", plan.python_path, "-e", ".[all]"],
        ["uv", "pip", "install", "--python", plan.python_path, "-e", "."],
    ]


def test_install_dependencies_falls_back_to_python_pip(monkeypatch, tmp_path):
    plan = _plan_dependencies(tmp_path)
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
        ["uv", "pip", "install", "--python", plan.python_path, "-e", ".[all]"],
        ["uv", "pip", "install", "--python", plan.python_path, "-e", "."],
        [plan.python_path, "-m", "pip", "install", "-e", ".[all]"],
    ]


def test_install_dependencies_falls_back_when_uv_is_missing(monkeypatch, tmp_path):
    plan = _plan_dependencies(tmp_path)
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        if command[0] == "uv":
            raise FileNotFoundError("uv")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(install_zermes.subprocess, "run", fake_run)

    result = install_zermes.install_python_dependencies(plan)

    assert result.command == (plan.python_path, "-m", "pip", "install", "-e", ".[all]")
    assert calls == [
        ["uv", "pip", "install", "--python", plan.python_path, "-e", ".[all]"],
        ["uv", "pip", "install", "--python", plan.python_path, "-e", "."],
        [plan.python_path, "-m", "pip", "install", "-e", ".[all]"],
    ]


def test_install_dependencies_can_be_skipped(monkeypatch, tmp_path):
    plan = _plan_dependencies(tmp_path)

    def fail_run(*_args, **_kwargs):
        raise AssertionError("run_command should not be called")

    monkeypatch.setattr(install_zermes, "run_command", fail_run)

    result = install_zermes.install_python_dependencies(plan, install_deps=False)

    assert result.command == ()
    assert result.returncode == 0


def test_install_dependencies_raises_last_failure(monkeypatch, tmp_path):
    plan = _plan_dependencies(tmp_path)

    def fake_run(command, *, cwd=None, env=None, dry_run=False):
        raise install_zermes.InstallerCommandError(
            install_zermes.CommandResult(command=tuple(command), returncode=5, stderr="broken")
        )

    monkeypatch.setattr(install_zermes, "run_command", fake_run)

    with pytest.raises(install_zermes.InstallerCommandError) as exc_info:
        install_zermes.install_python_dependencies(plan)

    assert exc_info.value.result.returncode == 5
    assert exc_info.value.result.stderr == "broken"



# From test_directories.py

import argparse
from pathlib import Path

from scripts import install_zermes


def _plan_directories(tmp_path):
    args = argparse.Namespace(
        prefix=tmp_path / "app",
        data_dir=tmp_path / "data",
        release_id="source-install",
        dry_run=False,
    )
    return install_zermes.build_plan(args, repo_root=tmp_path / "repo")


def test_create_install_directories(tmp_path):
    plan = _plan_directories(tmp_path)

    directories = install_zermes.create_install_directories(plan)

    for directory in directories:
        assert directory.is_dir()
    assert Path(plan.source_dir).is_dir()
    assert Path(plan.build_dir).is_dir()
    assert Path(plan.bin_dir).is_dir()
    assert Path(plan.install_data_dir).is_dir()
    assert not Path(plan.self_evolution_data_dir).exists()
    assert not (Path(plan.install_data_dir) / "tmp").exists()


def test_create_install_directories_is_idempotent(tmp_path):
    plan = _plan_directories(tmp_path)
    unknown_file = Path(plan.prefix) / "keep.txt"
    Path(plan.prefix).mkdir(parents=True)
    unknown_file.write_text("do not delete", encoding="utf-8")

    install_zermes.create_install_directories(plan)
    install_zermes.create_install_directories(plan)

    assert unknown_file.read_text(encoding="utf-8") == "do not delete"
    audit_file = Path(plan.self_evolution_data_dir) / "tasks" / "keep.md"
    audit_file.parent.mkdir(parents=True)
    audit_file.write_text("do not delete", encoding="utf-8")

    install_zermes.create_install_directories(plan)

    assert audit_file.read_text(encoding="utf-8") == "do not delete"


def test_create_install_directories_dry_run_does_not_write(tmp_path):
    plan = _plan_directories(tmp_path)

    directories = install_zermes.create_install_directories(plan, dry_run=True)

    assert directories
    assert not Path(plan.prefix).exists()



# From test_install_workflow.py

import argparse
import json
import sys
from pathlib import Path

from scripts import install_zermes


def _args_install_workflow(tmp_path, **overrides):
    """Build install args for workflow tests without using global defaults."""

    values = {
        "prefix": tmp_path / "app",
        "data_dir": tmp_path / "data",
        "release_id": "source-install",
        "dry_run": False,
        "non_interactive": True,
        "no_venv": False,
        "python": None,
        "install_deps": True,
        "create_launchers": True,
        "global_command": False,
        "global_bin_dir": None,
        "skip_verify": False,
        "start": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_prepare_interactive_install_args_prompts_for_missing_options(tmp_path):
    args = argparse.Namespace(
        prefix=None,
        data_dir=None,
        no_venv=False,
        install_deps=True,
        create_launchers=True,
        global_command=None,
        non_interactive=False,
        dry_run=False,
    )
    answers = iter(
        [
            str(tmp_path / "app"),
            str(tmp_path / "data"),
            "n",
            "n",
            "n",
        ]
    )

    result = install_zermes.prepare_interactive_install_args(
        args,
        input_fn=lambda _prompt: next(answers),
    )

    assert result.prefix == tmp_path / "app"
    assert result.data_dir == tmp_path / "data"
    assert result.no_venv is True
    assert result.install_deps is False
    assert result.create_launchers is False


def test_prepare_interactive_install_args_prompts_for_global_command(tmp_path):
    args = argparse.Namespace(
        prefix=tmp_path / "app",
        data_dir=tmp_path / "data",
        no_venv=True,
        install_deps=False,
        create_launchers=True,
        global_command=None,
        non_interactive=False,
        dry_run=False,
    )

    result = install_zermes.prepare_interactive_install_args(
        args,
        input_fn=lambda _prompt: "y",
    )

    assert result.global_command is True


def test_run_install_workflow_runs_steps_in_order(monkeypatch, tmp_path):
    args = _args_install_workflow(tmp_path)
    calls: list[str] = []

    def record(name, result=None):
        def wrapper(*_args_install_workflow, **_kwargs):
            calls.append(name)
            if result is not None:
                return result
            if name == "sync":
                return [Path("one"), Path("two")]
            if name == "metadata":
                return {"release_id": "source-install"}
            if name == "launchers":
                return (tmp_path / "app" / "bin" / "zermes",)
            if name == "global":
                return install_zermes.GlobalCommandResult(
                    status="skipped",
                    method="none",
                    path=None,
                    message="skipped",
                )
            if name == "verify":
                return ()
            return install_zermes.CommandResult(command=(), returncode=0)

        return wrapper

    monkeypatch.setattr(install_zermes, "create_install_directories", record("dirs"))
    monkeypatch.setattr(install_zermes, "create_data_directory", record("data"))
    monkeypatch.setattr(install_zermes, "sync_source_to_release", record("sync"))
    monkeypatch.setattr(install_zermes, "create_virtual_environment", record("venv"))
    monkeypatch.setattr(install_zermes, "install_python_dependencies", record("deps"))
    monkeypatch.setattr(install_zermes, "write_release_metadata", record("metadata"))
    monkeypatch.setattr(install_zermes, "create_launcher_scripts", record("launchers"))
    monkeypatch.setattr(install_zermes, "configure_global_command", record("global"))
    monkeypatch.setattr(install_zermes, "verify_installed_runtime", record("verify"))

    result = install_zermes.run_install_workflow(args, repo_root=tmp_path / "repo")

    assert calls == [
        "dirs",
        "data",
        "sync",
        "venv",
        "deps",
        "metadata",
        "launchers",
        "global",
        "verify",
    ]
    assert result["status"] == "installed"
    assert [step["step"] for step in result["steps"]] == [
        "create-install-directories",
        "create-data-directory",
        "sync-source",
        "create-virtual-environment",
        "install-python-dependencies",
        "write-release-metadata",
        "create-launchers",
        "configure-global-command",
        "verify-runtime",
    ]
    assert result["global_command"]["status"] == "skipped"


def test_run_install_workflow_dry_run_only_returns_plan(monkeypatch, tmp_path):
    args = _args_install_workflow(tmp_path, dry_run=True)

    def fail_write(*_args_install_workflow, **_kwargs):
        raise AssertionError("dry-run should not execute install steps")

    monkeypatch.setattr(install_zermes, "create_install_directories", fail_write)

    result = install_zermes.run_install_workflow(args, repo_root=tmp_path / "repo")

    assert result["dry_run"] is True
    assert result["release_id"] == "source-install"
    assert not (tmp_path / "app").exists()


def test_main_real_install_outputs_success_json(monkeypatch, tmp_path, capsys):
    prepared_args = []

    def fake_prepare(args, *, input_fn=input):
        args.prefix = tmp_path / "app"
        args.data_dir = tmp_path / "data"
        args.no_venv = True
        args.install_deps = False
        args.create_launchers = False
        prepared_args.append(args)
        return args

    def fake_install(args, *, repo_root, input_fn=input, now=None):
        return {
            "status": "installed",
            "plan": {"prefix": str(args.prefix.resolve())},
            "steps": [],
        }

    monkeypatch.setattr(install_zermes, "prepare_interactive_install_args", fake_prepare)
    monkeypatch.setattr(install_zermes, "run_install_workflow", fake_install)

    exit_code = install_zermes.main(["install"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert prepared_args
    assert payload["status"] == "installed"
    assert Path(payload["plan"]["prefix"]) == (tmp_path / "app").resolve()


def test_run_install_workflow_minimal_real_install(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("hello", encoding="utf-8")
    (repo / "launcher").mkdir()
    (repo / "launcher" / "zermes_launcher.py").write_text("# launcher\n", encoding="utf-8")
    args = _args_install_workflow(
        tmp_path,
        no_venv=True,
        python=Path(sys.executable),
        install_deps=False,
        skip_verify=True,
        start=False,
    )

    result = install_zermes.run_install_workflow(args, repo_root=repo)

    assert result["status"] == "installed"
    assert (tmp_path / "app" / "runtime" / "releases" / "source-install" / "source" / "README.md").read_text(
        encoding="utf-8"
    ) == "hello"
    assert (tmp_path / "app" / "runtime" / "active.json").exists()
    assert (tmp_path / "app" / "bin" / "zermes").exists()
    assert (tmp_path / "data").is_dir()



# From test_launchers.py

import argparse
import os
from pathlib import Path

from scripts import install_zermes


def _plan_launchers(tmp_path):
    args = argparse.Namespace(
        prefix=tmp_path / "app",
        data_dir=tmp_path / "data",
        release_id="source-install",
        dry_run=False,
        no_venv=False,
        python=None,
    )
    return install_zermes.build_plan(args, repo_root=tmp_path / "repo")


def test_posix_launcher_uses_release_python_and_hermes_home(tmp_path):
    plan = _plan_launchers(tmp_path)

    text = install_zermes.posix_launcher_text(plan)

    assert text.startswith("#!/usr/bin/env sh\n")
    assert f'export ZERMES_INSTALL_PREFIX="{plan.prefix}"' in text
    assert f'"{plan.prefix}/launcher/zermes_launcher.py" cli "$@"' in text
    assert "-m hermes_cli.main" not in text


def test_windows_launcher_uses_release_python_and_hermes_home(tmp_path):
    plan = _plan_launchers(tmp_path)

    text = install_zermes.windows_launcher_text(plan)

    assert text.startswith("@echo off\r\n")
    assert f"set ZERMES_INSTALL_PREFIX={plan.prefix}\r\n" in text
    assert "zermes_launcher.py\" cli %*\r\n" in text
    assert "-m hermes_cli.main" not in text


def test_create_launcher_scripts_writes_posix_and_windows_launchers(tmp_path):
    plan = _plan_launchers(tmp_path)
    _write_launcher_source(plan)

    paths = install_zermes.create_launcher_scripts(plan)

    assert paths == (
        Path(plan.prefix) / "launcher" / "zermes_launcher.py",
        Path(plan.bin_dir) / "zermes",
        Path(plan.bin_dir) / "zermes-gateway",
        Path(plan.bin_dir) / "zermes.bat",
        Path(plan.bin_dir) / "zermes-gateway.bat",
    )
    assert (Path(plan.bin_dir) / "zermes").read_text(encoding="utf-8") == (
        install_zermes.posix_launcher_text(plan)
    )
    assert (Path(plan.bin_dir) / "zermes.bat").read_bytes().decode("utf-8") == (
        install_zermes.windows_launcher_text(plan)
    )
    assert os.access(Path(plan.bin_dir) / "zermes", os.X_OK)


def test_create_launcher_scripts_can_be_disabled(tmp_path):
    plan = _plan_launchers(tmp_path)

    paths = install_zermes.create_launcher_scripts(plan, create_launchers=False)

    assert paths == ()
    assert not Path(plan.bin_dir).exists()


def test_create_launcher_scripts_dry_run_does_not_write(tmp_path):
    plan = _plan_launchers(tmp_path)

    paths = install_zermes.create_launcher_scripts(plan, dry_run=True)

    assert paths == (
        Path(plan.prefix) / "launcher" / "zermes_launcher.py",
        Path(plan.bin_dir) / "zermes",
        Path(plan.bin_dir) / "zermes-gateway",
        Path(plan.bin_dir) / "zermes.bat",
        Path(plan.bin_dir) / "zermes-gateway.bat",
    )
    assert not Path(plan.bin_dir).exists()


def test_configure_global_command_skips_when_disabled(tmp_path):
    plan = _plan_launchers(tmp_path)

    result = install_zermes.configure_global_command(plan, enabled=False)

    assert result.status == "skipped"
    assert result.path is None


def test_configure_global_command_creates_posix_symlink_when_path_is_ready(tmp_path):
    plan = _plan_launchers(tmp_path)
    Path(plan.bin_dir).mkdir(parents=True)
    launcher = Path(plan.bin_dir) / "zermes"
    launcher.write_text("#!/usr/bin/env sh\n", encoding="utf-8")
    global_bin_dir = tmp_path / "user-bin"

    result = install_zermes.configure_global_command(
        plan,
        enabled=True,
        global_bin_dir=global_bin_dir,
        platform="posix",
        env_path=str(global_bin_dir),
    )

    assert result.status == "enabled"
    assert result.method == "symlink"
    assert (global_bin_dir / "zermes").is_symlink()
    assert (global_bin_dir / "zermes").readlink() == launcher


def test_configure_global_command_reports_manual_action_when_posix_path_is_missing(tmp_path):
    plan = _plan_launchers(tmp_path)
    Path(plan.bin_dir).mkdir(parents=True)
    (Path(plan.bin_dir) / "zermes").write_text("#!/usr/bin/env sh\n", encoding="utf-8")
    global_bin_dir = tmp_path / "user-bin"

    result = install_zermes.configure_global_command(
        plan,
        enabled=True,
        global_bin_dir=global_bin_dir,
        platform="posix",
        env_path=str(tmp_path / "other-bin"),
    )

    assert result.status == "manual_action_required"
    assert (global_bin_dir / "zermes").is_symlink()


def test_configure_global_command_does_not_duplicate_windows_path(tmp_path):
    plan = _plan_launchers(tmp_path)
    writes: list[str] = []

    result = install_zermes.configure_global_command(
        plan,
        enabled=True,
        platform="windows",
        env_path=f"C:\\Tools;{plan.bin_dir}",
        windows_path_writer=writes.append,
    )

    assert result.status == "already_configured"
    assert writes == []


def test_configure_global_command_appends_windows_user_path(tmp_path):
    plan = _plan_launchers(tmp_path)
    writes: list[str] = []

    result = install_zermes.configure_global_command(
        plan,
        enabled=True,
        platform="windows",
        env_path="C:\\Tools",
        windows_path_writer=writes.append,
    )

    assert result.status == "enabled"
    assert writes == [f"C:\\Tools;{plan.bin_dir}"]


def test_configure_global_command_dry_run_does_not_write(tmp_path):
    plan = _plan_launchers(tmp_path)
    global_bin_dir = tmp_path / "user-bin"

    result = install_zermes.configure_global_command(
        plan,
        enabled=True,
        global_bin_dir=global_bin_dir,
        platform="posix",
        env_path=str(global_bin_dir),
        dry_run=True,
    )

    assert result.status == "enabled"
    assert not global_bin_dir.exists()


def _write_launcher_source(plan):
    launcher_source = Path(plan.source_dir) / "launcher" / "zermes_launcher.py"
    launcher_source.parent.mkdir(parents=True)
    launcher_source.write_text("# launcher\n", encoding="utf-8")



# From test_metadata.py

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path

from scripts import install_zermes


def _plan_metadata(tmp_path):
    args = argparse.Namespace(
        prefix=tmp_path / "app",
        data_dir=tmp_path / "data",
        release_id="source-install",
        dry_run=False,
        no_venv=False,
        python=None,
    )
    return install_zermes.build_plan(args, repo_root=tmp_path / "repo")


def test_release_metadata_contains_runtime_fields(tmp_path):
    plan = _plan_metadata(tmp_path)
    now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)

    metadata = install_zermes.release_metadata(plan, now=now)

    assert metadata == {
        "schema_version": 1,
        "release_id": "source-install",
        "install_prefix": plan.prefix,
        "data_dir": plan.data_dir,
        "install_data_dir": plan.install_data_dir,
        "self_evolution_data_dir": plan.self_evolution_data_dir,
        "source_path": plan.source_dir,
        "venv_path": plan.venv_dir,
        "build_path": plan.build_dir,
        "python_path": plan.python_path,
        "candidate_commit": "",
        "source_repo": {"path": plan.repo_root},
        "created_at": "2026-05-10T12:00:00+00:00",
        "activated_at": "2026-05-10T12:00:00+00:00",
        "installer_version": "source-installer-v1",
    }


def test_atomic_write_json_writes_complete_json(tmp_path):
    path = tmp_path / "runtime" / "active.json"

    install_zermes.atomic_write_json(path, {"release_id": "one"})

    assert json.loads(path.read_text(encoding="utf-8")) == {"release_id": "one"}
    assert not (path.parent / ".active.json.tmp").exists()


def test_write_release_metadata_writes_metadata_and_active(tmp_path):
    plan = _plan_metadata(tmp_path)
    now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)

    metadata = install_zermes.write_release_metadata(plan, now=now)

    metadata_path = Path(plan.release_dir) / "metadata.json"
    assert json.loads(metadata_path.read_text(encoding="utf-8")) == metadata
    assert json.loads(Path(plan.active_path).read_text(encoding="utf-8")) == metadata
    assert not Path(plan.previous_path).exists()


def test_write_release_metadata_preserves_previous_active(tmp_path):
    plan = _plan_metadata(tmp_path)
    active_path = Path(plan.active_path)
    active_path.parent.mkdir(parents=True)
    install_zermes.atomic_write_json(active_path, {"release_id": "old"})

    install_zermes.write_release_metadata(plan)

    assert json.loads(Path(plan.previous_path).read_text(encoding="utf-8")) == {
        "release_id": "old"
    }



# From test_source_sync.py

import argparse
from pathlib import Path

import pytest

from scripts import install_zermes


def _plan_source_sync(tmp_path, repo_root):
    args = argparse.Namespace(
        prefix=tmp_path / "app",
        data_dir=tmp_path / "data",
        release_id="source-install",
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

    plan = _plan_source_sync(tmp_path, repo)
    copied = install_zermes.sync_source_to_release(plan)

    assert copied
    target = Path(plan.source_dir)
    assert (target / "README.md").read_text(encoding="utf-8") == "hello"
    assert (target / "pkg" / "module.py").read_text(encoding="utf-8") == "print('ok')"
    assert not (target / ".git").exists()
    assert not (target / "venv").exists()
    assert not (target / "node_modules").exists()


def test_sync_source_to_release_uses_git_archive_for_git_checkout(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    archive_bytes = BytesIO()
    with tarfile.open(fileobj=archive_bytes, mode="w") as archive:
        payload = b"hello"
        info = tarfile.TarInfo("README.md")
        info.size = len(payload)
        archive.addfile(info, BytesIO(payload))

    def fake_run(command, *, cwd, capture_output, check, shell):
        assert command == ["git", "archive", "--format=tar", "HEAD"]
        assert cwd == repo
        assert capture_output is True
        assert check is False
        assert shell is False
        return SimpleNamespace(returncode=0, stdout=archive_bytes.getvalue())

    monkeypatch.setattr(install_zermes.subprocess, "run", fake_run)
    plan = _plan_source_sync(tmp_path, repo)

    copied = install_zermes.sync_source_to_release(plan)

    assert copied == [Path(plan.source_dir) / "README.md"]
    assert (Path(plan.source_dir) / "README.md").read_text(encoding="utf-8") == "hello"


def test_sync_source_to_release_preserves_unknown_target_files(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("hello", encoding="utf-8")
    plan = _plan_source_sync(tmp_path, repo)
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
    plan = _plan_source_sync(tmp_path, repo)

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
        dry_run=False,
    )
    plan = install_zermes.build_plan(args, repo_root=repo)

    with pytest.raises(ValueError, match="inside the repository root"):
        install_zermes.sync_source_to_release(plan)


# From test_venv.py

import argparse
from pathlib import Path

from scripts import install_zermes


def _plan_venv(tmp_path, *, no_venv=False, python_path=None):
    args = argparse.Namespace(
        prefix=tmp_path / "app",
        data_dir=tmp_path / "data",
        release_id="source-install",
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
    plan = _plan_venv(tmp_path)

    assert plan.use_venv is True
    assert Path(plan.python_path) == install_zermes.venv_python_path(Path(plan.venv_dir))


def test_build_plan_no_venv_uses_selected_python(tmp_path):
    selected_python = tmp_path / "python"
    selected_python.write_text("", encoding="utf-8")

    plan = _plan_venv(tmp_path, no_venv=True, python_path=selected_python)

    assert plan.use_venv is False
    assert Path(plan.python_path) == selected_python.resolve()


def test_create_virtual_environment_uses_command_runner(monkeypatch, tmp_path):
    calls = []
    plan = _plan_venv(tmp_path)

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
    plan = _plan_venv(tmp_path, no_venv=True)

    def fail_run_command(*_args, **_kwargs):
        raise AssertionError("run_command should not be called")

    monkeypatch.setattr(install_zermes, "run_command", fail_run_command)

    result = install_zermes.create_virtual_environment(plan)

    assert result.returncode == 0
    assert result.command == ()



# From test_verify.py

import argparse
from pathlib import Path

from scripts import install_zermes


def _plan_verify(tmp_path):
    args = argparse.Namespace(
        prefix=tmp_path / "app",
        data_dir=tmp_path / "data",
        release_id="source-install",
        dry_run=False,
        no_venv=False,
        python=None,
    )
    return install_zermes.build_plan(args, repo_root=tmp_path / "repo")


def test_verification_commands_use_release_python_and_existing_cli(tmp_path):
    plan = _plan_verify(tmp_path)

    assert install_zermes.verification_commands(plan) == (
        [plan.python_path, "-c", "import sys; print(sys.version)"],
        [plan.python_path, "-m", "pip", "--version"],
        [plan.python_path, "-m", "hermes_cli.main", "--help"],
    )


def test_verification_commands_can_skip_cli_when_dependencies_are_skipped(tmp_path):
    plan = _plan_verify(tmp_path)

    assert install_zermes.verification_commands(plan, verify_cli=False) == (
        [plan.python_path, "-c", "import sys; print(sys.version)"],
        [plan.python_path, "-m", "pip", "--version"],
    )


def test_verify_installed_runtime_runs_all_commands(monkeypatch, tmp_path):
    plan = _plan_verify(tmp_path)
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
    plan = _plan_verify(tmp_path)

    def fail_run(*_args, **_kwargs):
        raise AssertionError("run_command should not be called")

    monkeypatch.setattr(install_zermes, "run_command", fail_run)

    assert install_zermes.verify_installed_runtime(plan, skip_verify=True) == ()


def test_verify_installed_runtime_propagates_command_failure(monkeypatch, tmp_path):
    plan = _plan_verify(tmp_path)

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

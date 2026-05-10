from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scripts import install_zermes


def _args(tmp_path, **overrides):
    """Build install args for workflow tests without using global defaults."""

    values = {
        "prefix": tmp_path / "app",
        "data_dir": tmp_path / "data",
        "release_id": "source-install",
        "language": "zh-CN",
        "dry_run": False,
        "non_interactive": True,
        "no_venv": False,
        "python": None,
        "install_deps": True,
        "create_launchers": True,
        "skip_verify": False,
        "start": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_run_install_workflow_runs_steps_in_order(monkeypatch, tmp_path):
    args = _args(tmp_path)
    calls: list[str] = []

    def record(name, result=None):
        def wrapper(*_args, **_kwargs):
            calls.append(name)
            if result is not None:
                return result
            if name == "sync":
                return [Path("one"), Path("two")]
            if name == "metadata":
                return {"release_id": "source-install"}
            if name == "launchers":
                return (tmp_path / "app" / "bin" / "zermes",)
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
    monkeypatch.setattr(install_zermes, "verify_installed_runtime", record("verify"))
    monkeypatch.setattr(install_zermes, "start_zermes", record("start"))

    result = install_zermes.run_install_workflow(args, repo_root=tmp_path / "repo")

    assert calls == [
        "dirs",
        "data",
        "sync",
        "venv",
        "deps",
        "metadata",
        "launchers",
        "verify",
        "start",
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
        "verify-runtime",
        "start-zermes",
    ]


def test_run_install_workflow_dry_run_only_returns_plan(monkeypatch, tmp_path):
    args = _args(tmp_path, dry_run=True)

    def fail_write(*_args, **_kwargs):
        raise AssertionError("dry-run should not execute install steps")

    monkeypatch.setattr(install_zermes, "create_install_directories", fail_write)

    result = install_zermes.run_install_workflow(args, repo_root=tmp_path / "repo")

    assert result["dry_run"] is True
    assert result["release_id"] == "source-install"
    assert not (tmp_path / "app").exists()


def test_main_real_install_outputs_success_json(monkeypatch, tmp_path, capsys):
    def fake_install(args, *, repo_root, input_fn=input, now=None):
        return {
            "status": "installed",
            "plan": {"prefix": str(args.prefix.resolve())},
            "steps": [],
        }

    monkeypatch.setattr(install_zermes, "run_install_workflow", fake_install)

    exit_code = install_zermes.main(
        [
            "install",
            "--prefix",
            str(tmp_path / "app"),
            "--data-dir",
            str(tmp_path / "data"),
            "--non-interactive",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "installed"
    assert Path(payload["plan"]["prefix"]) == (tmp_path / "app").resolve()


def test_run_install_workflow_minimal_real_install(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("hello", encoding="utf-8")
    args = _args(
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

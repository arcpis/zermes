from argparse import Namespace
import json
from pathlib import Path

from scripts.install_zermes import (
    InstallerPlan,
    UpdateSource,
    activate_update_candidate,
    build_plan,
    create_launcher_scripts,
    posix_gateway_launcher_text,
    posix_launcher_text,
    windows_gateway_launcher_text,
    windows_launcher_text,
)


def test_launcher_scripts_route_through_stable_active_pointer(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    args = _install_args(tmp_path)
    plan = build_plan(args, repo_root=repo_root)
    launcher_source = Path(plan.source_dir) / "launcher" / "zermes_launcher.py"
    launcher_source.parent.mkdir(parents=True)
    launcher_source.write_text("# stable launcher\n", encoding="utf-8")

    launchers = create_launcher_scripts(plan)

    launcher_path = Path(plan.prefix) / "launcher" / "zermes_launcher.py"
    assert launcher_path in launchers
    assert launcher_path.read_text(encoding="utf-8") == "# stable launcher\n"
    assert (Path(plan.bin_dir) / "zermes") in launchers
    assert (Path(plan.bin_dir) / "zermes-gateway") in launchers
    assert (Path(plan.bin_dir) / "zermes.bat") in launchers
    assert (Path(plan.bin_dir) / "zermes-gateway.bat") in launchers

    zermes_text = (Path(plan.bin_dir) / "zermes").read_text(encoding="utf-8")
    gateway_text = (Path(plan.bin_dir) / "zermes-gateway").read_text(encoding="utf-8")
    assert "ZERMES_INSTALL_PREFIX" in zermes_text
    assert "zermes_launcher.py\" cli" in zermes_text
    assert "zermes_launcher.py\" gateway" in gateway_text
    assert "-m hermes_cli.main" not in zermes_text
    assert "-m hermes_cli.main" not in gateway_text


def test_launcher_script_texts_cover_cli_and_gateway_modes(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    plan = build_plan(_install_args(tmp_path), repo_root=repo_root)

    assert "zermes_launcher.py\" cli" in posix_launcher_text(plan)
    assert "zermes_launcher.py\" gateway" in posix_gateway_launcher_text(plan)
    assert "zermes_launcher.py\" cli" in windows_launcher_text(plan)
    assert "zermes_launcher.py\" gateway" in windows_gateway_launcher_text(plan)


def test_activate_update_candidate_refreshes_stable_launcher_from_release(tmp_path):
    prefix = tmp_path / "install"
    candidate_dir = prefix / "runtime" / "candidates" / "update-20260516"
    source_dir = candidate_dir / "source"
    venv_dir = candidate_dir / "venv"
    build_dir = candidate_dir / "build"
    launcher_source = source_dir / "launcher" / "zermes_launcher.py"
    launcher_source.parent.mkdir(parents=True)
    launcher_source.write_text("# candidate launcher\n", encoding="utf-8")
    venv_dir.mkdir(parents=True)
    build_dir.mkdir()
    _write_active_release(prefix, "old-release")
    plan = InstallerPlan(
        repo_root=str(tmp_path / "repo"),
        prefix=str(prefix),
        data_dir=str(tmp_path / "data"),
        release_id="update-20260516",
        runtime_dir=str(prefix / "runtime"),
        release_dir=str(candidate_dir),
        source_dir=str(source_dir),
        venv_dir=str(venv_dir),
        build_dir=str(build_dir),
        bin_dir=str(prefix / "bin"),
        python_path=str(tmp_path / "python"),
        use_venv=False,
        active_path=str(prefix / "runtime" / "active.json"),
        previous_path=str(prefix / "runtime" / "previous.json"),
        dry_run=False,
    )
    update_source = UpdateSource(kind="explicit", path=str(tmp_path / "repo"), active_release_id="old-release")

    state = activate_update_candidate(plan, update_source, candidate_id="update-20260516")

    stable_launcher = prefix / "launcher" / "zermes_launcher.py"
    assert state["status"] == "activated"
    assert stable_launcher.read_text(encoding="utf-8") == "# candidate launcher\n"
    assert (prefix / "bin" / "zermes-gateway").exists()


def test_stable_launcher_execs_active_release(monkeypatch, tmp_path):
    from launcher import zermes_launcher

    prefix = tmp_path / "install"
    source = tmp_path / "active-source"
    venv = tmp_path / "active-venv"
    python = venv / ("Scripts/python.exe" if zermes_launcher.os.name == "nt" else "bin/python")
    source.mkdir()
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    active_path = prefix / "runtime" / "active.json"
    active_path.parent.mkdir(parents=True)
    active_path.write_text(
        json.dumps(
            {
                "release_id": "release-abc1234",
                "source_path": str(source),
                "venv_path": str(venv),
                "data_dir": str(tmp_path / "data"),
            }
        ),
        encoding="utf-8",
    )
    captured = {}

    def fake_execve(path, command, env):
        captured["path"] = path
        captured["command"] = command
        captured["env"] = env
        raise SystemExit(0)

    monkeypatch.setenv("ZERMES_INSTALL_PREFIX", str(prefix))
    monkeypatch.setattr(zermes_launcher.os, "execve", fake_execve)
    monkeypatch.setattr(zermes_launcher.os, "chdir", lambda path: captured.setdefault("cwd", path))

    try:
        zermes_launcher.main(["gateway", "--help"])
    except SystemExit as exc:
        assert exc.code == 0

    assert captured["path"] == str(python.resolve())
    assert captured["command"] == [str(python.resolve()), "-m", "hermes_cli.main", "gateway", "--help"]
    assert captured["cwd"] == str(source.resolve())
    assert captured["env"]["ZERMES_ACTIVE_RELEASE"] == "release-abc1234"
    assert captured["env"]["HERMES_HOME"] == str(tmp_path / "data")
    assert captured["env"]["PYTHONPATH"].split(zermes_launcher.os.pathsep)[0] == str(source.resolve())


def _install_args(tmp_path):
    return Namespace(
        dry_run=False,
        prefix=tmp_path / "install",
        data_dir=tmp_path / "data",
        release_id="source-install",
        python=tmp_path / "python",
        no_venv=True,
    )


def _write_active_release(prefix, release_id):
    release_root = prefix / "runtime" / "releases" / release_id
    (release_root / "source").mkdir(parents=True)
    (release_root / "venv").mkdir()
    (release_root / "build").mkdir()
    active_path = prefix / "runtime" / "active.json"
    active_path.parent.mkdir(parents=True, exist_ok=True)
    active_path.write_text(
        json.dumps(
            {
                "release_id": release_id,
                "source_path": str(release_root / "source"),
                "venv_path": str(release_root / "venv"),
                "build_path": str(release_root / "build"),
            }
        ),
        encoding="utf-8",
    )

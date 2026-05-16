from argparse import Namespace
import json
from pathlib import Path

from scripts.install_zermes import (
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
    launcher_source = repo_root / "launcher" / "zermes_launcher.py"
    launcher_source.parent.mkdir()
    launcher_source.write_text("# stable launcher\n", encoding="utf-8")
    args = _install_args(tmp_path)
    plan = build_plan(args, repo_root=repo_root)

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

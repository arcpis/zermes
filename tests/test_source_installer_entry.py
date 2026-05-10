from __future__ import annotations

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

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

    assert install.main(["--dry-run"]) == 17
    assert calls == [["--dry-run"]]


def test_dry_run_defaults_do_not_create_default_prefix(capsys):
    exit_code = install_zermes.main(["--dry-run", "--non-interactive"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["language"] == "zh-CN"
    assert payload["release_id"] == "source-install"

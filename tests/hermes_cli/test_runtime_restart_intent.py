from __future__ import annotations

import json

import pytest

from hermes_cli import main as hermes_main


def test_runtime_restart_intent_path_requires_managed_prefix(monkeypatch):
    monkeypatch.delenv("ZERMES_INSTALL_PREFIX", raising=False)

    assert hermes_main._runtime_restart_intent_path() is None


def test_maybe_exec_runtime_restart_intent_after_cli_noops_without_intent(
    monkeypatch, tmp_path
):
    prefix = tmp_path / "install"
    monkeypatch.setenv("ZERMES_INSTALL_PREFIX", str(prefix))

    called = []

    def fake_restart_intent(_argv):
        called.append(_argv)

    monkeypatch.setattr(
        "launcher.zermes_launcher.main",
        fake_restart_intent,
    )

    hermes_main._maybe_exec_runtime_restart_intent_after_cli()

    assert called == []


def test_maybe_exec_runtime_restart_intent_after_cli_delegates_to_launcher(
    monkeypatch, tmp_path
):
    prefix = tmp_path / "install"
    intent_path = prefix / "runtime" / "restart-intent.json"
    intent_path.parent.mkdir(parents=True)
    intent_path.write_text(
        json.dumps({"status": "requested", "mode": "cli"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ZERMES_INSTALL_PREFIX", str(prefix))

    called = []

    def fake_restart_intent(argv):
        called.append(argv)
        raise SystemExit(0)

    monkeypatch.setattr(
        "launcher.zermes_launcher.main",
        fake_restart_intent,
    )

    with pytest.raises(SystemExit) as exc_info:
        hermes_main._maybe_exec_runtime_restart_intent_after_cli()

    assert exc_info.value.code == 0
    assert called == [["restart-intent"]]


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "restarting", "mode": "cli"},
        {"status": "requested", "mode": "gateway"},
        {"status": "requested", "mode": "manual"},
        ["not", "an", "object"],
    ],
)
def test_maybe_exec_runtime_restart_intent_after_cli_ignores_unconsumable_intents(
    monkeypatch, tmp_path, payload
):
    prefix = tmp_path / "install"
    intent_path = prefix / "runtime" / "restart-intent.json"
    intent_path.parent.mkdir(parents=True)
    intent_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("ZERMES_INSTALL_PREFIX", str(prefix))

    called = []
    monkeypatch.setattr(
        "launcher.zermes_launcher.main",
        lambda argv: called.append(argv),
    )

    hermes_main._maybe_exec_runtime_restart_intent_after_cli()

    assert called == []

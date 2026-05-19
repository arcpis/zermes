from pathlib import Path

from hermes_constants import get_default_hermes_root, get_hermes_home
from toolsets import resolve_toolset, validate_toolset


def test_zermes_home_is_default(monkeypatch, tmp_path):
    monkeypatch.delenv("ZERMES_HOME", raising=False)
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert get_hermes_home() == tmp_path / ".hermes"
    assert get_default_hermes_root() == tmp_path / ".hermes"


def test_hermes_home_takes_precedence_over_zermes_alias(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    monkeypatch.setenv("ZERMES_HOME", str(tmp_path / ".zermes"))

    assert get_hermes_home() == tmp_path / ".hermes"


def test_legacy_hermes_home_remains_supported(monkeypatch, tmp_path):
    legacy_home = tmp_path / ".hermes"
    monkeypatch.delenv("ZERMES_HOME", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(legacy_home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert get_hermes_home() == legacy_home
    assert get_default_hermes_root() == legacy_home


def test_zermes_toolset_aliases_resolve_to_legacy_toolsets():
    assert validate_toolset("zermes-cli")
    assert resolve_toolset("zermes-cli") == resolve_toolset("hermes-cli")

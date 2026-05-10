from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from scripts import install_zermes


def _args(tmp_path, **overrides):
    """Build update args with explicit defaults for source resolution tests."""

    values = {
        "prefix": tmp_path / "app",
        "source": None,
        "current_source": False,
        "non_interactive": True,
        "force": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_resolve_update_source_uses_explicit_source(tmp_path):
    source = tmp_path / "checkout"
    source.mkdir()

    resolved = install_zermes.resolve_update_source(
        _args(tmp_path, source=source),
        repo_root=tmp_path / "repo",
    )

    assert resolved.kind == "explicit"
    assert Path(resolved.path) == source.resolve()


def test_resolve_update_source_uses_current_source(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    resolved = install_zermes.resolve_update_source(
        _args(tmp_path, current_source=True),
        repo_root=repo_root,
    )

    assert resolved.kind == "current-source"
    assert Path(resolved.path) == repo_root.resolve()


def test_resolve_update_source_requires_source_in_non_interactive_mode(tmp_path):
    with pytest.raises(ValueError, match="requires --source or --current-source"):
        install_zermes.resolve_update_source(_args(tmp_path), repo_root=tmp_path / "repo")


def test_resolve_update_source_rejects_active_release_source_without_force(tmp_path):
    active_source = tmp_path / "app" / "runtime" / "releases" / "one" / "source"
    active_source.mkdir(parents=True)
    active_path = install_zermes.active_metadata_path(tmp_path / "app")
    active_path.parent.mkdir(parents=True, exist_ok=True)
    active_path.write_text(
        json.dumps({"release_id": "one", "source_path": str(active_source)}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="active release source"):
        install_zermes.resolve_update_source(
            _args(tmp_path, source=active_source),
            repo_root=tmp_path / "repo",
        )


def test_resolve_update_source_allows_active_release_source_with_force(tmp_path):
    active_source = tmp_path / "app" / "runtime" / "releases" / "one" / "source"
    active_source.mkdir(parents=True)
    active_path = install_zermes.active_metadata_path(tmp_path / "app")
    active_path.parent.mkdir(parents=True, exist_ok=True)
    active_path.write_text(
        json.dumps({"release_id": "one", "source_path": str(active_source)}),
        encoding="utf-8",
    )

    resolved = install_zermes.resolve_update_source(
        _args(tmp_path, source=active_source, force=True),
        repo_root=tmp_path / "repo",
    )

    assert resolved.active_release_id == "one"
    assert Path(resolved.path) == active_source.resolve()

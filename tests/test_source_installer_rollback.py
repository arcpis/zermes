from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import install_zermes


def test_rollback_release_points_active_to_previous(tmp_path):
    prefix = tmp_path / "app"
    current = {"release_id": "new-release"}
    previous = {"release_id": "old-release"}
    install_zermes.atomic_write_json(install_zermes.active_metadata_path(prefix), current)
    install_zermes.atomic_write_json(prefix / "runtime" / "previous.json", previous)

    state = install_zermes.rollback_release(prefix)

    active = json.loads(install_zermes.active_metadata_path(prefix).read_text(encoding="utf-8"))
    rollback_state = json.loads(
        install_zermes.rollback_state_path(prefix).read_text(encoding="utf-8")
    )
    assert active == previous
    assert state == rollback_state
    assert state["rolled_back_from"] == current
    assert state["rolled_back_to"] == previous
    assert state["restart_required"] is True


def test_rollback_release_requires_previous(tmp_path):
    with pytest.raises(ValueError, match="previous.json"):
        install_zermes.rollback_release(tmp_path / "app")


def test_rollback_release_does_not_delete_release_directories(tmp_path):
    prefix = tmp_path / "app"
    old_marker = prefix / "runtime" / "releases" / "old-release" / "keep.txt"
    new_marker = prefix / "runtime" / "releases" / "new-release" / "keep.txt"
    old_marker.parent.mkdir(parents=True)
    new_marker.parent.mkdir(parents=True)
    old_marker.write_text("old", encoding="utf-8")
    new_marker.write_text("new", encoding="utf-8")
    install_zermes.atomic_write_json(install_zermes.active_metadata_path(prefix), {"release_id": "new-release"})
    install_zermes.atomic_write_json(prefix / "runtime" / "previous.json", {"release_id": "old-release"})

    install_zermes.rollback_release(prefix)

    assert old_marker.read_text(encoding="utf-8") == "old"
    assert new_marker.read_text(encoding="utf-8") == "new"

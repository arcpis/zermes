"""Tests for runtime release pointer management."""

from datetime import UTC, datetime
import json
import os
import subprocess

import pytest

from code_modification.runtime_update import (
    RuntimeRelease,
    RuntimeUpdateError,
    RuntimeUpdateState,
    activate_release,
    acquire_runtime_update_lock,
    generate_candidate_id,
    generate_release_id,
    mark_candidate_blocked,
    mark_candidate_verified,
    prepare_candidate_environment,
    prepare_candidate_source,
    promote_candidate_to_release,
    read_active_release,
    read_previous_release,
    release_runtime_update_lock,
    rollback_active_release,
    runtime_update_lock,
    run_candidate_health_checks,
    write_runtime_update_state,
)


def test_prepare_candidate_source_archives_tracked_files_only(tmp_path):
    source_repo = tmp_path / "source-repo"
    _make_source_repo(source_repo)
    commit = _git_commit(source_repo)
    prefix = tmp_path / "zermes"

    candidate = prepare_candidate_source(
        prefix,
        "update-20260510-120000-abcdef0",
        source_repo=source_repo,
        git_ref="HEAD",
        task_id="20260516-010000-update-flow",
        old_release_id="source-install",
    )

    candidate_root = prefix / "runtime" / "candidates" / candidate.candidate_id
    source_path = candidate_root / "source"
    metadata = _read_json(candidate_root / "metadata.json")
    candidate_state = _read_json(candidate_root / "update-state.json")
    runtime_state = _read_json(prefix / "runtime" / "update-state.json")
    assert candidate.candidate_commit == commit
    assert (source_path / "pyproject.toml").exists()
    assert (source_path / "code_modification" / "__init__.py").exists()
    assert not (source_path / ".git").exists()
    assert not (source_path / "untracked.txt").exists()
    assert metadata["source_repo"]["path"] == str(source_repo.resolve())
    assert metadata["candidate_commit"] == commit
    assert candidate_state["status"] == "source_synced"
    assert runtime_state["candidate_id"] == candidate.candidate_id


def test_prepare_candidate_source_rejects_existing_candidate(tmp_path):
    source_repo = tmp_path / "source-repo"
    _make_source_repo(source_repo)
    prefix = tmp_path / "zermes"
    candidate_root = prefix / "runtime" / "candidates" / "update-20260510-120000-abcdef0"
    candidate_root.mkdir(parents=True)

    with pytest.raises(RuntimeUpdateError, match="candidate already exists"):
        prepare_candidate_source(
            prefix,
            "update-20260510-120000-abcdef0",
            source_repo=source_repo,
            git_ref="HEAD",
        )


def test_prepare_candidate_source_requires_git_root(tmp_path):
    source_repo = tmp_path / "source-repo"
    _make_source_repo(source_repo)

    with pytest.raises(RuntimeUpdateError, match="project_root must be the git root"):
        prepare_candidate_source(
            tmp_path / "zermes",
            "update-20260510-120000-abcdef0",
            source_repo=source_repo / "code_modification",
            git_ref="HEAD",
        )


def test_prepare_candidate_source_cleans_partial_candidate_on_archive_error(tmp_path):
    if not hasattr(os, "symlink"):
        pytest.skip("symlink support is required for this archive safety test")
    source_repo = tmp_path / "source-repo"
    _make_source_repo(source_repo)
    os.symlink("pyproject.toml", source_repo / "linked-pyproject.toml")
    subprocess.run(
        ["git", "add", "linked-pyproject.toml"],
        cwd=source_repo,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Add symlink"],
        cwd=source_repo,
        check=True,
        capture_output=True,
        text=True,
    )
    prefix = tmp_path / "zermes"
    candidate_id = "update-20260510-120000-abcdef0"

    with pytest.raises(RuntimeUpdateError, match="unsupported archive member type"):
        prepare_candidate_source(
            prefix,
            candidate_id,
            source_repo=source_repo,
            git_ref="HEAD",
        )

    assert not (prefix / "runtime" / "candidates" / candidate_id).exists()


def test_mark_candidate_verified_records_health_checks(tmp_path):
    source_repo = tmp_path / "source-repo"
    _make_source_repo(source_repo)
    prefix = tmp_path / "zermes"
    candidate = prepare_candidate_source(
        prefix,
        "update-20260510-120000-abcdef0",
        source_repo=source_repo,
        git_ref="HEAD",
        task_id="20260516-010000-update-flow",
        old_release_id="source-install",
    )

    state = mark_candidate_verified(
        prefix,
        candidate.candidate_id,
        health_checks=["cli help passed", "focused tests passed", ""],
    )

    candidate_state = _read_json(
        prefix / "runtime" / "candidates" / candidate.candidate_id / "update-state.json"
    )
    runtime_state = _read_json(prefix / "runtime" / "update-state.json")
    assert state.status == "verified"
    assert state.health_checks == ("cli help passed", "focused tests passed")
    assert candidate_state["status"] == "verified"
    assert candidate_state["steps"] == ["source_synced", "verified"]
    assert runtime_state["status"] == "verified"
    assert runtime_state["health_checks"] == ["cli help passed", "focused tests passed"]


def test_mark_candidate_verified_requires_health_checks(tmp_path):
    source_repo = tmp_path / "source-repo"
    _make_source_repo(source_repo)
    prefix = tmp_path / "zermes"
    candidate = prepare_candidate_source(
        prefix,
        "update-20260510-120000-abcdef0",
        source_repo=source_repo,
        git_ref="HEAD",
    )

    with pytest.raises(RuntimeUpdateError, match="at least one health check"):
        mark_candidate_verified(prefix, candidate.candidate_id, health_checks=[])


def test_mark_candidate_blocked_records_reason_without_touching_active(tmp_path):
    source_repo = tmp_path / "source-repo"
    _make_source_repo(source_repo)
    prefix = tmp_path / "zermes"
    active_release = _make_release(prefix, "source-install")
    _write_json(prefix / "runtime" / "active.json", _release_payload(active_release))
    candidate = prepare_candidate_source(
        prefix,
        "update-20260510-120000-abcdef0",
        source_repo=source_repo,
        git_ref="HEAD",
    )

    state = mark_candidate_blocked(
        prefix,
        candidate.candidate_id,
        reason="cli help failed",
        health_checks=["cli help failed"],
    )

    assert state.status == "blocked"
    assert state.error == "cli help failed"
    assert read_active_release(prefix).release_id == "source-install"
    runtime_state = _read_json(prefix / "runtime" / "update-state.json")
    assert runtime_state["status"] == "blocked"
    assert runtime_state["error"] == "cli help failed"


def test_prepare_candidate_environment_creates_venv_and_records_state(tmp_path):
    source_repo = tmp_path / "source-repo"
    _make_source_repo(source_repo)
    prefix = tmp_path / "zermes"
    candidate = prepare_candidate_source(
        prefix,
        "update-20260510-120000-abcdef0",
        source_repo=source_repo,
        git_ref="HEAD",
    )

    state, results = prepare_candidate_environment(prefix, candidate.candidate_id)

    candidate_root = prefix / "runtime" / "candidates" / candidate.candidate_id
    assert state.status == "env_prepared"
    assert results[0].name == "create_venv"
    assert results[0].status == "passed"
    assert (candidate_root / "venv" / "bin" / "python").exists()
    assert _read_json(candidate_root / "logs" / "environment.json")["results"][0]["name"] == "create_venv"


def test_run_candidate_health_checks_marks_verified_and_logs_results(tmp_path):
    source_repo = tmp_path / "source-repo"
    _make_source_repo(source_repo)
    prefix = tmp_path / "zermes"
    candidate = prepare_candidate_source(
        prefix,
        "update-20260510-120000-abcdef0",
        source_repo=source_repo,
        git_ref="HEAD",
    )

    state, results = run_candidate_health_checks(
        prefix,
        candidate.candidate_id,
        checks=["python_version", "cli_help", "compileall"],
    )

    log_payload = _read_json(
        prefix / "runtime" / "candidates" / candidate.candidate_id / "logs" / "health-checks.json"
    )
    assert state.status == "verified"
    assert [result.status for result in results] == ["passed", "passed", "passed"]
    assert log_payload["results"][1]["name"] == "cli_help"


def test_run_candidate_health_checks_marks_blocked_on_failure(tmp_path):
    source_repo = tmp_path / "source-repo"
    _make_source_repo(source_repo)
    (source_repo / "cli.py").write_text("raise SystemExit(7)\n", encoding="utf-8")
    subprocess.run(["git", "add", "cli.py"], cwd=source_repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "Break cli"], cwd=source_repo, check=True, capture_output=True, text=True)
    prefix = tmp_path / "zermes"
    candidate = prepare_candidate_source(
        prefix,
        "update-20260510-120000-abcdef0",
        source_repo=source_repo,
        git_ref="HEAD",
    )

    state, results = run_candidate_health_checks(prefix, candidate.candidate_id, checks=["cli_help"])

    assert state.status == "blocked"
    assert state.error == "cli_help: failed"
    assert results[0].status == "failed"


def test_read_active_release_validates_release_layout(tmp_path):
    prefix = tmp_path / "zermes"
    release = _make_release(prefix, "source-install", commit="abc1234")
    _write_json(prefix / "runtime" / "active.json", _release_payload(release))

    active = read_active_release(prefix)

    assert active.release_id == "source-install"
    assert active.candidate_commit == "abc1234"
    assert active.source_repo.endswith("source-repo")


def test_read_active_release_rejects_missing_release_files(tmp_path):
    prefix = tmp_path / "zermes"
    release = _make_release(prefix, "source-install")
    _write_json(prefix / "runtime" / "active.json", _release_payload(release))
    (prefix / "runtime" / "releases" / "source-install" / "venv").rmdir()

    with pytest.raises(RuntimeUpdateError, match="incomplete"):
        read_active_release(prefix)


def test_activate_release_updates_previous_and_active(tmp_path):
    prefix = tmp_path / "zermes"
    old_release = _make_release(prefix, "source-install", commit="1111111")
    new_release = _make_release(prefix, "update-20260510-120000-2222222", commit="2222222")
    _write_json(prefix / "runtime" / "active.json", _release_payload(old_release))

    activated = activate_release(
        prefix,
        new_release,
        expected_old_release_id="source-install",
    )

    active_payload = _read_json(prefix / "runtime" / "active.json")
    previous_payload = _read_json(prefix / "runtime" / "previous.json")
    assert activated.release_id == new_release.release_id
    assert active_payload["release_id"] == new_release.release_id
    assert active_payload["activated_at"]
    assert previous_payload["release_id"] == "source-install"


def test_activate_release_rejects_stale_expected_active(tmp_path):
    prefix = tmp_path / "zermes"
    old_release = _make_release(prefix, "source-install")
    new_release = _make_release(prefix, "update-20260510-120000-abcdef0")
    _write_json(prefix / "runtime" / "active.json", _release_payload(old_release))

    with pytest.raises(RuntimeUpdateError, match="active release changed"):
        activate_release(prefix, new_release, expected_old_release_id="other-release")


def test_rollback_restores_previous_without_deleting_releases(tmp_path):
    prefix = tmp_path / "zermes"
    old_release = _make_release(prefix, "source-install", commit="1111111")
    new_release = _make_release(prefix, "update-20260510-120000-2222222", commit="2222222")
    _write_json(prefix / "runtime" / "active.json", _release_payload(old_release))
    activate_release(prefix, new_release, expected_old_release_id="source-install")

    restored = rollback_active_release(prefix)

    assert restored.release_id == "source-install"
    assert read_active_release(prefix).release_id == "source-install"
    assert read_previous_release(prefix).release_id == new_release.release_id
    assert (prefix / "runtime" / "releases" / new_release.release_id).exists()


def test_promote_candidate_to_release_moves_candidate_and_writes_metadata(tmp_path):
    prefix = tmp_path / "zermes"
    candidate = prefix / "runtime" / "candidates" / "update-20260510-120000-abcdef0"
    _make_runtime_tree(candidate)
    _write_json(
        candidate / "metadata.json",
        {
            "candidate_commit": "abcdef0123456789",
            "source_repo": {"path": str(tmp_path / "source-repo")},
        },
    )
    _write_json(candidate / "update-state.json", {"status": "verified"})

    release = promote_candidate_to_release(
        prefix,
        "update-20260510-120000-abcdef0",
        "release-abcdef0",
    )

    assert release.release_id == "release-abcdef0"
    assert not candidate.exists()
    assert (prefix / "runtime" / "releases" / "release-abcdef0").exists()
    assert _read_json(prefix / "runtime" / "releases" / "release-abcdef0" / "metadata.json")[
        "release_id"
    ] == "release-abcdef0"


def test_promote_candidate_to_release_requires_verified_candidate(tmp_path):
    prefix = tmp_path / "zermes"
    candidate = prefix / "runtime" / "candidates" / "update-20260510-120000-abcdef0"
    _make_runtime_tree(candidate)
    _write_json(candidate / "metadata.json", {"candidate_commit": "abcdef0123456789"})
    _write_json(candidate / "update-state.json", {"status": "source_synced"})

    with pytest.raises(RuntimeUpdateError, match="must be verified"):
        promote_candidate_to_release(prefix, candidate.name, "release-abcdef0")


def test_release_paths_must_stay_inside_release_directory(tmp_path):
    prefix = tmp_path / "zermes"
    _make_release(prefix, "source-install")
    bad_release = RuntimeRelease(
        release_id="source-install",
        source_path=str(tmp_path / "outside-source"),
        venv_path=str(prefix / "runtime" / "releases" / "source-install" / "venv"),
        build_path=str(prefix / "runtime" / "releases" / "source-install" / "build"),
        candidate_commit="abcdef0",
    )

    with pytest.raises(RuntimeUpdateError, match="source_path must stay inside"):
        activate_release(prefix, bad_release)


def test_release_paths_must_be_directories(tmp_path):
    prefix = tmp_path / "zermes"
    release = _make_release(prefix, "source-install")
    venv_path = prefix / "runtime" / "releases" / "source-install" / "venv"
    venv_path.rmdir()
    venv_path.write_text("not a directory", encoding="utf-8")

    with pytest.raises(RuntimeUpdateError, match="must be directories"):
        activate_release(prefix, release)


def test_write_runtime_update_state_is_valid_json(tmp_path):
    prefix = tmp_path / "zermes"
    write_runtime_update_state(
        prefix,
        RuntimeUpdateState(
            status="verified",
            task_id="20260516-010000-update-flow",
            candidate_id="update-20260510-120000-abcdef0",
            release_id="release-abcdef0",
            steps=("planned", "verified"),
        ),
    )

    payload = _read_json(prefix / "runtime" / "update-state.json")
    assert payload["status"] == "verified"
    assert payload["steps"] == ["planned", "verified"]
    assert payload["updated_at"]


def test_generated_ids_are_stable_and_sanitized():
    now = datetime(2026, 5, 16, 1, 2, 3, tzinfo=UTC)

    candidate_id = generate_candidate_id(now, "ABCDEF012345")
    release_id = generate_release_id("../bad candidate", "ABCDEF012345")

    assert candidate_id == "update-20260516-010203-abcdef0"
    assert release_id == "bad-candidate-abcdef0"


def test_runtime_update_lock_rejects_concurrent_update(tmp_path):
    prefix = tmp_path / "zermes"
    lock = acquire_runtime_update_lock(prefix, "runtime_prepare")

    try:
        with pytest.raises(RuntimeUpdateError, match="already in progress"):
            acquire_runtime_update_lock(prefix, "runtime_activate")
    finally:
        release_runtime_update_lock(lock)

    assert not (prefix / "runtime" / "update.lock").exists()


def test_runtime_update_lock_releases_after_exception(tmp_path):
    prefix = tmp_path / "zermes"

    with pytest.raises(RuntimeError, match="boom"):
        with runtime_update_lock(prefix, "runtime_prepare"):
            assert (prefix / "runtime" / "update.lock").exists()
            raise RuntimeError("boom")

    assert not (prefix / "runtime" / "update.lock").exists()


def _make_release(prefix, release_id, *, commit="abcdef0"):
    release_root = prefix / "runtime" / "releases" / release_id
    _make_runtime_tree(release_root)
    release = RuntimeRelease(
        release_id=release_id,
        source_path=str(release_root / "source"),
        venv_path=str(release_root / "venv"),
        build_path=str(release_root / "build"),
        candidate_commit=commit,
        source_repo=str(prefix.parent / "source-repo"),
    )
    _write_json(release_root / "metadata.json", _release_payload(release))
    return release


def _make_source_repo(repo):
    repo.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "tests@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Tests"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    (repo / "pyproject.toml").write_text("[project]\nname = 'hermes-agent'\n", encoding="utf-8")
    (repo / "install.py").write_text("# installer\n", encoding="utf-8")
    (repo / "cli.py").write_text(
        "import argparse\nargparse.ArgumentParser().parse_args()\n",
        encoding="utf-8",
    )
    (repo / "code_modification").mkdir()
    (repo / "code_modification" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "tools").mkdir()
    (repo / "tools" / "code_modification_tool.py").write_text("# tool\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True, text=True)
    (repo / "untracked.txt").write_text("do not archive", encoding="utf-8")


def _git_commit(repo):
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _make_runtime_tree(root):
    (root / "source").mkdir(parents=True)
    (root / "venv").mkdir()
    (root / "build").mkdir()


def _release_payload(release):
    return {
        "schema_version": release.schema_version,
        "release_id": release.release_id,
        "source_path": release.source_path,
        "venv_path": release.venv_path,
        "build_path": release.build_path,
        "candidate_commit": release.candidate_commit,
        "source_repo": {"path": release.source_repo},
        "activated_at": release.activated_at,
    }


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))

"""Tests for audited self-update application state."""

import json
import subprocess

from code_modification.executor import ExecutionState, write_state
from code_modification.governance import build_task_record_layout
from code_modification.self_update import (
    plan_self_update_application,
    prepare_self_update,
    record_self_update_build,
    record_self_update_health_check,
    activate_self_update,
)
from tools.code_modification_tool import self_update_application


def test_self_update_application_records_restart_pending_flow(tmp_path):
    project_root = tmp_path / "hermes-agent"
    _make_project_repo(project_root)
    task_id = "20260516-010000-update-flow"
    _write_integrated_state(project_root, task_id)

    planned = plan_self_update_application(
        task_id,
        project_root=project_root,
        mode="cli",
    )
    prepared = prepare_self_update(
        task_id,
        approval_text="approved",
        project_root=project_root,
    )
    built = record_self_update_build(
        task_id,
        project_root=project_root,
        build_summary="python source only; no build required",
    )
    verified = record_self_update_health_check(
        task_id,
        project_root=project_root,
        checks=["focused self-evolution tests passed"],
        conclusion="passed",
    )
    activated = activate_self_update(
        task_id,
        approval_text="approved",
        project_root=project_root,
    )

    layout = build_task_record_layout(project_root, task_id)
    payload = json.loads((layout.task_dir / "update-state.json").read_text(encoding="utf-8"))
    report = (layout.task_dir / "update-application.md").read_text(encoding="utf-8")

    assert planned.status == "planned"
    assert prepared.approved_by_user is True
    assert built.status == "built"
    assert verified.status == "verified"
    assert activated.status == "restart_pending"
    assert activated.restart_required is True
    assert payload["status"] == "restart_pending"
    assert "restart remains a controlled follow-up" in report


def test_self_update_application_tool_exposes_paths(tmp_path):
    project_root = tmp_path / "hermes-agent"
    _make_project_repo(project_root)
    task_id = "20260516-020000-tool-flow"
    _write_integrated_state(project_root, task_id)

    planned = json.loads(
        self_update_application(
            "plan",
            task_id,
            project_root=str(project_root),
            mode="manual",
        )
    )
    prepared = json.loads(
        self_update_application(
            "prepare",
            task_id,
            project_root=str(project_root),
            approval_text="approved",
        )
    )
    status = json.loads(
        self_update_application("status", task_id, project_root=str(project_root))
    )

    assert planned["success"] is True
    assert planned["status"] == "planned"
    assert planned["update_application_path"].endswith("update-application.md")
    assert prepared["success"] is True
    assert prepared["status"] == "prepared"
    assert status["success"] is True
    assert status["state"]["status"] == "prepared"


def _write_integrated_state(project_root, task_id):
    layout = build_task_record_layout(project_root, task_id)
    state = ExecutionState(
        task_id=layout.task_id,
        status="integrated",
        project_root=str(project_root),
        base_branch="main",
        base_commit=_git_commit(project_root),
        development_branch=f"self-evolution/dev/{task_id}",
    )
    write_state(layout.task_dir / "execution-state.json", state)


def _make_project_repo(repo):
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
    (repo / "code_modification").mkdir()
    (repo / "tools").mkdir()
    (repo / "tools" / "code_modification_tool.py").write_text("# tool\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "switch", "-c", "main"], cwd=repo, check=True, capture_output=True, text=True)


def _git_commit(repo):
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

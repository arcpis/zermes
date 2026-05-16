import json
import os
from pathlib import Path

from code_modification.approval import build_approval_plan, write_approval_documents
from code_modification.executor import ExecutionState, commit_task_step, start_approved_task, write_state
from code_modification.governance import build_task_record_layout
from tools.code_modification_tool import (
    COMMIT_CODE_TASK_STEP_SCHEMA,
    COMPLETE_CODE_TASK_SCHEMA,
    FINALIZE_CODE_TASK_BRANCH_SCHEMA,
    GET_CODE_TASK_STATUS_SCHEMA,
    PLAN_CODE_TASK_VERIFICATION_SCHEMA,
    RECORD_CODE_TASK_SAFETY_REVIEW_SCHEMA,
    RUN_CODE_TASK_VERIFICATION_SCHEMA,
    SELF_EVOLUTION_THINKING_SCHEMA,
    SELF_UPDATE_APPLICATION_SCHEMA,
    START_APPROVED_CODE_TASK_SCHEMA,
    complete_code_task,
    plan_code_task_verification,
    record_code_task_safety_review,
    run_code_task_verification,
    self_evolution_thinking,
    self_update_application,
)


def test_complete_code_task_writes_plan_and_approval_for_clear_requirement(tmp_path):
    project_root = tmp_path / "hermes-agent"
    _make_project_repo(project_root)

    result = json.loads(
        complete_code_task(
            "Add a new terminal safety check",
            context="Terminal commands are handled by tools/terminal_tool.py.",
            affected_areas=["tools/terminal_tool.py"],
            project_root=str(project_root),
        )
    )

    assert result["success"] is True
    assert result["recommend_execution"] is True
    assert result["open_questions"] == []
    assert result["development_branch"].startswith("self-evolution/dev/")

    plan_path = project_root.parent / "self-evolution" / "tasks" / result["task_id"] / "plan.md"
    approval_path = project_root.parent / "self-evolution" / "tasks" / result["task_id"] / "approval.md"
    assert result["plan_path"] == str(plan_path)
    assert result["approval_path"] == str(approval_path)
    assert result["context_state_path"].endswith("context-state.json")
    assert result["task_context_summary_path"].endswith("task-context-summary.md")
    assert result["docs_summary_path"].endswith("docs-summary.json")
    assert "tools/terminal_tool.py" in plan_path.read_text(encoding="utf-8")
    assert "## Analysis Context" in plan_path.read_text(encoding="utf-8")
    assert "Approval Request" in approval_path.read_text(encoding="utf-8")


def test_complete_code_task_reports_documentation_update_candidates(tmp_path):
    project_root = tmp_path / "hermes-agent"
    _make_project_repo(project_root)
    (project_root / "AGENTS.md").write_text("# Rules\n", encoding="utf-8")
    (project_root / "README.md").write_text("# Hermes\n", encoding="utf-8")

    result = json.loads(
        complete_code_task(
            "Update the tool schema and document the user-facing command",
            project_root=str(project_root),
        )
    )

    assert "AGENTS.md" in result["documentation_updates"]
    assert "README.md" in result["documentation_updates"]


def test_complete_code_task_for_vague_requirement_requests_clarification(tmp_path):
    project_root = tmp_path / "hermes-agent"
    _make_project_repo(project_root)

    result = json.loads(complete_code_task("Improve", project_root=str(project_root)))

    assert result["success"] is True
    assert result["recommend_execution"] is False
    assert result["open_questions"] == [
        "Please describe the target behavior and expected outcome.",
    ]
    assert (project_root.parent / "self-evolution" / "tasks" / result["task_id"] / "plan.md").exists()


def test_complete_code_task_requires_requirement_and_does_not_create_records(tmp_path):
    project_root = tmp_path / "hermes-agent"
    _make_project_repo(project_root)

    result = json.loads(complete_code_task("  ", project_root=str(project_root)))

    assert "error" in result
    assert not (project_root.parent / "self-evolution").exists()


def test_complete_code_task_rejects_non_list_affected_areas(tmp_path):
    project_root = tmp_path / "hermes-agent"
    _make_project_repo(project_root)

    try:
        complete_code_task(
            "Fix the flaky retry behavior",
            affected_areas="tools/retry.py",  # type: ignore[arg-type]
            project_root=str(project_root),
        )
    except TypeError as exc:
        assert "affected_areas must be a list of strings" in str(exc)
    else:
        raise AssertionError("Expected TypeError for non-list affected_areas")


def test_verification_tools_return_structured_results(tmp_path):
    project_root = tmp_path / "hermes-agent"
    _make_project_repo(project_root)
    plan, layout = build_approval_plan(
        "Add verification workflow support",
        project_root,
        affected_areas=("code_modification",),
    )
    write_approval_documents(plan, layout)
    start_approved_task(plan.task_id, approval_text="approved", project_root=project_root)
    (project_root / "code_modification").mkdir(exist_ok=True)
    (project_root / "code_modification" / "marker.py").write_text("VALUE = 1\n", encoding="utf-8")
    commit_task_step(
        plan.task_id,
        summary="Add verification marker",
        files=["code_modification/marker.py"],
        project_root=project_root,
    )

    planned = json.loads(
        plan_code_task_verification(plan.task_id, project_root=str(project_root))
    )
    assert planned["success"] is True
    assert planned["status"] == "verification_planned"
    assert planned["planned_commands"]

    verified = json.loads(
        run_code_task_verification(
            plan.task_id,
            commands=["python -m compileall code_modification/marker.py"],
            project_root=str(project_root),
        )
    )
    assert verified["success"] is True
    assert verified["status"] == "verification_passed"
    assert verified["passed_commands"] == [
        "python -m compileall code_modification/marker.py",
    ]

    reviewed = json.loads(
        record_code_task_safety_review(
            plan.task_id,
            ["Does the workflow avoid broad staging?"],
            answers=["Yes."],
            conclusion="passed",
            project_root=str(project_root),
        )
    )
    assert reviewed["success"] is True
    assert reviewed["status"] == "safety_reviewed"


def test_self_evolution_thinking_tool_rejects_unknown_action(tmp_path):
    project_root = tmp_path / "hermes-agent"
    _make_project_repo(project_root)

    result = json.loads(
        self_evolution_thinking("unknown", project_root=str(project_root))
    )

    assert result["success"] is False
    assert "status, enable, disable, or run_once" in result["error"]


def test_self_update_application_runtime_actions_manage_release_switch(tmp_path):
    project_root = tmp_path / "hermes-agent"
    _make_project_repo(project_root)
    prefix = tmp_path / "zermes"
    _make_runtime_release(prefix, "source-install", project_root)
    candidate_id = "update-20260516-010000-abcdef0"
    release_id = "release-abcdef0"

    prepared = json.loads(
        self_update_application(
            "runtime_prepare",
            "20260516-010000-update-flow",
            project_root=str(project_root),
            install_prefix=str(prefix),
            candidate_id=candidate_id,
            candidate_ref="HEAD",
            expected_old_release_id="source-install",
        )
    )
    verified = json.loads(
        self_update_application(
            "runtime_verify",
            "20260516-010000-update-flow",
            install_prefix=str(prefix),
            candidate_id=candidate_id,
            health_checks=["cli help passed"],
        )
    )
    promoted = json.loads(
        self_update_application(
            "runtime_promote",
            "20260516-010000-update-flow",
            install_prefix=str(prefix),
            candidate_id=candidate_id,
            release_id=release_id,
        )
    )
    activated = json.loads(
        self_update_application(
            "runtime_activate",
            "20260516-010000-update-flow",
            install_prefix=str(prefix),
            release_id=release_id,
            approval_text="approved",
            expected_old_release_id="source-install",
        )
    )
    rolled_back = json.loads(
        self_update_application(
            "runtime_rollback",
            "20260516-010000-update-flow",
            install_prefix=str(prefix),
            approval_text="approved",
        )
    )
    status = json.loads(
        self_update_application(
            "runtime_status",
            "20260516-010000-update-flow",
            install_prefix=str(prefix),
        )
    )

    assert prepared["success"] is True
    assert prepared["candidate_id"] == candidate_id
    assert verified["status"] == "verified"
    assert promoted["release_id"] == release_id
    assert activated["release_id"] == release_id
    assert rolled_back["release_id"] == "source-install"
    assert status["active_release"]["release_id"] == "source-install"
    assert status["previous_release"]["release_id"] == release_id
    assert status["update_state"]["status"] == "rolled_back"
    assert status["update_state"]["steps"][-1] == "rolled_back"
    assert not (prefix / "runtime" / "update.lock").exists()
    assert json.loads((prefix / "runtime" / "active.json").read_text(encoding="utf-8"))[
        "release_id"
    ] == "source-install"


def test_self_update_application_runtime_actions_mirror_audit_state(tmp_path):
    project_root = tmp_path / "hermes-agent"
    _make_project_repo(project_root)
    task_id = "20260516-030000-runtime-audit"
    _write_integrated_state(project_root, task_id)
    prefix = tmp_path / "zermes"
    _make_runtime_release(prefix, "source-install", project_root)
    candidate_id = "update-20260516-030000-abcdef0"
    release_id = "release-abcdef0"

    prepared = json.loads(
        self_update_application(
            "runtime_prepare",
            task_id,
            project_root=str(project_root),
            install_prefix=str(prefix),
            candidate_id=candidate_id,
            candidate_ref="HEAD",
            expected_old_release_id="source-install",
        )
    )
    verified = json.loads(
        self_update_application(
            "runtime_run_health",
            task_id,
            install_prefix=str(prefix),
            candidate_id=candidate_id,
            health_checks=["python_version", "cli_help"],
        )
    )
    promoted = json.loads(
        self_update_application(
            "runtime_promote",
            task_id,
            install_prefix=str(prefix),
            candidate_id=candidate_id,
            release_id=release_id,
        )
    )
    activated = json.loads(
        self_update_application(
            "runtime_activate",
            task_id,
            install_prefix=str(prefix),
            release_id=release_id,
            approval_text="approved",
            expected_old_release_id="source-install",
        )
    )
    rolled_back = json.loads(
        self_update_application(
            "runtime_rollback",
            task_id,
            install_prefix=str(prefix),
            approval_text="approved",
            reason="test rollback",
        )
    )

    layout = build_task_record_layout(project_root, task_id)
    audit_payload = json.loads((layout.task_dir / "update-state.json").read_text(encoding="utf-8"))
    audit_report = (layout.task_dir / "update-application.md").read_text(encoding="utf-8")
    assert prepared["audit_status"] == "prepared"
    assert verified["audit_status"] == "verified"
    assert promoted["audit_status"] == "verified"
    assert activated["audit_status"] == "restart_pending"
    assert rolled_back["audit_status"] == "rolled_back"
    assert audit_payload["status"] == "rolled_back"
    assert audit_payload["restart_required"] is True
    assert "Runtime release was activated" in audit_report
    assert "Runtime rollback restored" in audit_report


def test_self_update_application_runtime_activate_rejects_stale_active_digest(tmp_path):
    project_root = tmp_path / "hermes-agent"
    _make_project_repo(project_root)
    prefix = tmp_path / "zermes"
    _make_runtime_release(prefix, "source-install", project_root)
    candidate_id = "update-20260516-035000-digest"
    release_id = "release-digest"

    json.loads(
        self_update_application(
            "runtime_prepare",
            "20260516-035000-digest",
            project_root=str(project_root),
            install_prefix=str(prefix),
            candidate_id=candidate_id,
            candidate_ref="HEAD",
        )
    )
    json.loads(
        self_update_application(
            "runtime_verify",
            "20260516-035000-digest",
            install_prefix=str(prefix),
            candidate_id=candidate_id,
            health_checks=["cli help passed"],
        )
    )
    json.loads(
        self_update_application(
            "runtime_promote",
            "20260516-035000-digest",
            install_prefix=str(prefix),
            candidate_id=candidate_id,
            release_id=release_id,
        )
    )
    status = json.loads(
        self_update_application(
            "runtime_status",
            "20260516-035000-digest",
            install_prefix=str(prefix),
        )
    )
    active_path = prefix / "runtime" / "active.json"
    active_payload = json.loads(active_path.read_text(encoding="utf-8"))
    active_payload["candidate_commit"] = "changed-after-status"
    active_path.write_text(json.dumps(active_payload, indent=2) + "\n", encoding="utf-8")

    activated = json.loads(
        self_update_application(
            "runtime_activate",
            "20260516-035000-digest",
            install_prefix=str(prefix),
            release_id=release_id,
            approval_text="approved",
            expected_old_release_id="source-install",
            expected_old_active_digest=status["active_release_digest"],
        )
    )

    assert activated["success"] is False
    assert "active release metadata changed" in activated["error"]
    assert json.loads(active_path.read_text(encoding="utf-8"))["release_id"] == "source-install"
    assert not (prefix / "runtime" / "previous.json").exists()


def test_self_update_application_runtime_prepare_does_not_require_audit_task(tmp_path):
    project_root = tmp_path / "hermes-agent"
    _make_project_repo(project_root)
    prefix = tmp_path / "zermes"
    _make_runtime_release(prefix, "source-install", project_root)
    candidate_id = "update-20260516-040000-no-audit"

    result = json.loads(
        self_update_application(
            "runtime_prepare",
            "20260516-040000-no-audit",
            project_root=str(project_root),
            install_prefix=str(prefix),
            candidate_id=candidate_id,
            candidate_ref="HEAD",
        )
    )

    assert result["success"] is True
    assert result["candidate_id"] == candidate_id
    assert "audit_status" not in result
    assert not (project_root.parent / "self-evolution" / "tasks" / "20260516-040000-no-audit").exists()


def test_self_update_application_runtime_run_health_can_verify_candidate(tmp_path):
    project_root = tmp_path / "hermes-agent"
    _make_project_repo(project_root)
    prefix = tmp_path / "zermes"
    _make_runtime_release(prefix, "source-install", project_root)
    candidate_id = "update-20260516-010000-abcdef0"

    json.loads(
        self_update_application(
            "runtime_prepare",
            "20260516-010000-update-flow",
            project_root=str(project_root),
            install_prefix=str(prefix),
            candidate_id=candidate_id,
            candidate_ref="HEAD",
        )
    )
    result = json.loads(
        self_update_application(
            "runtime_run_health",
            "20260516-010000-update-flow",
            install_prefix=str(prefix),
            candidate_id=candidate_id,
            health_checks=["python_version", "cli_help"],
        )
    )

    assert result["success"] is True
    assert result["status"] == "verified"
    assert [item["status"] for item in result["health_results"]] == ["passed", "passed"]


def test_self_update_application_runtime_run_health_can_verify_launcher_entrypoints(tmp_path):
    project_root = tmp_path / "hermes-agent"
    _make_project_repo(project_root)
    prefix = tmp_path / "zermes"
    _make_runtime_release(prefix, "source-install", project_root)
    candidate_id = "update-20260516-010000-abcdef0"

    json.loads(
        self_update_application(
            "runtime_prepare",
            "20260516-010000-update-flow",
            project_root=str(project_root),
            install_prefix=str(prefix),
            candidate_id=candidate_id,
            candidate_ref="HEAD",
        )
    )
    result = json.loads(
        self_update_application(
            "runtime_run_health",
            "20260516-010000-update-flow",
            install_prefix=str(prefix),
            candidate_id=candidate_id,
            health_checks=["launcher_cli_help", "launcher_gateway_help"],
            python_path=os.sys.executable,
        )
    )

    assert result["success"] is True
    assert result["status"] == "verified"
    assert [item["name"] for item in result["health_results"]] == [
        "launcher_cli_help",
        "launcher_gateway_help",
    ]


def test_self_update_application_runtime_prepare_env_creates_venv(tmp_path):
    project_root = tmp_path / "hermes-agent"
    _make_project_repo(project_root)
    prefix = tmp_path / "zermes"
    _make_runtime_release(prefix, "source-install", project_root)
    candidate_id = "update-20260516-010000-abcdef0"

    json.loads(
        self_update_application(
            "runtime_prepare",
            "20260516-010000-update-flow",
            project_root=str(project_root),
            install_prefix=str(prefix),
            candidate_id=candidate_id,
            candidate_ref="HEAD",
        )
    )
    result = json.loads(
        self_update_application(
            "runtime_prepare_env",
            "20260516-010000-update-flow",
            install_prefix=str(prefix),
            candidate_id=candidate_id,
        )
    )

    assert result["success"] is True
    assert result["status"] == "env_prepared"
    assert result["command_results"][0]["name"] == "create_venv"
    assert (prefix / "runtime" / "candidates" / candidate_id / "venv" / "bin" / "python").exists()


def test_self_update_application_runtime_action_rejects_existing_lock(tmp_path):
    prefix = tmp_path / "zermes"
    lock_path = prefix / "runtime" / "update.lock"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text(
        json.dumps(
            {
                "operation": "runtime_prepare",
                "created_at": "2026-05-16T01:00:00Z",
                "pid": 123,
                "hostname": "tests",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = json.loads(
        self_update_application(
            "runtime_verify",
            "20260516-010000-update-flow",
            install_prefix=str(prefix),
            candidate_id="update-20260516-010000-abcdef0",
            health_checks=["cli help passed"],
        )
    )

    assert result["success"] is False
    assert "already in progress" in result["error"]


def test_self_update_application_runtime_action_requires_install_prefix(tmp_path):
    result = json.loads(
        self_update_application(
            "runtime_verify",
            "20260516-010000-update-flow",
            candidate_id="update-20260516-010000-abcdef0",
            health_checks=["cli help passed"],
        )
    )

    assert result["success"] is False
    assert "install_prefix is required" in result["error"]


def test_code_modification_tool_schemas_include_install_prefix():
    schemas = [
        COMPLETE_CODE_TASK_SCHEMA,
        START_APPROVED_CODE_TASK_SCHEMA,
        COMMIT_CODE_TASK_STEP_SCHEMA,
        FINALIZE_CODE_TASK_BRANCH_SCHEMA,
        GET_CODE_TASK_STATUS_SCHEMA,
        PLAN_CODE_TASK_VERIFICATION_SCHEMA,
        RUN_CODE_TASK_VERIFICATION_SCHEMA,
        RECORD_CODE_TASK_SAFETY_REVIEW_SCHEMA,
        SELF_EVOLUTION_THINKING_SCHEMA,
        SELF_UPDATE_APPLICATION_SCHEMA,
    ]

    for schema in schemas:
        assert "install_prefix" in schema["parameters"]["properties"]


def test_self_update_application_schema_lists_launcher_health_checks():
    description = SELF_UPDATE_APPLICATION_SCHEMA["parameters"]["properties"]["health_checks"][
        "description"
    ]

    assert "launcher_cli_help" in description
    assert "launcher_gateway_help" in description


def _make_project_repo(repo):
    _write_project_markers(repo)
    _init_git_repo(repo)


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


def _init_git_repo(repo):
    import subprocess

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
    (repo / "README.md").write_text("initial\n", encoding="utf-8")
    (repo / "cli.py").write_text(
        "import argparse\nargparse.ArgumentParser().parse_args()\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "switch", "-c", "main"], cwd=repo, check=True, capture_output=True, text=True)


def _git_commit(repo):
    import subprocess

    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_project_markers(repo):
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "pyproject.toml").write_text("[project]\nname = 'hermes-agent'\n", encoding="utf-8")
    (repo / "install.py").write_text("# installer\n", encoding="utf-8")
    (repo / "code_modification").mkdir(exist_ok=True)
    (repo / "launcher").mkdir(exist_ok=True)
    launcher_source = Path(__file__).resolve().parents[2] / "launcher" / "zermes_launcher.py"
    (repo / "launcher" / "zermes_launcher.py").write_text(
        launcher_source.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (repo / "hermes_cli").mkdir(exist_ok=True)
    (repo / "hermes_cli" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "hermes_cli" / "main.py").write_text(
        (
            "import argparse\n"
            "def main():\n"
            "    parser = argparse.ArgumentParser()\n"
            "    parser.add_argument('command', nargs='?')\n"
            "    parser.parse_args()\n"
            "if __name__ == '__main__':\n"
            "    main()\n"
        ),
        encoding="utf-8",
    )
    tools_dir = repo / "tools"
    tools_dir.mkdir(exist_ok=True)
    (tools_dir / "code_modification_tool.py").write_text("# tool\n", encoding="utf-8")


def _make_runtime_release(prefix, release_id, source_repo):
    release_root = prefix / "runtime" / "releases" / release_id
    (release_root / "source").mkdir(parents=True)
    (release_root / "venv").mkdir()
    (release_root / "build").mkdir()
    payload = {
        "schema_version": 1,
        "release_id": release_id,
        "source_path": str(release_root / "source"),
        "venv_path": str(release_root / "venv"),
        "build_path": str(release_root / "build"),
        "candidate_commit": "0000000",
        "source_repo": {"path": str(source_repo)},
        "activated_at": "",
    }
    (release_root / "metadata.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    active_path = prefix / "runtime" / "active.json"
    active_path.parent.mkdir(parents=True, exist_ok=True)
    active_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

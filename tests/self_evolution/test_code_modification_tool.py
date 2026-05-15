import json

from code_modification.approval import build_approval_plan, write_approval_documents
from code_modification.executor import commit_task_step, start_approved_task
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


def _make_project_repo(repo):
    _write_project_markers(repo)
    _init_git_repo(repo)


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
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "switch", "-c", "main"], cwd=repo, check=True, capture_output=True, text=True)


def _write_project_markers(repo):
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "pyproject.toml").write_text("[project]\nname = 'hermes-agent'\n", encoding="utf-8")
    (repo / "install.py").write_text("# installer\n", encoding="utf-8")
    (repo / "code_modification").mkdir(exist_ok=True)
    tools_dir = repo / "tools"
    tools_dir.mkdir(exist_ok=True)
    (tools_dir / "code_modification_tool.py").write_text("# tool\n", encoding="utf-8")

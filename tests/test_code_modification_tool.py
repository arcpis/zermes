import json

from code_modification.approval import build_approval_plan, write_approval_documents
from code_modification.executor import commit_task_step, start_approved_task
from tools.code_modification_tool import (
    complete_code_task,
    plan_code_task_verification,
    record_code_task_safety_review,
    run_code_task_verification,
    self_evolution_thinking,
)


def test_complete_code_task_writes_plan_and_approval_for_clear_requirement(tmp_path):
    project_root = tmp_path / "hermes-agent"
    project_root.mkdir()

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
    assert "tools/terminal_tool.py" in plan_path.read_text(encoding="utf-8")
    assert "Approval Request" in approval_path.read_text(encoding="utf-8")


def test_complete_code_task_for_vague_requirement_requests_clarification(tmp_path):
    project_root = tmp_path / "hermes-agent"
    project_root.mkdir()

    result = json.loads(complete_code_task("Improve", project_root=str(project_root)))

    assert result["success"] is True
    assert result["recommend_execution"] is False
    assert result["open_questions"] == [
        "Please describe the target behavior and expected outcome.",
    ]
    assert (project_root.parent / "self-evolution" / "tasks" / result["task_id"] / "plan.md").exists()


def test_complete_code_task_requires_requirement_and_does_not_create_records(tmp_path):
    project_root = tmp_path / "hermes-agent"
    project_root.mkdir()

    result = json.loads(complete_code_task("  ", project_root=str(project_root)))

    assert "error" in result
    assert not (project_root.parent / "self-evolution").exists()


def test_complete_code_task_rejects_non_list_affected_areas(tmp_path):
    project_root = tmp_path / "hermes-agent"
    project_root.mkdir()

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
    project_root.mkdir()
    _init_git_repo(project_root)
    plan, layout = build_approval_plan(
        "Add verification workflow support",
        project_root,
        affected_areas=("code_modification",),
    )
    write_approval_documents(plan, layout)
    start_approved_task(plan.task_id, approval_text="approved", project_root=project_root)
    (project_root / "code_modification").mkdir()
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
    project_root.mkdir()

    result = json.loads(
        self_evolution_thinking("unknown", project_root=str(project_root))
    )

    assert result["success"] is False
    assert "status, enable, disable, or run_once" in result["error"]


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
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "switch", "-c", "main"], cwd=repo, check=True, capture_output=True, text=True)

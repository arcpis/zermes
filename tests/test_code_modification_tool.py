import json

from tools.code_modification_tool import complete_code_task


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

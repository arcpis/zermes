from datetime import UTC, datetime

from code_modification.approval import (
    build_approval_plan,
    render_approval_markdown,
    render_plan_markdown,
    write_approval_documents,
)


def test_build_approval_plan_for_clear_requirement(tmp_path):
    project_root = tmp_path / "hermes-agent"
    project_root.mkdir()
    now = datetime(2026, 5, 2, 3, 4, 5, tzinfo=UTC)

    plan, layout = build_approval_plan(
        "Add a new terminal safety check",
        project_root,
        install_prefix=tmp_path / "zermes",
        affected_areas=("tools/terminal_tool.py",),
        now=now,
    )

    assert plan.task_id == "20260502-030405-add-a-new-terminal-safety-check"
    assert plan.requirement_summary == "Add a new terminal safety check"
    assert plan.affected_areas == ("tools/terminal_tool.py",)
    assert plan.open_questions == ()
    assert plan.recommend_execution is True
    assert plan.development_branch == (
        "self-evolution/dev/20260502-030405-add-a-new-terminal-safety-check"
    )
    assert layout.plan_path.name == "plan.md"
    assert layout.approval_path.name == "approval.md"


def test_build_approval_plan_for_vague_requirement_requests_clarification(tmp_path):
    project_root = tmp_path / "hermes-agent"
    project_root.mkdir()

    plan, _ = build_approval_plan("Improve", project_root, install_prefix=tmp_path / "zermes")

    assert plan.recommend_execution is False
    assert plan.open_questions == (
        "Please describe the target behavior and expected outcome.",
    )
    assert plan.tasks == ("Collect missing requirement details.", "Regenerate the approval plan.")


def test_render_plan_contains_required_sections(tmp_path):
    project_root = tmp_path / "hermes-agent"
    project_root.mkdir()

    plan, _ = build_approval_plan(
        "Fix the flaky retry behavior",
        project_root,
        install_prefix=tmp_path / "zermes",
    )
    rendered = render_plan_markdown(plan)

    for heading in (
        "## Boundary",
        "## Affected Areas",
        "## Proposed Approach",
        "## Tasks",
        "## Estimates",
        "## Risks",
        "## Test Plan",
        "## Open Questions",
    ):
        assert heading in rendered
    assert "Product code changes, git branch creation" in rendered


def test_render_approval_forbids_code_changes_before_approval(tmp_path):
    project_root = tmp_path / "hermes-agent"
    project_root.mkdir()

    plan, _ = build_approval_plan(
        "Fix the flaky retry behavior",
        project_root,
        install_prefix=tmp_path / "zermes",
    )
    rendered = render_approval_markdown(plan)

    assert "Product code changes before approval: `forbidden`" in rendered
    assert "Please approve before implementation starts." in rendered


def test_write_approval_documents_only_writes_audit_files(tmp_path):
    project_root = tmp_path / "hermes-agent"
    project_root.mkdir()

    plan, layout = build_approval_plan(
        "Fix the flaky retry behavior",
        project_root,
        install_prefix=tmp_path / "zermes",
    )
    write_approval_documents(plan, layout)

    assert layout.plan_path.exists()
    assert layout.approval_path.exists()
    assert "Pre-Change Plan" in layout.plan_path.read_text(encoding="utf-8")
    assert "Approval Request" in layout.approval_path.read_text(encoding="utf-8")
    assert not layout.change_log_path.exists()
    assert not layout.verification_path.exists()

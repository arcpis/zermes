from datetime import UTC, datetime
from pathlib import Path
import tomllib

from code_modification.governance import (
    AUDIT_FILE_NAMES,
    DEFAULT_INTEGRATION_BRANCH,
    GovernancePolicy,
    build_development_branch_name,
    build_task_record_layout,
    get_evolution_workspace,
    make_task_id,
)


def test_evolution_workspace_is_next_to_project_root(tmp_path):
    project_root = tmp_path / "hermes-agent"
    project_root.mkdir()

    assert get_evolution_workspace(project_root) == tmp_path / "self-evolution"


def test_task_id_is_timestamped_and_readable():
    now = datetime(2026, 5, 2, 3, 4, 5, tzinfo=UTC)

    assert make_task_id("Add a new tool!", now=now) == "20260502-030405-add-a-new-tool"


def test_development_branch_uses_self_evolution_namespace():
    branch_name = build_development_branch_name("20260502-030405-add-tool")

    assert branch_name == "self-evolution/dev/20260502-030405-add-tool"


def test_task_record_layout_defines_audit_and_temp_paths(tmp_path):
    project_root = tmp_path / "hermes-agent"
    project_root.mkdir()

    layout = build_task_record_layout(project_root, "20260502-030405-add-tool")

    task_dir = tmp_path / "self-evolution" / "tasks" / "20260502-030405-add-tool"
    assert layout.task_id == "20260502-030405-add-tool"
    assert layout.workspace_dir == tmp_path / "self-evolution"
    assert layout.task_dir == task_dir
    assert layout.temp_dir == task_dir / "temp"
    assert layout.thinking_path == task_dir / "thinking.md"
    assert layout.plan_path == task_dir / "plan.md"
    assert layout.approval_path == task_dir / "approval.md"
    assert layout.change_log_path == task_dir / "change-log.md"
    assert layout.verification_path == task_dir / "verification.md"
    assert layout.final_report_path == task_dir / "final-report.md"
    assert not task_dir.exists()


def test_audit_file_names_cover_required_records():
    assert AUDIT_FILE_NAMES == {
        "thinking": "thinking.md",
        "plan": "plan.md",
        "approval": "approval.md",
        "change_log": "change-log.md",
        "verification": "verification.md",
        "final_report": "final-report.md",
    }


def test_default_policy_forbids_unsafe_evolution_behavior():
    policy = GovernancePolicy()

    assert policy.validate() == []
    assert policy.require_user_approval_before_code_changes is True
    assert policy.require_small_commits is True
    assert policy.require_detailed_commit_messages is True
    assert policy.allow_automatic_main_merge is False
    assert DEFAULT_INTEGRATION_BRANCH == "self-evolution/main"


def test_policy_reports_violations():
    policy = GovernancePolicy(
        require_user_approval_before_code_changes=False,
        require_small_commits=False,
        require_detailed_commit_messages=False,
        allow_automatic_main_merge=True,
    )

    assert policy.validate() == [
        "user_approval_required",
        "small_commits_required",
        "detailed_commit_messages_required",
        "automatic_main_merge_forbidden",
    ]


def test_code_modification_package_is_included():
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    package_includes = data["tool"]["setuptools"]["packages"]["find"]["include"]

    assert "code_modification" in package_includes

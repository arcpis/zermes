from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
import tomllib

from code_modification.governance import (
    AUDIT_FILE_NAMES,
    DEFAULT_INTEGRATION_BRANCH,
    GovernancePolicy,
    ProjectRootResolutionError,
    build_development_branch_name,
    build_task_record_layout,
    get_evolution_workspace,
    make_task_id,
    resolve_self_evolution_project_root,
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
    pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    package_includes = data["tool"]["setuptools"]["packages"]["find"]["include"]

    assert "code_modification" in package_includes


def test_resolve_project_root_prefers_explicit_path(tmp_path):
    repo = _make_project_repo(tmp_path / "explicit")
    cwd_repo = _make_project_repo(tmp_path / "cwd")

    previous = Path.cwd()
    try:
        import os

        os.chdir(cwd_repo)
        assert resolve_self_evolution_project_root(str(repo)) == repo
    finally:
        os.chdir(previous)


def test_resolve_project_root_accepts_valid_cwd(tmp_path):
    repo = _make_project_repo(tmp_path / "hermes-agent")

    previous = Path.cwd()
    try:
        import os

        os.chdir(repo)
        assert resolve_self_evolution_project_root() == repo
    finally:
        os.chdir(previous)


def test_resolve_project_root_reads_install_state_source_repo(tmp_path):
    repo = _make_project_repo(tmp_path / "source")
    prefix = tmp_path / "app"
    state_path = prefix / "runtime" / "install-state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps({"source_repo": {"path": str(repo)}}),
        encoding="utf-8",
    )

    assert (
        resolve_self_evolution_project_root(install_prefix=prefix, allow_cwd=False)
        == repo
    )


def test_resolve_project_root_reads_active_source_repo(tmp_path):
    repo = _make_project_repo(tmp_path / "source")
    prefix = tmp_path / "app"
    active_path = prefix / "runtime" / "active.json"
    active_path.parent.mkdir(parents=True)
    active_path.write_text(
        json.dumps(
            {
                "source_path": str(prefix / "runtime" / "releases" / "r1" / "source"),
                "source_repo": {"path": str(repo)},
            }
        ),
        encoding="utf-8",
    )

    assert (
        resolve_self_evolution_project_root(install_prefix=prefix, allow_cwd=False)
        == repo
    )


def test_resolve_project_root_reads_configured_source_repo(tmp_path, monkeypatch):
    repo = _make_project_repo(tmp_path / "source")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("ZERMES_HOME", str(home))
    (home / "config.yaml").write_text(
        f"self_evolution:\n  source_repo: {repo}\n",
        encoding="utf-8",
    )

    assert resolve_self_evolution_project_root(allow_cwd=False) == repo


def test_resolve_project_root_reports_missing_source(tmp_path):
    try:
        resolve_self_evolution_project_root(
            str(tmp_path / "missing"),
            allow_cwd=False,
        )
    except ProjectRootResolutionError as exc:
        assert "Pass project_root" in str(exc)
    else:
        raise AssertionError("Expected missing project root to fail")


def test_resolve_project_root_rejects_release_source_copy(tmp_path):
    prefix = tmp_path / "app"
    release_source = _make_project_repo(
        prefix / "runtime" / "releases" / "release-1" / "source"
    )

    try:
        resolve_self_evolution_project_root(
            str(release_source),
            install_prefix=prefix,
        )
    except ProjectRootResolutionError as exc:
        assert "runtime release/candidate source copy" in str(exc)
    else:
        raise AssertionError("Expected release source copy to fail")


def test_resolve_project_root_rejects_candidate_source_copy(tmp_path):
    prefix = tmp_path / "app"
    candidate_source = _make_project_repo(
        prefix / "runtime" / "candidates" / "candidate-1" / "source"
    )

    try:
        resolve_self_evolution_project_root(
            str(candidate_source),
            install_prefix=prefix,
        )
    except ProjectRootResolutionError as exc:
        assert "runtime release/candidate source copy" in str(exc)
    else:
        raise AssertionError("Expected candidate source copy to fail")


def test_resolve_project_root_rejects_non_git_root(tmp_path):
    project_root = tmp_path / "not-git"
    _write_project_markers(project_root)

    try:
        resolve_self_evolution_project_root(str(project_root), allow_cwd=False)
    except ProjectRootResolutionError as exc:
        assert "git repository root" in str(exc)
    else:
        raise AssertionError("Expected non-git root to fail")


def _make_project_repo(path: Path) -> Path:
    _write_project_markers(path)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    return path.resolve()


def _write_project_markers(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "pyproject.toml").write_text("[project]\nname = 'hermes-agent'\n", encoding="utf-8")
    (path / "install.py").write_text("# installer\n", encoding="utf-8")
    (path / "code_modification").mkdir(exist_ok=True)
    tools_dir = path / "tools"
    tools_dir.mkdir(exist_ok=True)
    (tools_dir / "code_modification_tool.py").write_text("# tool\n", encoding="utf-8")

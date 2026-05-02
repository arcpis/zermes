import subprocess

from code_modification.approval import build_approval_plan, write_approval_documents
from code_modification.executor import (
    CodeTaskExecutionError,
    commit_task_step,
    describe_task_execution,
    finalize_task_branch,
    start_approved_task,
)
from code_modification.git_workflow import current_branch
from code_modification.governance import DEFAULT_INTEGRATION_BRANCH
from code_modification.verifier import run_task_verification


def run_git(repo, *args):
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def init_repo(tmp_path):
    repo = tmp_path / "hermes-agent"
    repo.mkdir()
    run_git(repo, "init")
    run_git(repo, "config", "user.email", "tests@example.com")
    run_git(repo, "config", "user.name", "Tests")
    (repo / "README.md").write_text("initial\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "Initial commit")
    run_git(repo, "switch", "-c", "main")
    return repo


def create_approval_record(
    repo,
    requirement="Add approved workflow support",
    affected_areas=(),
):
    plan, layout = build_approval_plan(requirement, repo, affected_areas=affected_areas)
    write_approval_documents(plan, layout)
    return plan, layout


def test_start_approved_task_requires_approval_record(tmp_path):
    repo = init_repo(tmp_path)

    try:
        start_approved_task("missing-task", approval_text="approved", project_root=repo)
    except CodeTaskExecutionError as exc:
        assert "approval record is missing" in str(exc)
    else:
        raise AssertionError("Expected missing approval record to fail")


def test_start_approved_task_requires_explicit_approval(tmp_path):
    repo = init_repo(tmp_path)
    plan, _layout = create_approval_record(repo)

    try:
        start_approved_task(plan.task_id, approval_text="please wait", project_root=repo)
    except CodeTaskExecutionError as exc:
        assert "explicit user approval is required" in str(exc)
    else:
        raise AssertionError("Expected missing approval to fail")


def test_start_commit_and_finalize_approved_task(tmp_path):
    repo = init_repo(tmp_path)
    plan, layout = create_approval_record(repo)

    state = start_approved_task(plan.task_id, approval_text="approved", project_root=repo)

    assert state.status == "branch_created"
    assert current_branch(repo) == plan.development_branch
    assert state.plan_steps
    assert layout.change_log_path.exists()

    (repo / "workflow.txt").write_text("workflow\n", encoding="utf-8")
    committed, commit_hash = commit_task_step(
        plan.task_id,
        summary="Add workflow marker",
        files=["workflow.txt"],
        verification_summary="not run",
        project_root=repo,
    )

    assert committed.status == "committed"
    assert commit_hash
    assert committed.commits[0].commit_hash == commit_hash
    assert committed.commits[0].files == ("workflow.txt",)
    assert committed.plan_steps[0].status == "completed"
    assert committed.plan_steps[0].commit_hash == commit_hash
    assert "Add workflow marker" in layout.change_log_path.read_text(encoding="utf-8")

    run_task_verification(
        plan.task_id,
        commands=["python -m compileall workflow.txt"],
        project_root=repo,
    )

    integrated = finalize_task_branch(plan.task_id, project_root=repo)

    assert integrated.status == "integrated"
    assert current_branch(repo) == DEFAULT_INTEGRATION_BRANCH
    assert run_git(repo, "rev-parse", "--verify", "main")
    assert "integrated" in layout.change_log_path.read_text(encoding="utf-8")
    assert "Final Report" in layout.final_report_path.read_text(encoding="utf-8")


def test_describe_task_execution_returns_state_and_audit_paths(tmp_path):
    repo = init_repo(tmp_path)
    plan, layout = create_approval_record(repo)

    status_before_start = describe_task_execution(plan.task_id, project_root=repo)

    assert status_before_start["has_plan"] is True
    assert status_before_start["has_approval"] is True
    assert status_before_start["has_change_log"] is False
    assert status_before_start["state"] is None

    state = start_approved_task(plan.task_id, approval_text="approved", project_root=repo)
    status_after_start = describe_task_execution(plan.task_id, project_root=repo)

    assert status_after_start["state"]["status"] == state.status
    assert status_after_start["state"]["plan_steps"]
    assert status_after_start["change_log_path"] == str(layout.change_log_path)


def test_finalize_task_branch_requires_at_least_one_commit(tmp_path):
    repo = init_repo(tmp_path)
    plan, _layout = create_approval_record(repo)
    start_approved_task(plan.task_id, approval_text="approved", project_root=repo)

    try:
        finalize_task_branch(plan.task_id, project_root=repo)
    except CodeTaskExecutionError as exc:
        assert "at least one task commit is required" in str(exc)
    else:
        raise AssertionError("Expected finalize without commits to fail")


def test_finalize_task_branch_requires_passed_verification(tmp_path):
    repo = init_repo(tmp_path)
    plan, _layout = create_approval_record(repo)
    start_approved_task(plan.task_id, approval_text="approved", project_root=repo)
    (repo / "workflow.txt").write_text("workflow\n", encoding="utf-8")
    commit_task_step(
        plan.task_id,
        summary="Add workflow marker",
        files=["workflow.txt"],
        project_root=repo,
    )

    try:
        finalize_task_branch(plan.task_id, project_root=repo)
    except CodeTaskExecutionError as exc:
        assert "stage 4 verification must pass before finalizing" in str(exc)
    else:
        raise AssertionError("Expected finalize without verification to fail")


def test_finalize_task_branch_rejects_failed_verification(tmp_path):
    repo = init_repo(tmp_path)
    plan, _layout = create_approval_record(repo)
    start_approved_task(plan.task_id, approval_text="approved", project_root=repo)
    (repo / "workflow.txt").write_text("workflow\n", encoding="utf-8")
    commit_task_step(
        plan.task_id,
        summary="Add workflow marker",
        files=["workflow.txt"],
        project_root=repo,
    )
    (repo / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    try:
        run_task_verification(
            plan.task_id,
            commands=["python -m compileall broken.py"],
            project_root=repo,
        )
    except Exception:
        pass

    try:
        finalize_task_branch(plan.task_id, project_root=repo)
    except CodeTaskExecutionError as exc:
        assert "stage 4 verification must pass before finalizing" in str(exc)
    else:
        raise AssertionError("Expected finalize with failed verification to fail")


def test_commit_task_step_requires_task_branch(tmp_path):
    repo = init_repo(tmp_path)
    plan, _layout = create_approval_record(repo)
    start_approved_task(plan.task_id, approval_text="approved", project_root=repo)
    run_git(repo, "switch", "main")

    try:
        commit_task_step(
            plan.task_id,
            summary="Add workflow marker",
            files=["README.md"],
            project_root=repo,
        )
    except CodeTaskExecutionError as exc:
        assert "current branch must be" in str(exc)
    else:
        raise AssertionError("Expected commit from the wrong branch to fail")


def test_commit_task_step_rejects_files_outside_approved_areas(tmp_path):
    repo = init_repo(tmp_path)
    plan, _layout = create_approval_record(repo, affected_areas=("allowed",))
    start_approved_task(plan.task_id, approval_text="approved", project_root=repo)
    (repo / "outside.txt").write_text("outside\n", encoding="utf-8")

    try:
        commit_task_step(
            plan.task_id,
            summary="Add outside file",
            files=["outside.txt"],
            project_root=repo,
        )
    except CodeTaskExecutionError as exc:
        assert "outside the approved areas" in str(exc)
    else:
        raise AssertionError("Expected file outside approved areas to fail")


def test_commit_task_step_can_mark_explicit_plan_step(tmp_path):
    repo = init_repo(tmp_path)
    plan, _layout = create_approval_record(repo)
    start_approved_task(plan.task_id, approval_text="approved", project_root=repo)
    (repo / "workflow.txt").write_text("workflow\n", encoding="utf-8")

    committed, _commit_hash = commit_task_step(
        plan.task_id,
        summary="Add workflow marker",
        files=["workflow.txt"],
        plan_step_index=1,
        project_root=repo,
    )

    assert committed.plan_steps[0].status == "pending"
    assert committed.plan_steps[1].status == "completed"

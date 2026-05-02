import subprocess

from code_modification.approval import build_approval_plan, write_approval_documents
from code_modification.executor import CodeTaskExecutionError, commit_task_step, start_approved_task
from code_modification.git_workflow import current_branch
from code_modification.verifier import (
    CodeTaskVerificationError,
    VerificationCommand,
    VerificationState,
    describe_task_verification,
    plan_task_verification,
    record_task_safety_review,
    run_task_verification,
    write_verification_state,
)


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


def create_committed_task(repo, affected_areas=("code_modification",)):
    plan, layout = build_approval_plan(
        "Add verification workflow support",
        repo,
        affected_areas=affected_areas,
    )
    write_approval_documents(plan, layout)
    start_approved_task(plan.task_id, approval_text="approved", project_root=repo)
    (repo / "code_modification").mkdir(exist_ok=True)
    (repo / "code_modification" / "marker.py").write_text("VALUE = 1\n", encoding="utf-8")
    state, commit_hash = commit_task_step(
        plan.task_id,
        summary="Add verification marker",
        files=["code_modification/marker.py"],
        verification_summary="not run",
        project_root=repo,
    )
    return plan, layout, state, commit_hash


def test_plan_task_verification_writes_plan_and_state(tmp_path):
    repo = init_repo(tmp_path)
    plan, layout, _state, commit_hash = create_committed_task(repo)

    verification = plan_task_verification(plan.task_id, project_root=repo)

    assert verification.status == "verification_planned"
    assert verification.development_branch == plan.development_branch
    assert verification.commits == (commit_hash,)
    assert verification.planned_commands
    assert layout.verification_path.exists()
    assert "verification_planned" in layout.verification_path.read_text(encoding="utf-8")


def test_plan_task_verification_requires_task_branch(tmp_path):
    repo = init_repo(tmp_path)
    plan, _layout, _state, _commit_hash = create_committed_task(repo)
    run_git(repo, "switch", "main")

    try:
        plan_task_verification(plan.task_id, project_root=repo)
    except CodeTaskExecutionError as exc:
        assert "current branch must be" in str(exc)
    else:
        raise AssertionError("Expected verification from the wrong branch to fail")


def test_plan_task_verification_requires_commits(tmp_path):
    repo = init_repo(tmp_path)
    plan, layout = build_approval_plan("Add verification workflow support", repo)
    write_approval_documents(plan, layout)
    start_approved_task(plan.task_id, approval_text="approved", project_root=repo)

    try:
        plan_task_verification(plan.task_id, project_root=repo)
    except CodeTaskVerificationError as exc:
        assert "at least one task commit is required" in str(exc)
    else:
        raise AssertionError("Expected verification without commits to fail")


def test_run_task_verification_records_passed_command(tmp_path):
    repo = init_repo(tmp_path)
    plan, layout, _state, _commit_hash = create_committed_task(repo)

    verification = run_task_verification(
        plan.task_id,
        commands=["python -m compileall code_modification/marker.py"],
        project_root=repo,
    )

    assert verification.status == "verification_passed"
    assert verification.command_results[0].status == "passed"
    text = layout.verification_path.read_text(encoding="utf-8")
    assert "verification_passed" in text
    assert "python -m compileall code_modification/marker.py" in text


def test_run_task_verification_records_failed_command(tmp_path):
    repo = init_repo(tmp_path)
    plan, layout, _state, _commit_hash = create_committed_task(repo)
    (repo / "code_modification" / "broken.py").write_text("def broken(:\n", encoding="utf-8")

    try:
        run_task_verification(
            plan.task_id,
            commands=["python -m compileall code_modification/broken.py"],
            project_root=repo,
        )
    except CodeTaskVerificationError as exc:
        assert "verification failed" in str(exc)
    else:
        raise AssertionError("Expected failed verification command to fail")

    text = layout.verification_path.read_text(encoding="utf-8")
    assert "verification_failed" in text
    assert "broken.py" in text


def test_run_task_verification_rejects_unsafe_command(tmp_path):
    repo = init_repo(tmp_path)
    plan, _layout, _state, _commit_hash = create_committed_task(repo)

    try:
        run_task_verification(plan.task_id, commands=["git reset --hard"], project_root=repo)
    except CodeTaskVerificationError as exc:
        assert "verification command is not allowed" in str(exc)
    else:
        raise AssertionError("Expected unsafe verification command to fail")


def test_describe_task_verification_reports_latest_state(tmp_path):
    repo = init_repo(tmp_path)
    plan, layout, _state, _commit_hash = create_committed_task(repo)
    run_task_verification(
        plan.task_id,
        commands=["python -m compileall code_modification/marker.py"],
        project_root=repo,
    )

    status = describe_task_verification(plan.task_id, project_root=repo)

    assert status["has_verification"] is True
    assert status["verification_status"] == "verification_passed"
    assert status["verification_path"] == str(layout.verification_path)


def test_non_required_failed_command_is_recorded_without_failing_state(tmp_path):
    repo = init_repo(tmp_path)
    plan, layout, _state, commit_hash = create_committed_task(repo)
    (repo / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    state = VerificationState(
        task_id=plan.task_id,
        status="verification_planned",
        project_root=str(repo),
        development_branch=plan.development_branch,
        commits=(commit_hash,),
        planned_commands=(
            VerificationCommand(
                command=("python", "-m", "compileall", "broken.py"),
                purpose="Record an optional compile check failure.",
                required=False,
            ),
        ),
    )
    write_verification_state(layout.task_dir / "verification-state.json", state)

    verified = run_task_verification(plan.task_id, project_root=repo)

    assert verified.status == "verification_passed"
    assert verified.command_results[0].status == "failed"
    assert verified.command_results[0].required is False


def test_record_task_safety_review_rejects_unknown_conclusion(tmp_path):
    repo = init_repo(tmp_path)
    plan, _layout, _state, _commit_hash = create_committed_task(repo)

    try:
        record_task_safety_review(
            plan.task_id,
            questions=["Was the safety boundary reviewed?"],
            conclusion="maybe",
            project_root=repo,
        )
    except CodeTaskVerificationError as exc:
        assert "safety review conclusion must be" in str(exc)
    else:
        raise AssertionError("Expected unknown safety conclusion to fail")


def test_record_task_safety_review_writes_questions_and_conclusion(tmp_path):
    repo = init_repo(tmp_path)
    plan, layout, _state, _commit_hash = create_committed_task(repo)

    review = record_task_safety_review(
        plan.task_id,
        questions=["Does the workflow avoid broad staging?"],
        answers=["Yes, only explicit files are staged."],
        conclusion="passed",
        project_root=repo,
    )

    assert review.status == "safety_reviewed"
    assert review.safety_review.conclusion == "passed"
    text = layout.verification_path.read_text(encoding="utf-8")
    assert "Does the workflow avoid broad staging?" in text
    assert "Conclusion: `passed`" in text
    assert current_branch(repo) == plan.development_branch

import subprocess

from code_modification.git_workflow import (
    GitWorkflowError,
    create_or_switch_development_branch,
    current_branch,
    normalize_files,
)


def run_git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, text=True, check=True, capture_output=True)


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


def test_create_or_switch_development_branch_requires_clean_worktree(tmp_path):
    repo = init_repo(tmp_path)
    (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    try:
        create_or_switch_development_branch(repo, "self-evolution/dev/test-task")
    except GitWorkflowError as exc:
        assert "working tree must be clean" in str(exc)
    else:
        raise AssertionError("Expected dirty worktree to block branch creation")


def test_create_or_switch_development_branch_uses_required_namespace(tmp_path):
    repo = init_repo(tmp_path)

    try:
        create_or_switch_development_branch(repo, "feature/test-task")
    except GitWorkflowError as exc:
        assert "self-evolution/dev" in str(exc)
    else:
        raise AssertionError("Expected invalid branch namespace to fail")


def test_create_or_switch_development_branch_switches_to_task_branch(tmp_path):
    repo = init_repo(tmp_path)

    create_or_switch_development_branch(repo, "self-evolution/dev/test-task")

    assert current_branch(repo) == "self-evolution/dev/test-task"


def test_normalize_files_rejects_broad_staging(tmp_path):
    repo = init_repo(tmp_path)

    try:
        normalize_files(repo, ["."])
    except GitWorkflowError as exc:
        assert "explicit paths" in str(exc)
    else:
        raise AssertionError("Expected broad staging to fail")


def test_normalize_files_rejects_paths_outside_project_root(tmp_path):
    repo = init_repo(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")

    try:
        normalize_files(repo, [str(outside)])
    except GitWorkflowError as exc:
        assert "inside project_root" in str(exc)
    else:
        raise AssertionError("Expected outside path to fail")

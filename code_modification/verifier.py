"""Verification workflow for approved self-evolution tasks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

from .executor import (
    CodeTaskExecutionError,
    append_change_log,
    read_markdown_bullets,
    read_state,
    require_task_branch,
    require_task_repo_lock,
)
from .git_workflow import current_branch, require_git_repository
from .governance import build_task_record_layout


VERIFICATION_STATE_FILE_NAME = "verification-state.json"
DEFAULT_TIMEOUT_SECONDS = 300
OUTPUT_SNIPPET_CHARS = 2000


class CodeTaskVerificationError(RuntimeError):
    """Raised when a self-evolution task cannot be verified safely."""


@dataclass(frozen=True)
class VerificationCommand:
    command: tuple[str, ...]
    purpose: str
    required: bool = True
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS


@dataclass(frozen=True)
class VerificationResult:
    command: tuple[str, ...]
    purpose: str
    required: bool
    exit_code: int | None
    duration_seconds: float
    stdout_summary: str
    stderr_summary: str
    status: str


@dataclass(frozen=True)
class SafetyReviewRecord:
    questions: tuple[str, ...]
    answers: tuple[str, ...] = ()
    conclusion: str = ""


@dataclass(frozen=True)
class VerificationState:
    task_id: str
    status: str
    project_root: str
    development_branch: str
    commits: tuple[str, ...]
    planned_commands: tuple[VerificationCommand, ...] = ()
    command_results: tuple[VerificationResult, ...] = ()
    safety_review: SafetyReviewRecord | None = None
    blocked_reason: str = ""


def plan_task_verification(
    task_id: str,
    *,
    project_root: str | Path,
    install_prefix: str | Path | None = None,
    workspace_dir: str | Path | None = None,
    include_full_suite: bool = False,
) -> VerificationState:
    root = require_git_repository(project_root)
    layout = build_task_record_layout(
        root,
        task_id,
        install_prefix=install_prefix,
        workspace_dir=workspace_dir,
    )
    execution_state = read_state(layout.task_dir / "execution-state.json")
    require_verifiable_execution_state(execution_state.status, bool(execution_state.commits))
    require_task_branch(root, execution_state.development_branch)
    require_task_repo_lock(root, execution_state, install_prefix=install_prefix, workspace_dir=workspace_dir)

    commands = tuple(
        build_verification_commands(
            root,
            affected_areas=execution_state.approved_areas,
            committed_files=committed_files(execution_state.commits),
            include_full_suite=include_full_suite,
        )
    )
    state = VerificationState(
        task_id=execution_state.task_id,
        status="verification_planned",
        project_root=str(root),
        development_branch=execution_state.development_branch,
        commits=tuple(commit.commit_hash for commit in execution_state.commits),
        planned_commands=commands,
    )
    write_verification_state(layout.task_dir / VERIFICATION_STATE_FILE_NAME, state)
    append_verification_markdown(
        layout.verification_path,
        "verification_planned",
        [
            f"Development branch: `{state.development_branch}`",
            f"Current branch: `{current_branch(root)}`",
            f"Commits: {', '.join(state.commits)}",
            "Plan test items:",
            *[f"  - {item}" for item in read_markdown_bullets(layout.plan_path, "Test Plan")],
            "Planned commands:",
            *[f"  - `{format_command(command.command)}` ({command.purpose})" for command in commands],
        ],
    )
    append_change_log(
        layout.change_log_path,
        "verification_planned",
        [f"Verification path: `{layout.verification_path}`", f"Commands: {len(commands)}"],
    )
    return state


def run_task_verification(
    task_id: str,
    *,
    commands: list[str] | None = None,
    project_root: str | Path,
    install_prefix: str | Path | None = None,
    workspace_dir: str | Path | None = None,
) -> VerificationState:
    root = require_git_repository(project_root)
    layout = build_task_record_layout(
        root,
        task_id,
        install_prefix=install_prefix,
        workspace_dir=workspace_dir,
    )
    execution_state = read_state(layout.task_dir / "execution-state.json")
    require_verifiable_execution_state(execution_state.status, bool(execution_state.commits))
    require_task_branch(root, execution_state.development_branch)
    require_task_repo_lock(root, execution_state, install_prefix=install_prefix, workspace_dir=workspace_dir)

    state_path = layout.task_dir / VERIFICATION_STATE_FILE_NAME
    state = read_verification_state(state_path) if state_path.exists() else plan_task_verification(
        task_id,
        project_root=root,
        install_prefix=install_prefix,
        workspace_dir=workspace_dir,
    )
    planned_commands = tuple(parse_user_command(command) for command in commands) if commands else state.planned_commands
    if not planned_commands:
        raise CodeTaskVerificationError("no verification commands are planned")

    running = replace_verification_state(state, "verification_running", planned_commands=planned_commands)
    write_verification_state(state_path, running)
    append_verification_markdown(
        layout.verification_path,
        "verification_running",
        [f"Commands: {len(planned_commands)}"],
    )

    results = tuple(run_verification_command(root, command) for command in planned_commands)
    failed_required = [result for result in results if result.required and result.status != "passed"]
    status = "verification_failed" if failed_required else "verification_passed"
    blocked_reason = "; ".join(format_command(result.command) for result in failed_required)
    updated = replace_verification_state(
        running,
        status,
        command_results=results,
        blocked_reason=blocked_reason,
    )
    write_verification_state(state_path, updated)
    append_verification_results(layout.verification_path, status, results)
    append_change_log(
        layout.change_log_path,
        status,
        [
            f"Passed commands: {sum(1 for result in results if result.status == 'passed')}",
            f"Failed commands: {sum(1 for result in results if result.status != 'passed')}",
            f"Verification path: `{layout.verification_path}`",
        ],
    )
    if failed_required:
        raise CodeTaskVerificationError(f"verification failed: {blocked_reason}")
    return updated


def record_task_safety_review(
    task_id: str,
    *,
    questions: list[str],
    answers: list[str] | None = None,
    conclusion: str = "",
    project_root: str | Path,
    install_prefix: str | Path | None = None,
    workspace_dir: str | Path | None = None,
) -> VerificationState:
    root = require_git_repository(project_root)
    layout = build_task_record_layout(
        root,
        task_id,
        install_prefix=install_prefix,
        workspace_dir=workspace_dir,
    )
    execution_state = read_state(layout.task_dir / "execution-state.json")
    require_task_branch(root, execution_state.development_branch)
    require_task_repo_lock(root, execution_state, install_prefix=install_prefix, workspace_dir=workspace_dir)
    clean_questions = tuple(item.strip() for item in questions if item.strip())
    if not clean_questions:
        raise CodeTaskVerificationError("at least one safety review question is required")
    clean_answers = tuple(str(item).strip() for item in (answers or []) if str(item).strip())
    clean_conclusion = conclusion.strip() or "inconclusive"
    allowed_conclusions = {"passed", "failed", "inconclusive", "not_required"}
    if clean_conclusion not in allowed_conclusions:
        raise CodeTaskVerificationError(
            "safety review conclusion must be passed, failed, inconclusive, or not_required"
        )

    state_path = layout.task_dir / VERIFICATION_STATE_FILE_NAME
    state = read_verification_state(state_path) if state_path.exists() else VerificationState(
        task_id=execution_state.task_id,
        status="verification_planned",
        project_root=str(root),
        development_branch=execution_state.development_branch,
        commits=tuple(commit.commit_hash for commit in execution_state.commits),
    )
    review = SafetyReviewRecord(
        questions=clean_questions,
        answers=clean_answers,
        conclusion=clean_conclusion,
    )
    updated = replace_verification_state(state, "safety_reviewed", safety_review=review)
    write_verification_state(state_path, updated)
    append_verification_markdown(
        layout.verification_path,
        "safety_reviewed",
        [
            "Questions:",
            *[f"  - {question}" for question in review.questions],
            "Answers:",
            *[f"  - {answer}" for answer in (review.answers or ("not recorded",))],
            f"Conclusion: `{review.conclusion}`",
        ],
    )
    append_change_log(
        layout.change_log_path,
        "safety_reviewed",
        [f"Conclusion: `{review.conclusion}`", f"Questions: {len(review.questions)}"],
    )
    return updated


def describe_task_verification(
    task_id: str,
    *,
    project_root: str | Path,
    install_prefix: str | Path | None = None,
    workspace_dir: str | Path | None = None,
) -> dict:
    root = require_git_repository(project_root)
    layout = build_task_record_layout(
        root,
        task_id,
        install_prefix=install_prefix,
        workspace_dir=workspace_dir,
    )
    state_path = layout.task_dir / VERIFICATION_STATE_FILE_NAME
    state = read_verification_state(state_path) if state_path.exists() else None
    return {
        "has_verification": layout.verification_path.exists(),
        "verification_path": str(layout.verification_path),
        "verification_state_path": str(state_path),
        "verification_status": state.status if state else None,
        "verification_state": verification_state_to_dict(state) if state else None,
    }


def require_verifiable_execution_state(status: str, has_commits: bool) -> None:
    if status == "blocked":
        raise CodeTaskVerificationError("blocked tasks cannot be verified")
    if not has_commits:
        raise CodeTaskVerificationError("at least one task commit is required before verification")


def committed_files(commits) -> tuple[str, ...]:
    files: list[str] = []
    for commit in commits:
        files.extend(commit.files)
    return tuple(dict.fromkeys(files))


def build_verification_commands(
    project_root: Path,
    *,
    affected_areas: tuple[str, ...],
    committed_files: tuple[str, ...],
    include_full_suite: bool,
) -> list[VerificationCommand]:
    areas = tuple(area.replace("\\", "/") for area in (*affected_areas, *committed_files))
    commands: list[VerificationCommand] = []
    if any(area.startswith("code_modification/") or area == "tools/code_modification_tool.py" for area in areas):
        test_files = [
            "tests/self_evolution/test_code_modification_governance.py",
            "tests/self_evolution/test_code_modification_approval.py",
            "tests/self_evolution/test_code_modification_executor.py",
            "tests/self_evolution/test_code_modification_git_workflow.py",
            "tests/self_evolution/test_code_modification_tool.py",
            "tests/test_model_tools.py",
            "tests/test_toolsets.py",
        ]
        commands.append(
            VerificationCommand(
                command=("scripts/run_tests.sh", *test_files),
                purpose="Run focused self-evolution and tool registration tests.",
                timeout_seconds=900,
            )
        )
    elif any(area.startswith("tools/") or area == "toolsets.py" or area == "model_tools.py" for area in areas):
        commands.append(
            VerificationCommand(
                command=("scripts/run_tests.sh", "tests/test_model_tools.py", "tests/test_toolsets.py"),
                purpose="Run tool registration and toolset tests.",
                timeout_seconds=600,
            )
        )
    else:
        commands.append(
            VerificationCommand(
                command=("scripts/run_tests.sh", "tests/self_evolution/test_code_modification_executor.py"),
                purpose="Run a focused self-evolution workflow smoke test.",
                timeout_seconds=600,
            )
        )

    compile_targets = compile_targets_for(project_root, committed_files)
    if compile_targets:
        commands.append(
            VerificationCommand(
                command=("python", "-m", "compileall", *compile_targets),
                purpose="Compile changed Python files or packages.",
                timeout_seconds=300,
            )
        )
    if include_full_suite:
        commands.append(
            VerificationCommand(
                command=("scripts/run_tests.sh",),
                purpose="Run the full hermetic test suite.",
                timeout_seconds=3600,
            )
        )
    return commands


def compile_targets_for(project_root: Path, files: tuple[str, ...]) -> tuple[str, ...]:
    targets = []
    for file_name in files:
        if file_name.endswith(".py") and (project_root / file_name).exists():
            targets.append(file_name)
    return tuple(targets)


def parse_user_command(command: str) -> VerificationCommand:
    argv = tuple(shlex.split(command, posix=os.name != "nt"))
    if not argv:
        raise CodeTaskVerificationError("verification command cannot be empty")
    require_allowed_command(argv)
    return VerificationCommand(command=argv, purpose="User-provided verification command.")


def require_allowed_command(argv: tuple[str, ...]) -> None:
    # Verification commands are intentionally allow-listed so this workflow
    # cannot become a general terminal execution backdoor.
    normalized = tuple(part.replace("\\", "/") for part in argv)
    if normalized[0] == "scripts/run_tests.sh":
        return
    if len(normalized) >= 3 and normalized[:3] == ("python", "-m", "compileall"):
        return
    if len(normalized) >= 3 and normalized[:3] == ("python", "-m", "py_compile"):
        return
    if len(normalized) >= 2 and normalized[:2] == ("ruff", "check"):
        return
    if normalized[0] == "mypy":
        return
    if normalized in {("hermes", "--help"), ("hermes", "doctor", "--help")}:
        return
    raise CodeTaskVerificationError(f"verification command is not allowed: {format_command(argv)}")


def run_verification_command(project_root: Path, command: VerificationCommand) -> VerificationResult:
    require_allowed_command(command.command)
    argv = list(command.command)
    if len(argv) >= 3 and argv[0] == "python" and argv[1] == "-m":
        argv[0] = sys.executable
    started = time.monotonic()
    try:
        result = subprocess.run(
            argv,
            cwd=project_root,
            text=True,
            capture_output=True,
            check=False,
            timeout=command.timeout_seconds,
        )
        duration = time.monotonic() - started
        status = "passed" if result.returncode == 0 else "failed"
        return VerificationResult(
            command=command.command,
            purpose=command.purpose,
            required=command.required,
            exit_code=result.returncode,
            duration_seconds=duration,
            stdout_summary=summarize_output(result.stdout),
            stderr_summary=summarize_output(result.stderr),
            status=status,
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - started
        return VerificationResult(
            command=command.command,
            purpose=command.purpose,
            required=command.required,
            exit_code=None,
            duration_seconds=duration,
            stdout_summary=summarize_output(exc.stdout or ""),
            stderr_summary=summarize_output(exc.stderr or "command timed out"),
            status="timeout",
        )
    except OSError as exc:
        duration = time.monotonic() - started
        return VerificationResult(
            command=command.command,
            purpose=command.purpose,
            required=command.required,
            exit_code=None,
            duration_seconds=duration,
            stdout_summary="",
            stderr_summary=str(exc),
            status="blocked",
        )


def summarize_output(text: str) -> str:
    clean = str(text or "").strip()
    if len(clean) <= OUTPUT_SNIPPET_CHARS:
        return clean
    half = OUTPUT_SNIPPET_CHARS // 2
    return f"{clean[:half]}\n... truncated {len(clean) - OUTPUT_SNIPPET_CHARS} chars ...\n{clean[-half:]}"


def read_verification_state(path: Path) -> VerificationState:
    data = json.loads(path.read_text(encoding="utf-8"))
    planned_commands = tuple(
        VerificationCommand(
            command=tuple(item["command"]),
            purpose=item["purpose"],
            required=item.get("required", True),
            timeout_seconds=item.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS),
        )
        for item in data.pop("planned_commands", [])
    )
    command_results = tuple(
        VerificationResult(
            command=tuple(item["command"]),
            purpose=item["purpose"],
            required=item.get("required", True),
            exit_code=item.get("exit_code"),
            duration_seconds=item.get("duration_seconds", 0.0),
            stdout_summary=item.get("stdout_summary", ""),
            stderr_summary=item.get("stderr_summary", ""),
            status=item.get("status", ""),
        )
        for item in data.pop("command_results", [])
    )
    safety_data = data.pop("safety_review", None)
    safety_review = (
        SafetyReviewRecord(
            questions=tuple(safety_data.get("questions", [])),
            answers=tuple(safety_data.get("answers", [])),
            conclusion=safety_data.get("conclusion", ""),
        )
        if safety_data
        else None
    )
    return VerificationState(
        **data,
        planned_commands=planned_commands,
        command_results=command_results,
        safety_review=safety_review,
    )


def write_verification_state(path: Path, state: VerificationState) -> None:
    # Keep machine-readable state separate from verification.md, which remains
    # append-only and optimized for human audit.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(verification_state_to_dict(state), indent=2), encoding="utf-8")


def verification_state_to_dict(state: VerificationState) -> dict:
    data = asdict(state)
    data["planned_commands"] = [
        {**asdict(command), "command": list(command.command)}
        for command in state.planned_commands
    ]
    data["command_results"] = [
        {**asdict(result), "command": list(result.command)}
        for result in state.command_results
    ]
    return data


def replace_verification_state(
    state: VerificationState,
    status: str,
    *,
    planned_commands: tuple[VerificationCommand, ...] | None = None,
    command_results: tuple[VerificationResult, ...] | None = None,
    safety_review: SafetyReviewRecord | None = None,
    blocked_reason: str | None = None,
) -> VerificationState:
    return VerificationState(
        task_id=state.task_id,
        status=status,
        project_root=state.project_root,
        development_branch=state.development_branch,
        commits=state.commits,
        planned_commands=state.planned_commands if planned_commands is None else planned_commands,
        command_results=state.command_results if command_results is None else command_results,
        safety_review=state.safety_review if safety_review is None else safety_review,
        blocked_reason=state.blocked_reason if blocked_reason is None else blocked_reason,
    )


def append_verification_markdown(path: Path, status: str, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).isoformat()
    rendered_lines = [f"# Verification\n"] if not path.exists() else []
    rendered_lines.extend([f"## {timestamp} - {status}", ""])
    rendered_lines.extend(f"- {line}" for line in lines)
    rendered_lines.append("")
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(rendered_lines))
        handle.write("\n")


def append_verification_results(
    path: Path,
    status: str,
    results: tuple[VerificationResult, ...],
) -> None:
    lines = []
    for result in results:
        lines.extend(
            [
                f"Command: `{format_command(result.command)}`",
                f"Purpose: {result.purpose}",
                f"Status: `{result.status}`",
                f"Exit code: `{result.exit_code}`",
                f"Duration seconds: `{result.duration_seconds:.2f}`",
                f"stdout: {result.stdout_summary or 'empty'}",
                f"stderr: {result.stderr_summary or 'empty'}",
            ]
        )
    append_verification_markdown(path, status, lines)


def format_command(command: tuple[str, ...]) -> str:
    return " ".join(command)

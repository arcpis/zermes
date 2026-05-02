#!/usr/bin/env python3
"""Self-evolution code modification planning tool."""

from __future__ import annotations

import os
from pathlib import Path

from code_modification.approval import build_approval_plan, write_approval_documents
from code_modification.executor import (
    CodeTaskExecutionError,
    commit_task_step,
    describe_task_execution,
    finalize_task_branch,
    start_approved_task,
)
from code_modification.git_workflow import GitWorkflowError
from code_modification.verifier import (
    CodeTaskVerificationError,
    describe_task_verification,
    plan_task_verification,
    record_task_safety_review,
    run_task_verification,
)
from tools.registry import registry, tool_error, tool_result


def complete_code_task(
    requirement: str,
    *,
    context: str = "",
    affected_areas: list[str] | None = None,
    project_root: str | None = None,
) -> str:
    """Create a pre-change approval plan without modifying product code."""
    clean_requirement = str(requirement or "").strip()
    if not clean_requirement:
        return tool_error("requirement is required.")

    clean_affected_areas = _clean_affected_areas(affected_areas)
    root = Path(project_root).expanduser() if project_root else Path(os.getcwd())

    plan, layout = build_approval_plan(
        clean_requirement,
        root,
        context=str(context or ""),
        affected_areas=tuple(clean_affected_areas),
    )
    write_approval_documents(plan, layout)

    return tool_result(
        success=True,
        task_id=plan.task_id,
        recommend_execution=plan.recommend_execution,
        open_questions=list(plan.open_questions),
        development_branch=plan.development_branch,
        plan_path=str(layout.plan_path),
        approval_path=str(layout.approval_path),
    )


def _clean_affected_areas(affected_areas: list[str] | None) -> list[str]:
    if affected_areas is None:
        return []
    if not isinstance(affected_areas, list):
        raise TypeError("affected_areas must be a list of strings.")
    return [str(area).strip() for area in affected_areas if str(area).strip()]


def start_approved_code_task(
    task_id: str,
    approval_text: str,
    *,
    project_root: str | None = None,
    base_branch: str | None = None,
) -> str:
    """Start an approved task by creating its dedicated development branch."""
    root = Path(project_root).expanduser() if project_root else Path(os.getcwd())
    try:
        state = start_approved_task(
            str(task_id or ""),
            approval_text=str(approval_text or ""),
            project_root=root,
            base_branch=str(base_branch).strip() if base_branch else None,
        )
    except (CodeTaskExecutionError, CodeTaskVerificationError, GitWorkflowError) as exc:
        return tool_error(str(exc), success=False)
    return _execution_state_result(state)


def commit_code_task_step(
    task_id: str,
    summary: str,
    files: list[str] | None,
    *,
    verification_summary: str = "",
    plan_step_index: int | None = None,
    project_root: str | None = None,
) -> str:
    """Commit one explicit implementation step for an approved task."""
    root = Path(project_root).expanduser() if project_root else Path(os.getcwd())
    try:
        state, commit_hash = commit_task_step(
            str(task_id or ""),
            summary=str(summary or ""),
            files=files or [],
            verification_summary=str(verification_summary or ""),
            plan_step_index=plan_step_index,
            project_root=root,
        )
    except (CodeTaskExecutionError, GitWorkflowError) as exc:
        return tool_error(str(exc), success=False)
    return _execution_state_result(state, commit_hash=commit_hash)


def finalize_code_task_branch(
    task_id: str,
    *,
    project_root: str | None = None,
) -> str:
    """Merge an approved task branch into the self-evolution integration branch."""
    root = Path(project_root).expanduser() if project_root else Path(os.getcwd())
    try:
        state = finalize_task_branch(str(task_id or ""), project_root=root)
    except (CodeTaskExecutionError, GitWorkflowError) as exc:
        return tool_error(str(exc), success=False)
    return _execution_state_result(state)


def get_code_task_status(
    task_id: str,
    *,
    project_root: str | None = None,
) -> str:
    """Return the audit and execution state for an approved code task."""
    root = Path(project_root).expanduser() if project_root else Path(os.getcwd())
    try:
        status = describe_task_execution(str(task_id or ""), project_root=root)
        status.update(describe_task_verification(str(task_id or ""), project_root=root))
    except (CodeTaskExecutionError, GitWorkflowError) as exc:
        return tool_error(str(exc), success=False)
    return tool_result(success=True, **status)


def plan_code_task_verification(
    task_id: str,
    *,
    project_root: str | None = None,
    include_full_suite: bool = False,
) -> str:
    """Create a verification plan for an approved task branch."""
    root = Path(project_root).expanduser() if project_root else Path(os.getcwd())
    try:
        state = plan_task_verification(
            str(task_id or ""),
            project_root=root,
            include_full_suite=bool(include_full_suite),
        )
    except (CodeTaskExecutionError, CodeTaskVerificationError, GitWorkflowError) as exc:
        return tool_error(str(exc), success=False)
    return _verification_state_result(state)


def run_code_task_verification(
    task_id: str,
    *,
    commands: list[str] | None = None,
    project_root: str | None = None,
) -> str:
    """Run planned or explicit verification commands for an approved task."""
    root = Path(project_root).expanduser() if project_root else Path(os.getcwd())
    try:
        state = run_task_verification(
            str(task_id or ""),
            commands=commands,
            project_root=root,
        )
    except (CodeTaskExecutionError, CodeTaskVerificationError, GitWorkflowError) as exc:
        return tool_error(str(exc), success=False)
    return _verification_state_result(state)


def record_code_task_safety_review(
    task_id: str,
    questions: list[str] | None,
    *,
    answers: list[str] | None = None,
    conclusion: str = "",
    project_root: str | None = None,
) -> str:
    """Record the isolated safety review result for an approved task."""
    root = Path(project_root).expanduser() if project_root else Path(os.getcwd())
    try:
        state = record_task_safety_review(
            str(task_id or ""),
            questions=questions or [],
            answers=answers,
            conclusion=str(conclusion or ""),
            project_root=root,
        )
    except (CodeTaskExecutionError, CodeTaskVerificationError, GitWorkflowError) as exc:
        return tool_error(str(exc), success=False)
    return _verification_state_result(state)


def _execution_state_result(state, **extra) -> str:
    # The result includes the audit path so callers can show the user exactly
    # where the approved execution record was updated.
    return tool_result(
        success=True,
        task_id=state.task_id,
        status=state.status,
        development_branch=state.development_branch,
        integration_branch=state.integration_branch,
        change_log_path=str(
            Path(state.project_root).parent
            / "self-evolution"
            / "tasks"
            / state.task_id
            / "change-log.md"
        ),
        final_report_path=str(
            Path(state.project_root).parent
            / "self-evolution"
            / "tasks"
            / state.task_id
            / "final-report.md"
        ),
        **extra,
    )


def _verification_state_result(state, **extra) -> str:
    verification_path = (
        Path(state.project_root).parent
        / "self-evolution"
        / "tasks"
        / state.task_id
        / "verification.md"
    )
    return tool_result(
        success=True,
        task_id=state.task_id,
        status=state.status,
        development_branch=state.development_branch,
        verification_path=str(verification_path),
        planned_commands=[
            " ".join(command.command) for command in state.planned_commands
        ],
        passed_commands=[
            " ".join(result.command)
            for result in state.command_results
            if result.status == "passed"
        ],
        failed_commands=[
            " ".join(result.command)
            for result in state.command_results
            if result.status != "passed"
        ],
        blocked_reason=state.blocked_reason,
        **extra,
    )


def check_code_modification_requirements() -> bool:
    """The approval planner has no external service requirements."""
    return True


COMPLETE_CODE_TASK_SCHEMA = {
    "name": "complete_code_task",
    "description": (
        "Create a self-evolution pre-change approval plan for a requested code "
        "change. Use this when the user asks Hermes to add a tool, fix a bug, "
        "optimize performance, improve interaction flow, or otherwise modify "
        "the codebase. Before calling, perform low-token, focused code reading "
        "only as needed, then pass confirmed module/file scope in affected_areas "
        "and a concise context summary. This tool only writes self-evolution "
        "audit documents; it must not implement code changes, create branches, "
        "run git commands, or execute builds."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "requirement": {
                "type": "string",
                "description": "Natural-language code modification request to analyze.",
            },
            "context": {
                "type": "string",
                "description": (
                    "Optional concise summary from focused code reading, recent "
                    "failures, user feedback, or existing self-evolution docs."
                ),
            },
            "affected_areas": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional list of confirmed modules, files, or subsystems "
                    "likely affected by the requested change."
                ),
            },
            "project_root": {
                "type": "string",
                "description": (
                    "Optional project root. Defaults to the current working directory; "
                    "the self-evolution workspace is placed next to this root."
                ),
            },
        },
        "required": ["requirement"],
    },
}

START_APPROVED_CODE_TASK_SCHEMA = {
    "name": "start_approved_code_task",
    "description": (
        "Start an explicitly approved self-evolution code task. This creates "
        "or switches to the task development branch after validating the "
        "approval record and a clean git working tree. Do not call before the "
        "user has clearly approved implementation."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Task id created by complete_code_task.",
            },
            "approval_text": {
                "type": "string",
                "description": "Exact user approval text or a concise approval summary.",
            },
            "project_root": {
                "type": "string",
                "description": "Optional git repository root. Defaults to the current directory.",
            },
            "base_branch": {
                "type": "string",
                "description": "Optional branch to use as the task base before creating the development branch.",
            },
        },
        "required": ["task_id", "approval_text"],
    },
}

COMMIT_CODE_TASK_STEP_SCHEMA = {
    "name": "commit_code_task_step",
    "description": (
        "Create one small git commit for an approved self-evolution task. "
        "The files list must contain explicit paths; broad staging is forbidden."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Task id created by complete_code_task.",
            },
            "summary": {
                "type": "string",
                "description": "Short English summary of the committed change.",
            },
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Explicit changed files to stage and commit.",
            },
            "verification_summary": {
                "type": "string",
                "description": "Truthful verification status, such as a test command or 'not run'.",
            },
            "plan_step_index": {
                "type": "integer",
                "description": "Optional zero-based plan step index completed by this commit.",
            },
            "project_root": {
                "type": "string",
                "description": "Optional git repository root. Defaults to the current directory.",
            },
        },
        "required": ["task_id", "summary", "files"],
    },
}

FINALIZE_CODE_TASK_BRANCH_SCHEMA = {
    "name": "finalize_code_task_branch",
    "description": (
        "Merge an approved self-evolution development branch into "
        "self-evolution/main. This never merges into the project main branch."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Task id created by complete_code_task.",
            },
            "project_root": {
                "type": "string",
                "description": "Optional git repository root. Defaults to the current directory.",
            },
        },
        "required": ["task_id"],
    },
}

GET_CODE_TASK_STATUS_SCHEMA = {
    "name": "get_code_task_status",
    "description": (
        "Return the approval record presence, execution state, and audit paths "
        "for a self-evolution code task."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Task id created by complete_code_task.",
            },
            "project_root": {
                "type": "string",
                "description": "Optional git repository root. Defaults to the current directory.",
            },
        },
        "required": ["task_id"],
    },
}

PLAN_CODE_TASK_VERIFICATION_SCHEMA = {
    "name": "plan_code_task_verification",
    "description": (
        "Create a verification plan for an approved self-evolution task branch. "
        "This records planned tests, compile checks, and optional full-suite "
        "coverage without running commands."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Task id created by complete_code_task.",
            },
            "project_root": {
                "type": "string",
                "description": "Optional git repository root. Defaults to the current directory.",
            },
            "include_full_suite": {
                "type": "boolean",
                "description": "When true, include the full scripts/run_tests.sh command in the plan.",
            },
        },
        "required": ["task_id"],
    },
}

RUN_CODE_TASK_VERIFICATION_SCHEMA = {
    "name": "run_code_task_verification",
    "description": (
        "Run planned or explicit safe verification commands for an approved "
        "self-evolution task branch and record the results."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Task id created by complete_code_task.",
            },
            "commands": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional explicit safe verification commands to run.",
            },
            "project_root": {
                "type": "string",
                "description": "Optional git repository root. Defaults to the current directory.",
            },
        },
        "required": ["task_id"],
    },
}

RECORD_CODE_TASK_SAFETY_REVIEW_SCHEMA = {
    "name": "record_code_task_safety_review",
    "description": (
        "Record isolated safety review questions, answers, and conclusion for "
        "an approved self-evolution task."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Task id created by complete_code_task.",
            },
            "questions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Safety review questions checked in isolation.",
            },
            "answers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional answers or findings for the safety review.",
            },
            "conclusion": {
                "type": "string",
                "description": "One of passed, failed, inconclusive, or not_required.",
            },
            "project_root": {
                "type": "string",
                "description": "Optional git repository root. Defaults to the current directory.",
            },
        },
        "required": ["task_id", "questions"],
    },
}


registry.register(
    name="complete_code_task",
    toolset="code_modification",
    schema=COMPLETE_CODE_TASK_SCHEMA,
    handler=lambda args, **kw: complete_code_task(
        requirement=args.get("requirement", ""),
        context=args.get("context", ""),
        affected_areas=args.get("affected_areas"),
        project_root=args.get("project_root"),
    ),
    check_fn=check_code_modification_requirements,
    emoji="🧭",
)

registry.register(
    name="start_approved_code_task",
    toolset="code_modification",
    schema=START_APPROVED_CODE_TASK_SCHEMA,
    handler=lambda args, **kw: start_approved_code_task(
        task_id=args.get("task_id", ""),
        approval_text=args.get("approval_text", ""),
        project_root=args.get("project_root"),
        base_branch=args.get("base_branch"),
    ),
    check_fn=check_code_modification_requirements,
    emoji="🌿",
)

registry.register(
    name="commit_code_task_step",
    toolset="code_modification",
    schema=COMMIT_CODE_TASK_STEP_SCHEMA,
    handler=lambda args, **kw: commit_code_task_step(
        task_id=args.get("task_id", ""),
        summary=args.get("summary", ""),
        files=args.get("files"),
        verification_summary=args.get("verification_summary", ""),
        plan_step_index=args.get("plan_step_index"),
        project_root=args.get("project_root"),
    ),
    check_fn=check_code_modification_requirements,
    emoji="✅",
)

registry.register(
    name="finalize_code_task_branch",
    toolset="code_modification",
    schema=FINALIZE_CODE_TASK_BRANCH_SCHEMA,
    handler=lambda args, **kw: finalize_code_task_branch(
        task_id=args.get("task_id", ""),
        project_root=args.get("project_root"),
    ),
    check_fn=check_code_modification_requirements,
    emoji="🔀",
)

registry.register(
    name="get_code_task_status",
    toolset="code_modification",
    schema=GET_CODE_TASK_STATUS_SCHEMA,
    handler=lambda args, **kw: get_code_task_status(
        task_id=args.get("task_id", ""),
        project_root=args.get("project_root"),
    ),
    check_fn=check_code_modification_requirements,
    emoji="📋",
)

registry.register(
    name="plan_code_task_verification",
    toolset="code_modification",
    schema=PLAN_CODE_TASK_VERIFICATION_SCHEMA,
    handler=lambda args, **kw: plan_code_task_verification(
        task_id=args.get("task_id", ""),
        project_root=args.get("project_root"),
        include_full_suite=args.get("include_full_suite", False),
    ),
    check_fn=check_code_modification_requirements,
    emoji="🧪",
)

registry.register(
    name="run_code_task_verification",
    toolset="code_modification",
    schema=RUN_CODE_TASK_VERIFICATION_SCHEMA,
    handler=lambda args, **kw: run_code_task_verification(
        task_id=args.get("task_id", ""),
        commands=args.get("commands"),
        project_root=args.get("project_root"),
    ),
    check_fn=check_code_modification_requirements,
    emoji="🔬",
)

registry.register(
    name="record_code_task_safety_review",
    toolset="code_modification",
    schema=RECORD_CODE_TASK_SAFETY_REVIEW_SCHEMA,
    handler=lambda args, **kw: record_code_task_safety_review(
        task_id=args.get("task_id", ""),
        questions=args.get("questions"),
        answers=args.get("answers"),
        conclusion=args.get("conclusion", ""),
        project_root=args.get("project_root"),
    ),
    check_fn=check_code_modification_requirements,
    emoji="🛡️",
)

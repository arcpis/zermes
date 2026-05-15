#!/usr/bin/env python3
"""Self-evolution code modification planning tool."""

from __future__ import annotations

from pathlib import Path

from code_modification.approval import build_approval_plan, write_approval_documents
from code_modification.executor import (
    CodeTaskExecutionError,
    commit_task_step,
    describe_task_execution,
    finalize_task_branch,
    require_explicit_approval,
    start_approved_task,
)
from code_modification.git_workflow import GitWorkflowError
from code_modification.governance import (
    ProjectRootResolutionError,
    resolve_self_evolution_project_root,
)
from code_modification.self_update import (
    SelfUpdateApplicationError,
    activate_self_update,
    describe_self_update_application,
    plan_self_update_application,
    prepare_self_update,
    record_self_update_build,
    record_self_update_health_check,
    rollback_self_update,
)
from code_modification.runtime_update import (
    RuntimeUpdateState,
    RuntimeUpdateError,
    activate_release as activate_runtime_release,
    mark_candidate_blocked,
    mark_candidate_verified,
    prepare_candidate_source,
    promote_candidate_to_release,
    read_active_release,
    read_previous_release,
    read_release as read_runtime_release,
    read_runtime_update_state,
    rollback_active_release,
    runtime_update_lock,
    write_runtime_update_state,
)
from code_modification.token_strategy import AnalysisHints, build_analysis_context
from code_modification.thinking import (
    SelfEvolutionThinkingError,
    describe_self_evolution_thinking,
    disable_self_evolution_thinking,
    enable_self_evolution_thinking,
    run_self_evolution_thinking,
)
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
    install_prefix: str | None = None,
) -> str:
    """Create a pre-change approval plan without modifying product code."""
    clean_requirement = str(requirement or "").strip()
    if not clean_requirement:
        return tool_error("requirement is required.")

    clean_affected_areas = _clean_affected_areas(affected_areas)
    try:
        root = _resolve_tool_project_root(project_root, install_prefix)
    except ProjectRootResolutionError as exc:
        return tool_error(str(exc), success=False)
    analysis_context = build_analysis_context(
        root,
        purpose="approval",
        hints=AnalysisHints(
            requirement=clean_requirement,
            explicit_paths=tuple(clean_affected_areas),
        ),
    )
    enriched_context = _merge_context_summary(
        str(context or ""),
        analysis_context.task_context_summary_path,
    )

    plan, layout = build_approval_plan(
        clean_requirement,
        root,
        context=enriched_context,
        affected_areas=tuple(clean_affected_areas),
        context_state_path=analysis_context.context_state_path,
        task_context_summary_path=analysis_context.task_context_summary_path,
        docs_summary_path=analysis_context.docs_summary_path,
        documentation_updates=analysis_context.documentation_updates,
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
        context_state_path=analysis_context.context_state_path,
        task_context_summary_path=analysis_context.task_context_summary_path,
        docs_summary_path=analysis_context.docs_summary_path,
        documentation_updates=list(analysis_context.documentation_updates),
    )


def _clean_affected_areas(affected_areas: list[str] | None) -> list[str]:
    if affected_areas is None:
        return []
    if not isinstance(affected_areas, list):
        raise TypeError("affected_areas must be a list of strings.")
    return [str(area).strip() for area in affected_areas if str(area).strip()]


def _merge_context_summary(context: str, task_context_summary_path: str) -> str:
    """Attach the reusable context path without copying large summaries."""
    clean_context = context.strip()
    summary_note = f"Reusable analysis context: {task_context_summary_path}"
    return f"{clean_context}\n{summary_note}".strip() if clean_context else summary_note


def start_approved_code_task(
    task_id: str,
    approval_text: str,
    *,
    project_root: str | None = None,
    install_prefix: str | None = None,
    base_branch: str | None = None,
) -> str:
    """Start an approved task by creating its dedicated development branch."""
    try:
        root = _resolve_tool_project_root(project_root, install_prefix)
        state = start_approved_task(
            str(task_id or ""),
            approval_text=str(approval_text or ""),
            project_root=root,
            base_branch=str(base_branch).strip() if base_branch else None,
        )
    except (
        CodeTaskExecutionError,
        CodeTaskVerificationError,
        GitWorkflowError,
        ProjectRootResolutionError,
    ) as exc:
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
    install_prefix: str | None = None,
) -> str:
    """Commit one explicit implementation step for an approved task."""
    try:
        root = _resolve_tool_project_root(project_root, install_prefix)
        state, commit_hash = commit_task_step(
            str(task_id or ""),
            summary=str(summary or ""),
            files=files or [],
            verification_summary=str(verification_summary or ""),
            plan_step_index=plan_step_index,
            project_root=root,
        )
    except (CodeTaskExecutionError, GitWorkflowError, ProjectRootResolutionError) as exc:
        return tool_error(str(exc), success=False)
    return _execution_state_result(state, commit_hash=commit_hash)


def finalize_code_task_branch(
    task_id: str,
    *,
    project_root: str | None = None,
    install_prefix: str | None = None,
) -> str:
    """Merge an approved task branch into the self-evolution integration branch."""
    try:
        root = _resolve_tool_project_root(project_root, install_prefix)
        state = finalize_task_branch(str(task_id or ""), project_root=root)
    except (CodeTaskExecutionError, GitWorkflowError, ProjectRootResolutionError) as exc:
        return tool_error(str(exc), success=False)
    return _execution_state_result(state)


def get_code_task_status(
    task_id: str,
    *,
    project_root: str | None = None,
    install_prefix: str | None = None,
) -> str:
    """Return the audit and execution state for an approved code task."""
    try:
        root = _resolve_tool_project_root(project_root, install_prefix)
        status = describe_task_execution(str(task_id or ""), project_root=root)
        status.update(describe_task_verification(str(task_id or ""), project_root=root))
    except (CodeTaskExecutionError, GitWorkflowError, ProjectRootResolutionError) as exc:
        return tool_error(str(exc), success=False)
    return tool_result(success=True, **status)


def plan_code_task_verification(
    task_id: str,
    *,
    project_root: str | None = None,
    install_prefix: str | None = None,
    include_full_suite: bool = False,
) -> str:
    """Create a verification plan for an approved task branch."""
    try:
        root = _resolve_tool_project_root(project_root, install_prefix)
        state = plan_task_verification(
            str(task_id or ""),
            project_root=root,
            include_full_suite=bool(include_full_suite),
        )
    except (
        CodeTaskExecutionError,
        CodeTaskVerificationError,
        GitWorkflowError,
        ProjectRootResolutionError,
    ) as exc:
        return tool_error(str(exc), success=False)
    return _verification_state_result(state)


def run_code_task_verification(
    task_id: str,
    *,
    commands: list[str] | None = None,
    project_root: str | None = None,
    install_prefix: str | None = None,
) -> str:
    """Run planned or explicit verification commands for an approved task."""
    try:
        root = _resolve_tool_project_root(project_root, install_prefix)
        state = run_task_verification(
            str(task_id or ""),
            commands=commands,
            project_root=root,
        )
    except (
        CodeTaskExecutionError,
        CodeTaskVerificationError,
        GitWorkflowError,
        ProjectRootResolutionError,
    ) as exc:
        return tool_error(str(exc), success=False)
    return _verification_state_result(state)


def record_code_task_safety_review(
    task_id: str,
    questions: list[str] | None,
    *,
    answers: list[str] | None = None,
    conclusion: str = "",
    project_root: str | None = None,
    install_prefix: str | None = None,
) -> str:
    """Record the isolated safety review result for an approved task."""
    try:
        root = _resolve_tool_project_root(project_root, install_prefix)
        state = record_task_safety_review(
            str(task_id or ""),
            questions=questions or [],
            answers=answers,
            conclusion=str(conclusion or ""),
            project_root=root,
        )
    except (
        CodeTaskExecutionError,
        CodeTaskVerificationError,
        GitWorkflowError,
        ProjectRootResolutionError,
    ) as exc:
        return tool_error(str(exc), success=False)
    return _verification_state_result(state)


def self_evolution_thinking(
    action: str,
    *,
    schedule: str | None = None,
    max_candidates: int | None = None,
    project_root: str | None = None,
    install_prefix: str | None = None,
) -> str:
    """Manage read-only self-evolution thinking and candidate reports."""
    normalized = str(action or "").strip().lower()
    try:
        root = _resolve_tool_project_root(project_root, install_prefix)
        if normalized == "status":
            return tool_result(
                success=True,
                action=normalized,
                **describe_self_evolution_thinking(root),
            )
        if normalized == "enable":
            return tool_result(
                success=True,
                action=normalized,
                **enable_self_evolution_thinking(
                    root,
                    schedule=schedule,
                    max_candidates=max_candidates,
                ),
            )
        if normalized == "disable":
            return tool_result(
                success=True,
                action=normalized,
                **disable_self_evolution_thinking(),
            )
        if normalized == "run_once":
            report = run_self_evolution_thinking(root, trigger="manual")
            return tool_result(
                success=True,
                action=normalized,
                status=report.state.status,
                run_id=report.state.run_id,
                candidate_count=report.state.candidate_count,
                report_path=str(report.report_path),
                candidates_path=str(report.candidates_path),
                state_path=str(report.state_path),
            )
    except (SelfEvolutionThinkingError, ProjectRootResolutionError) as exc:
        return tool_error(str(exc), success=False)
    return tool_error(
        "action must be one of status, enable, disable, or run_once.",
        success=False,
    )


def self_update_application(
    action: str,
    task_id: str,
    *,
    project_root: str | None = None,
    install_prefix: str | None = None,
    approval_text: str = "",
    candidate_ref: str | None = None,
    previous_active_ref: str | None = None,
    mode: str = "manual",
    worktree_path: str | None = None,
    candidate_id: str = "",
    release_id: str = "",
    expected_old_release_id: str = "",
    build_summary: str = "",
    health_checks: list[str] | None = None,
    conclusion: str = "",
    reason: str = "",
) -> str:
    """Manage audited self-update application state without restarting runtime."""
    normalized = str(action or "").strip().lower()
    try:
        if normalized.startswith("runtime_"):
            return _runtime_update_application_action(
                normalized,
                str(task_id or ""),
                project_root=project_root,
                install_prefix=install_prefix,
                approval_text=approval_text,
                candidate_ref=candidate_ref,
                candidate_id=candidate_id,
                release_id=release_id,
                expected_old_release_id=expected_old_release_id,
                health_checks=health_checks or [],
                reason=reason,
            )
        root = _resolve_tool_project_root(project_root, install_prefix)
        clean_task_id = str(task_id or "")
        if normalized == "status":
            return tool_result(
                success=True,
                action=normalized,
                **describe_self_update_application(clean_task_id, project_root=root),
            )
        if normalized == "plan":
            state = plan_self_update_application(
                clean_task_id,
                project_root=root,
                candidate_ref=candidate_ref,
                previous_active_ref=previous_active_ref,
                mode=mode,
            )
        elif normalized == "prepare":
            state = prepare_self_update(
                clean_task_id,
                approval_text=approval_text,
                project_root=root,
                worktree_path=worktree_path,
            )
        elif normalized == "record_build":
            state = record_self_update_build(
                clean_task_id,
                project_root=root,
                build_summary=build_summary,
            )
        elif normalized == "record_health":
            state = record_self_update_health_check(
                clean_task_id,
                project_root=root,
                checks=health_checks or [],
                conclusion=conclusion,  # type: ignore[arg-type]
            )
        elif normalized == "activate":
            state = activate_self_update(
                clean_task_id,
                approval_text=approval_text,
                project_root=root,
            )
        elif normalized == "rollback":
            state = rollback_self_update(
                clean_task_id,
                approval_text=approval_text,
                project_root=root,
                reason=reason,
            )
        else:
            return tool_error(
                "action must be one of status, plan, prepare, record_build, "
                "record_health, activate, rollback, runtime_prepare, "
                "runtime_status, runtime_verify, runtime_block, "
                "runtime_promote, runtime_activate, or runtime_rollback.",
                success=False,
            )
    except (
        CodeTaskExecutionError,
        GitWorkflowError,
        ProjectRootResolutionError,
        SelfUpdateApplicationError,
        RuntimeUpdateError,
    ) as exc:
        return tool_error(str(exc), success=False)
    return _self_update_state_result(state, action=normalized)


def _runtime_update_application_action(
    action: str,
    task_id: str,
    *,
    project_root: str | None,
    install_prefix: str | None,
    approval_text: str,
    candidate_ref: str | None,
    candidate_id: str,
    release_id: str,
    expected_old_release_id: str,
    health_checks: list[str],
    reason: str,
) -> str:
    if not install_prefix:
        return tool_error("install_prefix is required for runtime update actions.", success=False)
    if action in {"runtime_prepare", "runtime_verify", "runtime_block", "runtime_promote"} and not str(candidate_id or "").strip():
        return tool_error("candidate_id is required for this runtime update action.", success=False)
    if action in {"runtime_promote", "runtime_activate"} and not str(release_id or "").strip():
        return tool_error("release_id is required for this runtime update action.", success=False)
    if action == "runtime_status":
        return _runtime_status_result(install_prefix, action=action, task_id=task_id)
    with runtime_update_lock(install_prefix, action):
        return _run_locked_runtime_update_action(
            action,
            task_id,
            project_root=project_root,
            install_prefix=install_prefix,
            approval_text=approval_text,
            candidate_ref=candidate_ref,
            candidate_id=candidate_id,
            release_id=release_id,
            expected_old_release_id=expected_old_release_id,
            health_checks=health_checks,
            reason=reason,
        )


def _run_locked_runtime_update_action(
    action: str,
    task_id: str,
    *,
    project_root: str | None,
    install_prefix: str,
    approval_text: str,
    candidate_ref: str | None,
    candidate_id: str,
    release_id: str,
    expected_old_release_id: str,
    health_checks: list[str],
    reason: str,
) -> str:
    if action == "runtime_prepare":
        root = _resolve_tool_project_root(project_root, install_prefix)
        candidate = prepare_candidate_source(
            install_prefix,
            candidate_id,
            source_repo=root,
            git_ref=candidate_ref or "HEAD",
            task_id=task_id,
            old_release_id=expected_old_release_id,
        )
        return tool_result(
            success=True,
            action=action,
            task_id=task_id,
            candidate_id=candidate.candidate_id,
            candidate_commit=candidate.candidate_commit,
            source_repo=candidate.source_repo,
            candidate_source_path=candidate.source_path,
            candidate_metadata_path=str(
                Path(install_prefix).expanduser().resolve()
                / "runtime"
                / "candidates"
                / candidate.candidate_id
                / "metadata.json"
            ),
        )
    if action == "runtime_verify":
        state = mark_candidate_verified(
            install_prefix,
            candidate_id,
            health_checks=health_checks,
        )
        return _runtime_state_result(state, action=action)
    if action == "runtime_block":
        state = mark_candidate_blocked(
            install_prefix,
            candidate_id,
            reason=reason,
            health_checks=health_checks,
        )
        return _runtime_state_result(state, action=action)
    if action == "runtime_promote":
        release = promote_candidate_to_release(install_prefix, candidate_id, release_id)
        return _runtime_release_result(release, action=action, task_id=task_id)
    if action == "runtime_activate":
        require_explicit_approval(approval_text)
        release = read_runtime_release(install_prefix, release_id)
        activated = activate_runtime_release(
            install_prefix,
            release,
            expected_old_release_id=expected_old_release_id or None,
        )
        _record_runtime_terminal_state(
            install_prefix,
            "activated",
            activated,
            task_id=task_id,
            old_release_id=expected_old_release_id,
        )
        return _runtime_release_result(activated, action=action, task_id=task_id)
    if action == "runtime_rollback":
        require_explicit_approval(approval_text)
        release = rollback_active_release(install_prefix)
        _record_runtime_terminal_state(
            install_prefix,
            "rolled_back",
            release,
            task_id=task_id,
            old_release_id=release_id,
        )
        return _runtime_release_result(release, action=action, task_id=task_id)
    return tool_error(
        "runtime action must be one of runtime_prepare, runtime_verify, "
        "runtime_status, runtime_block, runtime_promote, runtime_activate, "
        "or runtime_rollback.",
        success=False,
    )


def _resolve_tool_project_root(
    project_root: str | None,
    install_prefix: str | None,
) -> Path:
    return resolve_self_evolution_project_root(
        explicit_project_root=project_root,
        install_prefix=install_prefix,
    )


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


def _self_update_state_result(state, **extra) -> str:
    task_dir = (
        Path(state.project_root).parent
        / "self-evolution"
        / "tasks"
        / state.task_id
    )
    return tool_result(
        success=True,
        task_id=state.task_id,
        status=state.status,
        mode=state.mode,
        candidate_commit=state.candidate_commit,
        previous_active_commit=state.previous_active_commit,
        approved_by_user=state.approved_by_user,
        dependency_files_changed=list(state.dependency_files_changed),
        restart_required=state.restart_required,
        blocked_reason=state.blocked_reason,
        update_application_path=str(task_dir / "update-application.md"),
        update_state_path=str(task_dir / "update-state.json"),
        **extra,
    )


def _runtime_state_result(state, **extra) -> str:
    return tool_result(
        success=True,
        status=state.status,
        task_id=state.task_id,
        candidate_id=state.candidate_id,
        release_id=state.release_id,
        candidate_commit=state.candidate_commit,
        old_release_id=state.old_release_id,
        steps=list(state.steps),
        health_checks=list(state.health_checks),
        error=state.error,
        **extra,
    )


def _runtime_release_result(release, **extra) -> str:
    return tool_result(
        success=True,
        release_id=release.release_id,
        candidate_commit=release.candidate_commit,
        source_path=release.source_path,
        venv_path=release.venv_path,
        build_path=release.build_path,
        source_repo=release.source_repo,
        activated_at=release.activated_at,
        **extra,
    )


def _runtime_status_result(install_prefix: str, **extra) -> str:
    active = read_active_release(install_prefix)
    previous = read_previous_release(install_prefix)
    update_state = read_runtime_update_state(install_prefix)
    return tool_result(
        success=True,
        active_release=_runtime_release_payload(active),
        previous_release=_runtime_release_payload(previous) if previous else None,
        update_state=_runtime_update_payload(update_state) if update_state else None,
        **extra,
    )


def _record_runtime_terminal_state(
    install_prefix: str,
    status: str,
    release,
    *,
    task_id: str,
    old_release_id: str,
) -> None:
    previous = read_runtime_update_state(install_prefix)
    previous_steps = previous.steps if previous else ()
    write_runtime_update_state(
        install_prefix,
        RuntimeUpdateState(
            status=status,
            task_id=task_id or (previous.task_id if previous else ""),
            candidate_id=previous.candidate_id if previous else "",
            release_id=release.release_id,
            source_repo=release.source_repo,
            candidate_commit=release.candidate_commit,
            old_release_id=old_release_id or (previous.old_release_id if previous else ""),
            steps=_append_runtime_step(previous_steps, status),
            health_checks=previous.health_checks if previous else (),
        ),
    )


def _runtime_release_payload(release) -> dict:
    return {
        "release_id": release.release_id,
        "candidate_commit": release.candidate_commit,
        "source_path": release.source_path,
        "venv_path": release.venv_path,
        "build_path": release.build_path,
        "source_repo": release.source_repo,
        "activated_at": release.activated_at,
    }


def _runtime_update_payload(state) -> dict:
    return {
        "status": state.status,
        "task_id": state.task_id,
        "candidate_id": state.candidate_id,
        "release_id": state.release_id,
        "candidate_commit": state.candidate_commit,
        "old_release_id": state.old_release_id,
        "steps": list(state.steps),
        "health_checks": list(state.health_checks),
        "error": state.error,
        "updated_at": state.updated_at,
    }


def _append_runtime_step(steps: tuple[str, ...], step: str) -> tuple[str, ...]:
    return steps if steps and steps[-1] == step else (*steps, step)


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

SELF_EVOLUTION_THINKING_SCHEMA = {
    "name": "self_evolution_thinking",
    "description": (
        "Manage read-only self-evolution thinking. Use action='status' to inspect "
        "configuration and the dedicated schedule, action='enable' or 'disable' "
        "to manage the scheduled thinking job, and action='run_once' to generate "
        "a local candidate report. This tool only writes self-evolution candidate "
        "reports and config or cron metadata; it must not modify product code, "
        "create branches, commit, merge, or run verification commands."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "One of status, enable, disable, or run_once.",
            },
            "schedule": {
                "type": "string",
                "description": "Optional schedule for enable, such as 'every 7d'.",
            },
            "max_candidates": {
                "type": "integer",
                "description": "Optional maximum candidate count for enable.",
            },
            "project_root": {
                "type": "string",
                "description": "Optional git repository root. Defaults to the current directory.",
            },
        },
        "required": ["action"],
    },
}

SELF_UPDATE_APPLICATION_SCHEMA = {
    "name": "self_update_application",
    "description": (
        "Manage audited self-update application state for an integrated "
        "self-evolution task. This tool records plan, approval, build status, "
        "health checks, activation intent, and rollback intent. It never "
        "installs dependencies, changes active runtime code, restarts a "
        "process, or runs arbitrary commands."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": (
                    "One of status, plan, prepare, record_build, record_health, "
                    "activate, rollback, runtime_prepare, runtime_verify, "
                    "runtime_block, runtime_promote, runtime_activate, "
                    "runtime_rollback, or runtime_status."
                ),
            },
            "task_id": {
                "type": "string",
                "description": "Integrated self-evolution task id.",
            },
            "approval_text": {
                "type": "string",
                "description": "Explicit user approval text for prepare, activate, or rollback.",
            },
            "candidate_ref": {
                "type": "string",
                "description": "Optional git ref for the candidate commit when planning.",
            },
            "previous_active_ref": {
                "type": "string",
                "description": "Optional git ref for the previous active commit when planning.",
            },
            "mode": {
                "type": "string",
                "description": "Application mode for plan: manual, cli, gateway, or cron.",
            },
            "worktree_path": {
                "type": "string",
                "description": "Optional candidate worktree path to record during prepare.",
            },
            "candidate_id": {
                "type": "string",
                "description": (
                    "Runtime candidate id for runtime_prepare, runtime_verify, "
                    "runtime_block, or runtime_promote."
                ),
            },
            "release_id": {
                "type": "string",
                "description": "Runtime release id for runtime_promote or runtime_activate.",
            },
            "expected_old_release_id": {
                "type": "string",
                "description": (
                    "Optional active release id guard for runtime_prepare or "
                    "runtime_activate."
                ),
            },
            "build_summary": {
                "type": "string",
                "description": "Build result or reason no build is required; commands are not run.",
            },
            "health_checks": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Health-check evidence to record.",
            },
            "conclusion": {
                "type": "string",
                "description": "Health conclusion: passed, failed, or inconclusive.",
            },
            "reason": {
                "type": "string",
                "description": "Optional rollback reason.",
            },
            "project_root": {
                "type": "string",
                "description": "Optional git repository root. Defaults to the current directory.",
            },
        },
        "required": ["action", "task_id"],
    },
}


def _add_install_prefix_to_schema(schema: dict) -> None:
    properties = schema["parameters"]["properties"]
    if "project_root" in properties:
        properties["project_root"]["description"] = (
            "Optional development source repository root. When omitted, the "
            "tool resolves a safe self-evolution project root from cwd, "
            "install_prefix state, or self_evolution.source_repo."
        )
    properties["install_prefix"] = {
        "type": "string",
        "description": (
            "Optional Zermes install prefix. When project_root is omitted, "
            "runtime/install-state.json or runtime/active.json source_repo.path "
            "can identify the development source repository. Runtime release "
            "or candidate source copies are rejected."
        ),
    }


for _schema in (
    COMPLETE_CODE_TASK_SCHEMA,
    START_APPROVED_CODE_TASK_SCHEMA,
    COMMIT_CODE_TASK_STEP_SCHEMA,
    FINALIZE_CODE_TASK_BRANCH_SCHEMA,
    GET_CODE_TASK_STATUS_SCHEMA,
    PLAN_CODE_TASK_VERIFICATION_SCHEMA,
    RUN_CODE_TASK_VERIFICATION_SCHEMA,
    RECORD_CODE_TASK_SAFETY_REVIEW_SCHEMA,
    SELF_EVOLUTION_THINKING_SCHEMA,
    SELF_UPDATE_APPLICATION_SCHEMA,
):
    _add_install_prefix_to_schema(_schema)


registry.register(
    name="complete_code_task",
    toolset="code_modification",
    schema=COMPLETE_CODE_TASK_SCHEMA,
    handler=lambda args, **kw: complete_code_task(
        requirement=args.get("requirement", ""),
        context=args.get("context", ""),
        affected_areas=args.get("affected_areas"),
        project_root=args.get("project_root"),
        install_prefix=args.get("install_prefix"),
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
        install_prefix=args.get("install_prefix"),
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
        install_prefix=args.get("install_prefix"),
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
        install_prefix=args.get("install_prefix"),
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
        install_prefix=args.get("install_prefix"),
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
        install_prefix=args.get("install_prefix"),
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
        install_prefix=args.get("install_prefix"),
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
        install_prefix=args.get("install_prefix"),
    ),
    check_fn=check_code_modification_requirements,
    emoji="🛡️",
)

registry.register(
    name="self_evolution_thinking",
    toolset="code_modification",
    schema=SELF_EVOLUTION_THINKING_SCHEMA,
    handler=lambda args, **kw: self_evolution_thinking(
        action=args.get("action", ""),
        schedule=args.get("schedule"),
        max_candidates=args.get("max_candidates"),
        project_root=args.get("project_root"),
        install_prefix=args.get("install_prefix"),
    ),
    check_fn=check_code_modification_requirements,
    emoji="T",
)

registry.register(
    name="self_update_application",
    toolset="code_modification",
    schema=SELF_UPDATE_APPLICATION_SCHEMA,
    handler=lambda args, **kw: self_update_application(
        action=args.get("action", ""),
        task_id=args.get("task_id", ""),
        project_root=args.get("project_root"),
        install_prefix=args.get("install_prefix"),
        approval_text=args.get("approval_text", ""),
        candidate_ref=args.get("candidate_ref"),
        previous_active_ref=args.get("previous_active_ref"),
        mode=args.get("mode", "manual"),
        worktree_path=args.get("worktree_path"),
        candidate_id=args.get("candidate_id", ""),
        release_id=args.get("release_id", ""),
        expected_old_release_id=args.get("expected_old_release_id", ""),
        build_summary=args.get("build_summary", ""),
        health_checks=args.get("health_checks"),
        conclusion=args.get("conclusion", ""),
        reason=args.get("reason", ""),
    ),
    check_fn=check_code_modification_requirements,
    emoji="U",
)

import pytest

from worker_agents.runtime_boundary import (
    AgentRuntimeBoundaryError,
    AgentRuntimeLifecycle,
    AgentRuntimePersona,
    AgentRuntimeRole,
    AgentRuntimeSessionConfig,
    AgentRuntimeSessionScope,
    RuntimeBudgetSnapshot,
    RuntimeContextBundle,
    RuntimePermissionSnapshot,
    RuntimeProfileSummary,
)


def _worker_persona():
    return AgentRuntimePersona(
        role=AgentRuntimeRole.MANAGED_WORKER,
        lifecycle=AgentRuntimeLifecycle.DURABLE_WORKER,
        display_name="Frontend Engineer",
        responsibility_summary="Build user interfaces.",
        worker_id="frontend",
    )


def _minimal_context():
    return RuntimeContextBundle(
        user_instruction="Implement the focused change.",
        task_summary="Patch the runtime boundary.",
    )


def _minimal_budget():
    return RuntimeBudgetSnapshot(
        model_policy_ref="worker-default",
        max_task_tokens=1000,
        max_allowed_task_tokens=1000,
    )


def test_managed_worker_session_accepts_matching_profile_summary():
    config = AgentRuntimeSessionConfig(
        scope=AgentRuntimeSessionScope.MANAGED_WORKER_TASK,
        persona=_worker_persona(),
        profile_summary=RuntimeProfileSummary(
            worker_id="frontend",
            identity_ref="workers/frontend/identity.md",
            allowed_skill_refs=("skills/frontend.md",),
            memory_summary_refs=("memory/frontend-summary.md",),
        ),
        permissions=RuntimePermissionSnapshot(
            allowed_tool_names=("read_file",),
            workspace_read_roots=("workspace/project",),
        ),
        budget=_minimal_budget(),
        context=_minimal_context(),
    )

    assert config.scope == AgentRuntimeSessionScope.MANAGED_WORKER_TASK
    assert config.profile_summary.worker_id == "frontend"


def test_session_rejects_scope_and_persona_mismatch():
    with pytest.raises(AgentRuntimeBoundaryError, match="requires main_agent"):
        AgentRuntimeSessionConfig(
            scope=AgentRuntimeSessionScope.INTERACTIVE_MAIN,
            persona=_worker_persona(),
            profile_summary=RuntimeProfileSummary(worker_id="frontend"),
            permissions=RuntimePermissionSnapshot(),
            budget=_minimal_budget(),
            context=_minimal_context(),
        )


def test_permission_snapshot_rejects_wildcard_access():
    with pytest.raises(AgentRuntimeBoundaryError, match="grant all access"):
        RuntimePermissionSnapshot(allowed_tool_names=("*",))


def test_budget_snapshot_rejects_budget_increase():
    with pytest.raises(AgentRuntimeBoundaryError, match="max_task_tokens"):
        RuntimeBudgetSnapshot(
            model_name="fast-model",
            max_task_tokens=2000,
            max_allowed_task_tokens=1000,
        )


def test_context_bundle_rejects_full_transcript_and_private_memory_text():
    with pytest.raises(AgentRuntimeBoundaryError, match="full transcripts"):
        RuntimeContextBundle(
            user_instruction="Use everything.",
            task_summary="Unsafe context.",
            includes_full_transcript=True,
        )

    with pytest.raises(AgentRuntimeBoundaryError, match="private memory"):
        RuntimeContextBundle(
            user_instruction="Use memory.",
            task_summary="Unsafe context.",
            includes_private_memory_text=True,
        )


def test_temporary_child_session_requires_cleanup_policy_and_no_durable_profile():
    persona = AgentRuntimePersona(
        role=AgentRuntimeRole.TEMPORARY_CHILD,
        lifecycle=AgentRuntimeLifecycle.TASK_SCOPED,
        display_name="Temporary Explorer",
        responsibility_summary="Explore one implementation option.",
        parent_worker_id="frontend",
        parent_task_id="task_123",
    )

    with pytest.raises(AgentRuntimeBoundaryError, match="cleanup_policy"):
        AgentRuntimeSessionConfig(
            scope=AgentRuntimeSessionScope.TEMPORARY_CHILD_TASK,
            persona=persona,
            profile_summary=RuntimeProfileSummary(),
            permissions=RuntimePermissionSnapshot(),
            budget=_minimal_budget(),
            context=_minimal_context(),
        )

    with pytest.raises(AgentRuntimeBoundaryError, match="durable profile"):
        AgentRuntimeSessionConfig(
            scope=AgentRuntimeSessionScope.TEMPORARY_CHILD_TASK,
            persona=persona,
            profile_summary=RuntimeProfileSummary(worker_id="frontend"),
            permissions=RuntimePermissionSnapshot(),
            budget=_minimal_budget(),
            context=_minimal_context(),
            cleanup_policy="delete_runtime_state",
        )

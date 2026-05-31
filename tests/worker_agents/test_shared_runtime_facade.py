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
from worker_agents.runtime_facade import SharedAgentRuntimeFacade


def _budget():
    return RuntimeBudgetSnapshot(
        model_policy_ref="worker-default",
        max_task_tokens=500,
        max_allowed_task_tokens=500,
    )


def _context():
    return RuntimeContextBundle(
        user_instruction="Handle the task.",
        task_summary="Prepare a managed runtime invocation.",
    )


def test_facade_prepares_managed_worker_invocation():
    facade = SharedAgentRuntimeFacade()
    config = AgentRuntimeSessionConfig(
        scope=AgentRuntimeSessionScope.MANAGED_WORKER_TASK,
        persona=AgentRuntimePersona(
            role=AgentRuntimeRole.MANAGED_WORKER,
            lifecycle=AgentRuntimeLifecycle.DURABLE_WORKER,
            display_name="Frontend Engineer",
            responsibility_summary="Build user interfaces.",
            worker_id="frontend",
        ),
        profile_summary=RuntimeProfileSummary(worker_id="frontend"),
        permissions=RuntimePermissionSnapshot(
            allowed_tool_names=("read_file", "apply_patch"),
            allowed_toolset_names=("filesystem",),
            workspace_read_roots=("workspace/project",),
            workspace_write_roots=("workspace/project/src",),
        ),
        budget=_budget(),
        context=_context(),
    )

    invocation = facade.prepare_invocation(config)

    assert invocation.role == AgentRuntimeRole.MANAGED_WORKER
    assert invocation.worker_id == "frontend"
    assert invocation.allowed_tool_names == ("read_file", "apply_patch")
    assert invocation.max_task_tokens == 500
    assert invocation.user_instruction == "Handle the task."


def test_facade_prepares_temporary_child_without_durable_identity():
    facade = SharedAgentRuntimeFacade()
    config = AgentRuntimeSessionConfig(
        scope=AgentRuntimeSessionScope.TEMPORARY_CHILD_TASK,
        persona=AgentRuntimePersona(
            role=AgentRuntimeRole.TEMPORARY_CHILD,
            lifecycle=AgentRuntimeLifecycle.TASK_SCOPED,
            display_name="Temporary Explorer",
            responsibility_summary="Explore a small implementation question.",
            parent_worker_id="frontend",
            parent_task_id="task_123",
        ),
        profile_summary=RuntimeProfileSummary(),
        permissions=RuntimePermissionSnapshot(allowed_tool_names=("read_file",)),
        budget=_budget(),
        context=_context(),
        cleanup_policy="delete_runtime_state",
    )

    invocation = facade.prepare_invocation(config)

    assert invocation.role == AgentRuntimeRole.TEMPORARY_CHILD
    assert invocation.worker_id is None
    assert invocation.parent_worker_id == "frontend"
    assert invocation.cleanup_policy == "delete_runtime_state"


def test_facade_uses_same_invocation_shape_for_main_agent():
    facade = SharedAgentRuntimeFacade()
    config = AgentRuntimeSessionConfig(
        scope=AgentRuntimeSessionScope.INTERACTIVE_MAIN,
        persona=AgentRuntimePersona(
            role=AgentRuntimeRole.MAIN_AGENT,
            lifecycle=AgentRuntimeLifecycle.GOVERNED_MAIN,
            display_name="Zermes",
            responsibility_summary="Coordinate worker activity.",
            enables_governance_actions=True,
        ),
        profile_summary=RuntimeProfileSummary(identity_ref="main-agent"),
        permissions=RuntimePermissionSnapshot(
            allowed_toolset_names=("core",),
            outbound_communication_policy="user_entrypoint",
        ),
        budget=_budget(),
        context=_context(),
    )

    invocation = facade.run(config)

    assert invocation.role == AgentRuntimeRole.MAIN_AGENT
    assert invocation.scope == AgentRuntimeSessionScope.INTERACTIVE_MAIN
    assert invocation.worker_id is None


def test_facade_rejects_non_session_config():
    with pytest.raises(AgentRuntimeBoundaryError, match="AgentRuntimeSessionConfig"):
        SharedAgentRuntimeFacade().prepare_invocation(object())

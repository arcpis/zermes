import pytest

from worker_agents.runtime_boundary import (
    AgentRuntimeBoundaryError,
    AgentRuntimeLifecycle,
    AgentRuntimePersona,
    AgentRuntimeRole,
)


def test_main_agent_persona_accepts_governance_overlay():
    persona = AgentRuntimePersona(
        role=AgentRuntimeRole.MAIN_AGENT,
        lifecycle=AgentRuntimeLifecycle.GOVERNED_MAIN,
        display_name="Zermes",
        responsibility_summary="Coordinate user-visible worker activity.",
        enables_governance_actions=True,
    )

    assert persona.role == AgentRuntimeRole.MAIN_AGENT
    assert persona.enables_governance_actions is True


def test_managed_worker_persona_requires_worker_id():
    with pytest.raises(AgentRuntimeBoundaryError, match="worker_id"):
        AgentRuntimePersona(
            role=AgentRuntimeRole.MANAGED_WORKER,
            lifecycle=AgentRuntimeLifecycle.DURABLE_WORKER,
            display_name="Frontend Engineer",
            responsibility_summary="Build user interfaces.",
        )


def test_managed_worker_rejects_main_agent_governance_actions():
    with pytest.raises(AgentRuntimeBoundaryError, match="governance"):
        AgentRuntimePersona(
            role=AgentRuntimeRole.MANAGED_WORKER,
            lifecycle=AgentRuntimeLifecycle.DURABLE_WORKER,
            display_name="Backend Engineer",
            responsibility_summary="Build APIs.",
            worker_id="backend",
            enables_governance_actions=True,
        )


def test_temporary_child_requires_parent_identity():
    with pytest.raises(AgentRuntimeBoundaryError, match="parent_worker_id"):
        AgentRuntimePersona(
            role=AgentRuntimeRole.TEMPORARY_CHILD,
            lifecycle=AgentRuntimeLifecycle.TASK_SCOPED,
            display_name="Short Research Task",
            responsibility_summary="Explore one focused question.",
            parent_task_id="task_123",
        )


def test_temporary_child_rejects_durable_worker_identity_and_memory_access():
    with pytest.raises(AgentRuntimeBoundaryError, match="durable worker_id"):
        AgentRuntimePersona(
            role=AgentRuntimeRole.TEMPORARY_CHILD,
            lifecycle=AgentRuntimeLifecycle.TASK_SCOPED,
            display_name="Short Implementation Task",
            responsibility_summary="Patch one narrow module.",
            worker_id="temporary_impl",
            parent_worker_id="frontend",
            parent_task_id="task_123",
        )

    with pytest.raises(AgentRuntimeBoundaryError, match="private memory"):
        AgentRuntimePersona(
            role=AgentRuntimeRole.TEMPORARY_CHILD,
            lifecycle=AgentRuntimeLifecycle.TASK_SCOPED,
            display_name="Short Implementation Task",
            responsibility_summary="Patch one narrow module.",
            parent_worker_id="frontend",
            parent_task_id="task_123",
            can_write_private_memory=True,
        )


def test_unknown_role_is_rejected():
    with pytest.raises(AgentRuntimeBoundaryError, match="Unsupported"):
        AgentRuntimePersona(
            role="external_executor",
            lifecycle=AgentRuntimeLifecycle.TASK_SCOPED,
            display_name="External",
            responsibility_summary="Unknown runtime.",
        )

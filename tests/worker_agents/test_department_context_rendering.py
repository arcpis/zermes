import pytest

from worker_agents.department_context_bundle import (
    DepartmentAssetContextBundle,
    DepartmentContextSelectionReason,
    DepartmentMemoryContextView,
    DepartmentToolPolicyContextSnapshot,
)
from worker_agents.department_context_rendering import (
    DepartmentContextRenderingError,
    render_department_context_bundle,
)
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


def _bundle() -> DepartmentAssetContextBundle:
    memory = DepartmentMemoryContextView(
        department_id="engineering",
        memory_id="release-memory",
        kind="delivery_standard",
        summary="Run focused release tests before broad checks.",
        source_refs=("departments/engineering/memory/release-memory.json",),
        sensitivity="low",
    )
    policy = DepartmentToolPolicyContextSnapshot(
        department_id="engineering",
        allowed_tool_summaries=("read-only pytest runs",),
        denied_tool_summaries=("production deploy commands",),
        approval_required_tool_summaries=("write shell commands pending approval",),
        denial_reasons=("deploy is outside worker task scope",),
        approval_status_refs=("approvals/write-shell/pending.json",),
        policy_refs=("departments/engineering/tool-policy.json",),
    )
    return DepartmentAssetContextBundle(
        department_id="engineering",
        worker_id="release_worker",
        task_ref="tasks/release-check",
        selected_memories=(memory,),
        selected_tool_policy_snapshot=policy,
        selection_reasons=(
            DepartmentContextSelectionReason(
                asset_kind="memory",
                asset_id="release-memory",
                reasons=("department_match", "task_type_match"),
                source_refs=memory.source_refs,
            ),
        ),
        audit_summary="trace=traces/release-check/context.json",
        created_at="2026-05-23T00:00:00Z",
    )


def _session_config(**overrides):
    values = {
        "scope": AgentRuntimeSessionScope.MANAGED_WORKER_TASK,
        "persona": AgentRuntimePersona(
            role=AgentRuntimeRole.MANAGED_WORKER,
            lifecycle=AgentRuntimeLifecycle.DURABLE_WORKER,
            display_name="Release Worker",
            responsibility_summary="Run release checks.",
            worker_id="release_worker",
        ),
        "profile_summary": RuntimeProfileSummary(worker_id="release_worker"),
        "permissions": RuntimePermissionSnapshot(),
        "budget": RuntimeBudgetSnapshot(model_policy_ref="worker-default"),
        "context": RuntimeContextBundle(
            user_instruction="Run release checks.",
            task_summary="Release check task.",
        ),
    }
    values.update(overrides)
    return AgentRuntimeSessionConfig(**values)


def test_no_department_context_preserves_session_config_shape():
    config = _session_config()

    assert config.department_context is None
    assert config.context.user_instruction == "Run release checks."


def test_empty_bundle_renders_no_op_context():
    empty = DepartmentAssetContextBundle(
        department_id="engineering",
        worker_id="release_worker",
        task_ref="tasks/release-check",
        created_at="2026-05-23T00:00:00Z",
    )

    rendered = render_department_context_bundle(empty)

    assert rendered.no_op is True
    assert rendered.context_block == ""
    assert rendered.audit_trace_ref == "tasks/release-check"


def test_non_empty_rendering_contains_sources_and_selection_reasons():
    rendered = render_department_context_bundle(_bundle())

    assert "Department memory notes" in rendered.context_block
    assert "Selection reasons" in rendered.context_block
    assert "departments/engineering/memory/release-memory.json" in rendered.source_refs
    assert rendered.sensitivity_summary.startswith("highest=")


def test_rendering_rejects_raw_dict_or_invalid_session_field():
    with pytest.raises(DepartmentContextRenderingError):
        render_department_context_bundle({"secret": "blocked"})

    with pytest.raises(AgentRuntimeBoundaryError, match="department_context"):
        _session_config(department_context="unsafe string")


def test_external_runtime_summary_contains_no_raw_sensitive_terms():
    rendered = render_department_context_bundle(_bundle())

    for blocked in (
        "raw instruction",
        "secret",
        "credential",
        "token",
        "env",
        "full transcript",
        "raw_stdout",
        "raw_stderr",
    ):
        assert blocked not in rendered.context_block.lower()

    config = _session_config(department_context=rendered)
    assert config.department_context is rendered

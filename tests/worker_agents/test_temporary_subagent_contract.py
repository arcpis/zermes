import pytest

from worker_agents.runtime_contract import RuntimeResult, RuntimeState, RuntimeType
from worker_agents.temporary_subagents import (
    TemporarySubagentError,
    TemporarySubagentProfileOverlay,
    TemporarySubagentRequest,
    TemporarySubagentResultEnvelope,
    TemporarySubagentResultReturnPolicy,
    TemporarySubagentTerminalState,
    temporary_subagent_request_to_dict,
    temporary_subagent_request_to_runtime_request,
)


def _overlay():
    return TemporarySubagentProfileOverlay(
        role_name="Focused Explorer",
        task_instructions="Inspect only the supplied summaries.",
        output_contract="Return concise findings.",
        tool_guidance=("Use read-only tools.",),
        context_limits={"max_refs": 3},
    )


def _request(**overrides):
    data = {
        "delegation_id": "delegation-1",
        "parent_worker_id": "researcher",
        "task_id": "task-1",
        "purpose": "Explore one narrow question.",
        "requested_runtime_type": RuntimeType.TEMPORARY_SUBAGENT,
        "profile_overlay": _overlay(),
        "result_return_policy": TemporarySubagentResultReturnPolicy.PARENT_WORKER_ONLY,
        "parent_request_id": "parent-runtime-request",
        "requested_model": "fast-model",
        "requested_tools": ("read_file",),
        "workspace_read_roots": ("workspace/project",),
        "context_refs": ("threads/task-1/summary.md",),
        "max_task_tokens": 250,
        "timeout_seconds": 30,
    }
    data.update(overrides)
    return TemporarySubagentRequest(**data)


def test_temporary_subagent_request_is_audit_safe_and_serializable():
    request = _request()

    data = temporary_subagent_request_to_dict(request)

    assert data["parent_worker_id"] == "researcher"
    assert data["requested_runtime_type"] == "temporary_subagent"
    assert data["profile_overlay"]["role_name"] == "Focused Explorer"
    assert data["result_return_policy"] == "parent_worker_only"


def test_temporary_subagent_request_rejects_missing_parent_or_purpose():
    with pytest.raises(TemporarySubagentError, match="purpose"):
        _request(purpose="")

    with pytest.raises(ValueError, match="worker_id"):
        _request(parent_worker_id="../researcher")


def test_profile_overlay_rejects_durable_identity_and_memory_fields():
    with pytest.raises(TemporarySubagentError, match="worker_id"):
        TemporarySubagentProfileOverlay(
            role_name="Bad Overlay",
            task_instructions="Do too much.",
            output_contract="Return output.",
            context_limits={"worker_id": "durable-worker"},
        )

    with pytest.raises(TemporarySubagentError, match="private_memory"):
        TemporarySubagentProfileOverlay(
            role_name="Bad Overlay",
            task_instructions="Read memory.",
            output_contract="Return output.",
            context_limits={"nested": {"private_memory": "raw text"}},
        )


def test_request_requires_a_budget_or_timeout_limit():
    with pytest.raises(TemporarySubagentError, match="requires a token"):
        _request(
            max_task_tokens=None,
            max_task_cost_usd=None,
            timeout_seconds=None,
        )


def test_request_converts_to_runtime_request_with_parent_reference():
    runtime_request = temporary_subagent_request_to_runtime_request(
        _request(),
        request_id="child-runtime-request",
        requested_by="researcher",
        created_at="2026-05-21T00:00:00Z",
    )

    assert runtime_request.request_id == "child-runtime-request"
    assert runtime_request.worker_id == "researcher"
    assert runtime_request.runtime_type == RuntimeType.TEMPORARY_SUBAGENT
    assert runtime_request.parent_request_id == "parent-runtime-request"
    assert runtime_request.context.artifact_manifest_refs == ()
    assert runtime_request.budget.max_output_tokens == 250


def test_result_envelope_matches_runtime_result_terminal_state():
    runtime_result = RuntimeResult(
        request_id="child-runtime-request",
        task_id="task-1",
        worker_id="researcher",
        runtime_type=RuntimeType.TEMPORARY_SUBAGENT,
        final_state=RuntimeState.SUCCEEDED,
        started_at="2026-05-21T00:00:00Z",
        completed_at="2026-05-21T00:00:01Z",
        internal_summary="Child result returned to parent.",
    )

    envelope = TemporarySubagentResultEnvelope(
        delegation_id="delegation-1",
        parent_worker_id="researcher",
        task_id="task-1",
        terminal_state=TemporarySubagentTerminalState.SUCCEEDED,
        runtime_result=runtime_result,
    )

    assert envelope.cleanup_status == "pending"


def test_result_envelope_rejects_mismatched_terminal_state():
    runtime_result = RuntimeResult(
        request_id="child-runtime-request",
        task_id="task-1",
        worker_id="researcher",
        runtime_type=RuntimeType.TEMPORARY_SUBAGENT,
        final_state=RuntimeState.SUCCEEDED,
        started_at="2026-05-21T00:00:00Z",
        completed_at="2026-05-21T00:00:01Z",
        internal_summary="Child result returned to parent.",
    )

    with pytest.raises(TemporarySubagentError, match="must match"):
        TemporarySubagentResultEnvelope(
            delegation_id="delegation-1",
            parent_worker_id="researcher",
            task_id="task-1",
            terminal_state=TemporarySubagentTerminalState.FAILED,
            runtime_result=runtime_result,
        )

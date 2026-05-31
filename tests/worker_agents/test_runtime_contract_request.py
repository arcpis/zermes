import pytest

from worker_agents.runtime_contract import (
    RUNTIME_CONTRACT_VERSION,
    RuntimeContractError,
    RuntimeExecutionBudget,
    RuntimeRequest,
    RuntimeRequestContext,
    RuntimeType,
    dump_runtime_request_json,
    load_runtime_request_json,
    runtime_request_from_dict,
)


def _budget():
    return RuntimeExecutionBudget(
        budget_source="worker-profile:frontend",
        model="fast-model",
        max_input_tokens=4000,
        max_output_tokens=1000,
        max_cost_usd=0.5,
        timeout_seconds=120,
        max_output_bytes=10000,
        max_transcript_bytes=50000,
    )


def _context():
    return RuntimeRequestContext(
        input_message="Implement the focused runtime contract change.",
        source_thread_id="thread-123",
        source_message_refs=("worker_agents/threads/thread-123/messages/msg-1",),
        source_sender_ref="user:user-123",
        target_context_summary="Reply as frontend in thread-123.",
        thread_summary_refs=("threads/task-123/summary.md",),
        organization_summary_refs=("org/frontend/summary.md",),
        artifact_manifest_refs=("manifests/design-brief.json",),
        allowed_tool_descriptions=("read_file: inspect approved files",),
        workspace_policy_ref="policies/frontend/workspace.json",
        redaction_policy_ref="policies/default-redaction.json",
        relevant_excerpts=("Only the public task summary is included.",),
    )


def test_runtime_request_json_round_trip():
    request = RuntimeRequest(
        request_id="runtime_req_123",
        task_id="task_123",
        worker_id="frontend",
        runtime_type=RuntimeType.INTERNAL_WORKER,
        requested_by="zermes_main_agent",
        created_at="2026-05-21T00:00:00Z",
        context=_context(),
        budget=_budget(),
        session_ref="sessions/runtime_req_123.json",
    )

    loaded = load_runtime_request_json(dump_runtime_request_json(request))

    assert loaded == request
    assert loaded.contract_version == RUNTIME_CONTRACT_VERSION
    assert loaded.runtime_type == RuntimeType.INTERNAL_WORKER
    assert loaded.context.source_thread_id == "thread-123"
    assert loaded.context.source_message_refs == (
        "worker_agents/threads/thread-123/messages/msg-1",
    )


def test_runtime_request_rejects_missing_required_fields():
    data = {
        "contract_version": RUNTIME_CONTRACT_VERSION,
        "request_id": "runtime_req_123",
        "worker_id": "frontend",
        "runtime_type": "internal_worker",
        "requested_by": "zermes_main_agent",
        "created_at": "2026-05-21T00:00:00Z",
        "context": {
            "input_message": "Run the task.",
        },
        "budget": {
            "budget_source": "worker-profile:frontend",
            "max_output_tokens": 1000,
        },
    }

    with pytest.raises(RuntimeContractError, match="task_id"):
        runtime_request_from_dict(data)


def test_runtime_request_rejects_unknown_runtime_type():
    with pytest.raises(RuntimeContractError, match="Unknown runtime_type"):
        RuntimeRequest(
            request_id="runtime_req_123",
            task_id="task_123",
            worker_id="frontend",
            runtime_type="unmanaged_shell",
            requested_by="zermes_main_agent",
            created_at="2026-05-21T00:00:00Z",
            context=_context(),
            budget=_budget(),
        )


def test_runtime_context_rejects_sensitive_fields():
    with pytest.raises(RuntimeContractError, match="raw_transcript"):
        runtime_request_from_dict(
            {
                "contract_version": RUNTIME_CONTRACT_VERSION,
                "request_id": "runtime_req_123",
                "task_id": "task_123",
                "worker_id": "frontend",
                "runtime_type": "internal_worker",
                "requested_by": "zermes_main_agent",
                "created_at": "2026-05-21T00:00:00Z",
                "context": {
                    "input_message": "Run the task.",
                    "raw_transcript": "complete private conversation",
                },
                "budget": {
                    "budget_source": "worker-profile:frontend",
                    "max_output_tokens": 1000,
                },
            }
        )


def test_runtime_budget_requires_a_limit():
    with pytest.raises(RuntimeContractError, match="at least one limit"):
        RuntimeExecutionBudget(budget_source="worker-profile:frontend")


def test_temporary_runtime_request_requires_parent_request():
    with pytest.raises(RuntimeContractError, match="parent_request_id"):
        RuntimeRequest(
            request_id="runtime_req_child",
            task_id="task_123",
            worker_id="frontend",
            runtime_type=RuntimeType.TEMPORARY_SUBAGENT,
            requested_by="frontend",
            created_at="2026-05-21T00:00:00Z",
            context=_context(),
            budget=_budget(),
        )

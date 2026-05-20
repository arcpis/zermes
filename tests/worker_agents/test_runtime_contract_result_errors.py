import pytest

from worker_agents.runtime_contract import (
    RUNTIME_CONTRACT_VERSION,
    RuntimeArtifactRef,
    RuntimeContractError,
    RuntimeErrorCode,
    RuntimeErrorInfo,
    RuntimeMemoryProposal,
    RuntimeResult,
    RuntimeSafetyRequest,
    RuntimeState,
    RuntimeType,
    dump_runtime_result_json,
    load_runtime_result_json,
    runtime_result_from_dict,
)


def _artifact():
    return RuntimeArtifactRef(
        manifest_ref="manifests/task_123/result.json",
        artifact_type="patch_summary",
        summary="Generated a patch summary manifest.",
        retention_policy_ref="retention/default.json",
    )


def _memory_proposal():
    return RuntimeMemoryProposal(
        proposal_id="memory_prop_123",
        target_scope="worker:frontend",
        redacted_summary="Prefer focused runtime contract tests for adapter work.",
        source_task_id="task_123",
        review_reason="Useful implementation habit from this task.",
    )


def _safety_request():
    return RuntimeSafetyRequest(
        request_id="safety_req_123",
        request_type="high_risk_tool",
        risk_level="high",
        user_visible_summary="The worker needs approval before writing outside scope.",
        required_approver="zermes_main_agent",
        blocking=True,
    )


def _error(code=RuntimeErrorCode.OUTPUT_PARSE_ERROR, retryable=False):
    return RuntimeErrorInfo(
        code=code,
        message="Adapter output could not be parsed.",
        safe_summary="The adapter returned malformed structured output.",
        retryable=retryable,
        source="external_adapter",
        created_at="2026-05-21T00:10:00Z",
        raw_error_ref="data/worker_agents/runtime/task_123/error.log",
    )


def test_runtime_result_json_round_trip_for_success():
    result = RuntimeResult(
        request_id="runtime_req_123",
        task_id="task_123",
        worker_id="frontend",
        runtime_type=RuntimeType.INTERNAL_WORKER,
        final_state=RuntimeState.SUCCEEDED,
        started_at="2026-05-21T00:00:00Z",
        completed_at="2026-05-21T00:10:00Z",
        public_message="The runtime contract implementation is complete.",
        internal_summary="Added request, event, result and error models.",
        artifact_refs=(_artifact(),),
        memory_proposals=(_memory_proposal(),),
        department_asset_proposals=(_memory_proposal(),),
        safety_requests=(_safety_request(),),
        audit_summary="No long-term assets were written by the runtime result.",
    )

    loaded = load_runtime_result_json(dump_runtime_result_json(result))

    assert loaded == result
    assert loaded.contract_version == RUNTIME_CONTRACT_VERSION


def test_failed_runtime_result_requires_error():
    with pytest.raises(RuntimeContractError, match="failed result requires error"):
        RuntimeResult(
            request_id="runtime_req_123",
            task_id="task_123",
            worker_id="frontend",
            runtime_type=RuntimeType.INTERNAL_WORKER,
            final_state=RuntimeState.FAILED,
            started_at="2026-05-21T00:00:00Z",
            completed_at="2026-05-21T00:10:00Z",
            internal_summary="The adapter failed.",
        )


def test_partial_success_can_include_artifact_and_error():
    result = RuntimeResult(
        request_id="runtime_req_123",
        task_id="task_123",
        worker_id="frontend",
        runtime_type=RuntimeType.EXTERNAL_ADAPTER,
        final_state=RuntimeState.FAILED,
        started_at="2026-05-21T00:00:00Z",
        completed_at="2026-05-21T00:10:00Z",
        artifact_refs=(_artifact(),),
        audit_summary="One artifact was produced before output parsing failed.",
        error=_error(),
        partial_success=True,
    )

    assert result.partial_success is True
    assert result.error.code == RuntimeErrorCode.OUTPUT_PARSE_ERROR


def test_runtime_error_retryable_flag_must_match_non_retryable_codes():
    with pytest.raises(RuntimeContractError, match="must not be retryable"):
        _error(code=RuntimeErrorCode.PERMISSION_DENIED, retryable=True)

    retryable = _error(code=RuntimeErrorCode.RETRYABLE, retryable=True)
    assert retryable.retryable is True


def test_runtime_result_rejects_non_terminal_final_state():
    with pytest.raises(RuntimeContractError, match="terminal final_state"):
        RuntimeResult(
            request_id="runtime_req_123",
            task_id="task_123",
            worker_id="frontend",
            runtime_type=RuntimeType.INTERNAL_WORKER,
            final_state=RuntimeState.RUNNING,
            started_at="2026-05-21T00:00:00Z",
            completed_at="2026-05-21T00:10:00Z",
            internal_summary="Still running.",
        )


def test_runtime_result_rejects_direct_memory_write_fields():
    with pytest.raises(RuntimeContractError, match="private_memory"):
        runtime_result_from_dict(
            {
                "contract_version": RUNTIME_CONTRACT_VERSION,
                "request_id": "runtime_req_123",
                "task_id": "task_123",
                "worker_id": "frontend",
                "runtime_type": "internal_worker",
                "final_state": "succeeded",
                "started_at": "2026-05-21T00:00:00Z",
                "completed_at": "2026-05-21T00:10:00Z",
                "internal_summary": "Unsafe result.",
                "memory_proposals": [
                    {
                        "proposal_id": "memory_prop_123",
                        "target_scope": "worker:frontend",
                        "redacted_summary": "safe summary",
                        "source_task_id": "task_123",
                        "review_reason": "review it",
                        "private_memory": "raw private memory text",
                    }
                ],
            }
        )


def test_runtime_result_rejects_raw_stderr_inline():
    with pytest.raises(RuntimeContractError, match="raw_stderr"):
        runtime_result_from_dict(
            {
                "contract_version": RUNTIME_CONTRACT_VERSION,
                "request_id": "runtime_req_123",
                "task_id": "task_123",
                "worker_id": "frontend",
                "runtime_type": "external_adapter",
                "final_state": "failed",
                "started_at": "2026-05-21T00:00:00Z",
                "completed_at": "2026-05-21T00:10:00Z",
                "error": {
                    "code": "output_parse_error",
                    "message": "bad output",
                    "safe_summary": "Could not parse adapter output.",
                    "retryable": False,
                    "source": "external_adapter",
                    "created_at": "2026-05-21T00:10:00Z",
                    "raw_stderr": "secret stderr",
                },
            }
        )

import json

import pytest

from worker_agents.external_adapter_output import (
    ExternalAdapterOutputError,
    ExternalAdapterRawOutput,
    external_adapter_audit_summary,
    external_adapter_audit_summary_to_dict,
    failed_external_adapter_parse_result,
    normalize_external_adapter_output,
)
from worker_agents.external_adapter_runner import ExternalAdapterBackendState
from worker_agents.runtime_contract import (
    RuntimeErrorCode,
    RuntimeExecutionBudget,
    RuntimeRequest,
    RuntimeRequestContext,
    RuntimeState,
    RuntimeType,
)


def _request():
    return RuntimeRequest(
        request_id="runtime-request-1",
        task_id="task-1",
        worker_id="researcher",
        runtime_type=RuntimeType.EXTERNAL_ADAPTER,
        requested_by="zermes_main_agent",
        created_at="2026-05-21T00:00:00Z",
        context=RuntimeRequestContext(input_message="Summarize the input."),
        budget=RuntimeExecutionBudget(
            budget_source="worker-profile:researcher",
            timeout_seconds=30,
        ),
    )


def _output(**overrides):
    data = {
        "invocation_id": "external-runtime-request-1",
        "adapter_id": "fake-external-adapter",
        "state": ExternalAdapterBackendState.SUCCEEDED,
        "safe_summary": "Fake adapter completed.",
        "completed_at": "2026-05-21T00:01:00Z",
    }
    data.update(overrides)
    return ExternalAdapterRawOutput(**data)


def test_normalizer_maps_json_output_to_runtime_result():
    adapter_output = json.dumps(
        {
            "public_message": "Done.",
            "internal_summary": "Completed safely.",
            "artifact_refs": [
                {
                    "manifest_ref": "manifests/result.json",
                    "artifact_type": "report",
                    "summary": "Result manifest.",
                }
            ],
            "memory_proposals": [
                {
                    "proposal_id": "proposal-1",
                    "target_scope": "worker:researcher",
                    "redacted_summary": "Prefer short research summaries.",
                    "source_task_id": "task-1",
                    "review_reason": "Worker preference candidate.",
                }
            ],
            "safety_requests": [
                {
                    "request_id": "safety-1",
                    "request_type": "review",
                    "risk_level": "medium",
                    "user_visible_summary": "Review before publishing.",
                    "required_approver": "zermes_main_agent",
                }
            ],
            "audit_summary": "Low-sensitive audit summary.",
        }
    )

    result = normalize_external_adapter_output(
        _request(),
        _output(adapter_output_text=adapter_output),
        started_at="2026-05-21T00:00:30Z",
    )

    assert result.final_state == RuntimeState.SUCCEEDED
    assert result.public_message == "Done."
    assert result.artifact_refs[0].manifest_ref == "manifests/result.json"
    assert result.memory_proposals[0].proposal_id == "proposal-1"
    assert result.safety_requests[0].request_id == "safety-1"


def test_normalizer_maps_text_output_to_public_message():
    result = normalize_external_adapter_output(
        _request(),
        _output(adapter_output_text="A concise public answer."),
        started_at="2026-05-21T00:00:30Z",
    )

    assert result.public_message == "A concise public answer."
    assert result.audit_summary is not None


def test_normalizer_rejects_sensitive_output_fields():
    with pytest.raises(ExternalAdapterOutputError, match="secret"):
        normalize_external_adapter_output(
            _request(),
            _output(adapter_output_text=json.dumps({"secret": "do-not-leak"})),
            started_at="2026-05-21T00:00:30Z",
        )


def test_normalizer_maps_failed_output_to_low_sensitive_error():
    result = normalize_external_adapter_output(
        _request(),
        _output(
            state=ExternalAdapterBackendState.FAILED,
            safe_summary="Adapter failed before producing a result.",
            raw_error_ref="tasks/task-1/logs/adapter.err",
        ),
        started_at="2026-05-21T00:00:30Z",
    )

    assert result.final_state == RuntimeState.FAILED
    assert result.error is not None
    assert result.error.code == RuntimeErrorCode.NON_RETRYABLE
    assert result.error.raw_error_ref == "tasks/task-1/logs/adapter.err"


def test_failed_parse_result_uses_output_parse_error():
    result = failed_external_adapter_parse_result(
        _request(),
        _output(raw_output_ref="tasks/task-1/output/result.json"),
        started_at="2026-05-21T00:00:30Z",
        message="Invalid adapter JSON.",
    )

    assert result.final_state == RuntimeState.FAILED
    assert result.error is not None
    assert result.error.code == RuntimeErrorCode.OUTPUT_PARSE_ERROR
    assert result.error.raw_error_ref == "tasks/task-1/output/result.json"


def test_audit_summary_uses_refs_not_raw_content():
    summary = external_adapter_audit_summary(
        _request(),
        _output(
            raw_output_ref="tasks/task-1/output/result.json",
            metrics={"output_bytes": 42},
        ),
    )

    data = external_adapter_audit_summary_to_dict(summary)

    assert data["raw_output_ref"] == "tasks/task-1/output/result.json"
    assert data["metrics"] == {"output_bytes": 42}
    assert "raw_output" not in data

import pytest

from worker_agents.result_routing import (
    ResultRouteItem,
    ResultRouteItemKind,
    ResultRouteVisibility,
    ResultRoutingError,
    classify_runtime_result,
    runtime_result_classification_to_dict,
)
from worker_agents.runtime_contract import (
    RuntimeArtifactRef,
    RuntimeErrorCode,
    RuntimeErrorInfo,
    RuntimeMemoryProposal,
    RuntimeResult,
    RuntimeSafetyRequest,
    RuntimeState,
    RuntimeType,
)


def _memory_proposal(proposal_id="memory_prop_123", target_scope="worker:frontend"):
    return RuntimeMemoryProposal(
        proposal_id=proposal_id,
        target_scope=target_scope,
        redacted_summary="Prefer small runtime changes with focused tests.",
        source_task_id="task_123",
        review_reason="Useful habit from this worker task.",
    )


def _safety_request():
    return RuntimeSafetyRequest(
        request_id="safety_req_123",
        request_type="high_risk_tool",
        risk_level="high",
        user_visible_summary="The worker needs review before changing permissions.",
        required_approver="zermes_main_agent",
    )


def _error(code=RuntimeErrorCode.OUTPUT_PARSE_ERROR):
    return RuntimeErrorInfo(
        code=code,
        message="Adapter output could not be parsed.",
        safe_summary="The adapter returned malformed structured output.",
        retryable=False,
        source="external_adapter",
        created_at="2026-05-21T00:10:00Z",
        raw_error_ref="tasks/task_123/runtime-error.log",
    )


def test_classifies_runtime_result_into_route_items():
    result = RuntimeResult(
        request_id="runtime_req_123",
        task_id="task_123",
        worker_id="frontend",
        runtime_type=RuntimeType.INTERNAL_WORKER,
        final_state=RuntimeState.SUCCEEDED,
        started_at="2026-05-21T00:00:00Z",
        completed_at="2026-05-21T00:10:00Z",
        public_message="Implementation is complete.",
        internal_summary="Added route item classification.",
        artifact_refs=(
            RuntimeArtifactRef(
                manifest_ref="tasks/task_123/result.json",
                artifact_type="patch_summary",
                summary="Patch summary manifest.",
            ),
        ),
        memory_proposals=(_memory_proposal(),),
        department_asset_proposals=(
            _memory_proposal("dept_prop_123", "department:engineering"),
        ),
        safety_requests=(_safety_request(),),
        audit_summary="No direct long-term writes happened.",
    )

    classification = classify_runtime_result(
        result, source_result_ref="runtime-results/runtime_req_123.json"
    )

    assert [item.kind for item in classification.route_items] == [
        ResultRouteItemKind.PUBLIC_MESSAGE,
        ResultRouteItemKind.SILENT_SUMMARY,
        ResultRouteItemKind.ARTIFACT_MANIFEST,
        ResultRouteItemKind.MEMORY_PROPOSAL,
        ResultRouteItemKind.DEPARTMENT_ASSET_PROPOSAL,
        ResultRouteItemKind.SAFETY_REQUEST,
        ResultRouteItemKind.AUDIT_SUMMARY,
    ]
    assert classification.route_items[0].visibility == (
        ResultRouteVisibility.USER_VISIBLE
    )
    assert classification.route_items[2].requires_main_agent_review is True
    assert classification.source_result_ref == "runtime-results/runtime_req_123.json"
    assert runtime_result_classification_to_dict(classification)["route_items"][0][
        "source_worker_id"
    ] == "frontend"


def test_failed_runtime_result_gets_failure_report_without_raw_error_ref():
    result = RuntimeResult(
        request_id="runtime_req_123",
        task_id="task_123",
        worker_id="frontend",
        runtime_type=RuntimeType.EXTERNAL_ADAPTER,
        final_state=RuntimeState.FAILED,
        started_at="2026-05-21T00:00:00Z",
        completed_at="2026-05-21T00:10:00Z",
        internal_summary="The adapter failed.",
        error=_error(),
    )

    classification = classify_runtime_result(result)
    failure = [
        item
        for item in classification.route_items
        if item.kind == ResultRouteItemKind.FAILURE_REPORT
    ][0]

    assert failure.visibility == ResultRouteVisibility.USER_VISIBLE
    assert failure.payload["final_state"] == "failed"
    assert "raw_error_ref" not in failure.payload["error"]


def test_partial_success_gets_failure_report_even_when_state_succeeded():
    result = RuntimeResult(
        request_id="runtime_req_123",
        task_id="task_123",
        worker_id="frontend",
        runtime_type=RuntimeType.INTERNAL_WORKER,
        final_state=RuntimeState.SUCCEEDED,
        started_at="2026-05-21T00:00:00Z",
        completed_at="2026-05-21T00:10:00Z",
        public_message="Some work completed.",
        partial_success=True,
    )

    classification = classify_runtime_result(result)

    assert ResultRouteItemKind.FAILURE_REPORT in {
        item.kind for item in classification.route_items
    }


def test_route_item_rejects_sensitive_payload_fields():
    with pytest.raises(ResultRoutingError, match="raw_transcript"):
        ResultRouteItem(
            route_item_id="route_item_123",
            source_runtime_session_id="runtime_req_123",
            source_worker_id="frontend",
            source_runtime_type=RuntimeType.INTERNAL_WORKER,
            task_id="task_123",
            kind=ResultRouteItemKind.PUBLIC_MESSAGE,
            visibility=ResultRouteVisibility.USER_VISIBLE,
            payload={"raw_transcript": "full hidden transcript"},
        )

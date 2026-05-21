import pytest

from worker_agents.result_routing import (
    ResultRouteItem,
    ResultRouteItemKind,
    ResultRouteVisibility,
    ResultRoutingError,
    RoutedApprovalKind,
    RoutedApprovalRequest,
    RoutedApprovalStatus,
    RuntimeResultClassification,
    approval_and_safety_route_to_dict,
    approval_request_with_status,
    classify_runtime_result,
    route_approval_and_safety_requests,
)
from worker_agents.runtime_contract import (
    RuntimeResult,
    RuntimeSafetyRequest,
    RuntimeState,
    RuntimeType,
)


def test_routes_runtime_safety_request_to_pending_governance_request():
    result = RuntimeResult(
        request_id="runtime_req_123",
        task_id="task_123",
        worker_id="frontend",
        runtime_type=RuntimeType.INTERNAL_WORKER,
        final_state=RuntimeState.SUCCEEDED,
        started_at="2026-05-21T00:00:00Z",
        completed_at="2026-05-21T00:10:00Z",
        safety_requests=(
            RuntimeSafetyRequest(
                request_id="safety_req_123",
                request_type="workspace_write",
                risk_level="high",
                user_visible_summary="The worker needs write access review.",
                required_approver="zermes_main_agent",
            ),
        ),
    )
    classification = classify_runtime_result(result)

    routed = route_approval_and_safety_requests(classification)

    assert len(routed.pending_requests) == 1
    request = routed.pending_requests[0]
    assert request.approval_kind == RoutedApprovalKind.SAFETY_REVIEW
    assert request.status == RoutedApprovalStatus.PENDING
    assert request.requested_capability == "workspace_write"
    assert approval_and_safety_route_to_dict(routed)["pending_requests"][0][
        "status"
    ] == "pending"


def test_routes_explicit_tool_permission_request_without_granting_access():
    route_item = ResultRouteItem(
        route_item_id="route_item_123",
        source_runtime_session_id="runtime_req_123",
        source_worker_id="frontend",
        source_runtime_type=RuntimeType.EXTERNAL_ADAPTER,
        task_id="task_123",
        kind=ResultRouteItemKind.APPROVAL_REQUEST,
        visibility=ResultRouteVisibility.MAIN_AGENT_REVIEW,
        payload={
            "request_id": "approval_req_123",
            "approval_kind": "tool_permission",
            "requested_capability": "write_file",
            "reason": "Need to update the generated implementation file.",
            "risk_summary": "Writes are limited to the approved workspace.",
            "required_approver": "zermes_main_agent",
            "expires_at": "2026-05-21T01:00:00Z",
        },
    )
    classification = RuntimeResultClassification(
        source_result_ref="runtime-results/runtime_req_123.json",
        route_items=(route_item,),
        audit_summary="Approval request routing test.",
    )

    routed = route_approval_and_safety_requests(classification)

    assert routed.pending_requests[0].approval_kind == (
        RoutedApprovalKind.TOOL_PERMISSION
    )
    assert routed.pending_requests[0].status == RoutedApprovalStatus.PENDING


def test_rejects_auto_approved_request_from_runtime_result():
    with pytest.raises(ResultRoutingError, match="cannot create approved"):
        RoutedApprovalRequest(
            approval_request_id="approval_req_123",
            approval_kind=RoutedApprovalKind.TOOL_PERMISSION,
            source_route_item_id="route_item_123",
            source_runtime_session_id="runtime_req_123",
            source_worker_id="frontend",
            task_id="task_123",
            requested_capability="write_file",
            reason="Need write access.",
            risk_summary="Writes can change files.",
            required_approver="zermes_main_agent",
            status=RoutedApprovalStatus.APPROVED,
        )


def test_denied_expired_and_cancelled_status_can_be_recorded():
    request = RoutedApprovalRequest(
        approval_request_id="approval_req_123",
        approval_kind=RoutedApprovalKind.EXTERNAL_SERVICE_ACCESS,
        source_route_item_id="route_item_123",
        source_runtime_session_id="runtime_req_123",
        source_worker_id="frontend",
        task_id="task_123",
        requested_capability="external_research_api",
        reason="Need external research data.",
        risk_summary="External service may transmit task context.",
        required_approver="zermes_main_agent",
    )

    denied = approval_request_with_status(
        request, RoutedApprovalStatus.DENIED, reason="Not needed for this task."
    )
    expired = approval_request_with_status(
        request, RoutedApprovalStatus.EXPIRED, reason="No decision before expiry."
    )
    cancelled = approval_request_with_status(
        request, RoutedApprovalStatus.CANCELLED, reason="Runtime was cancelled."
    )

    assert denied.status == RoutedApprovalStatus.DENIED
    assert expired.status == RoutedApprovalStatus.EXPIRED
    assert cancelled.status == RoutedApprovalStatus.CANCELLED
    assert denied.metadata["status_reason"] == "Not needed for this task."


def test_status_update_cannot_mark_request_approved():
    request = RoutedApprovalRequest(
        approval_request_id="approval_req_123",
        approval_kind=RoutedApprovalKind.MODEL_OR_BUDGET_INCREASE,
        source_route_item_id="route_item_123",
        source_runtime_session_id="runtime_req_123",
        source_worker_id="frontend",
        task_id="task_123",
        requested_capability="larger_runtime_budget",
        reason="Need more output tokens.",
        risk_summary="Budget increase affects cost.",
        required_approver="zermes_main_agent",
    )

    with pytest.raises(ResultRoutingError, match="must come from governance"):
        approval_request_with_status(
            request, RoutedApprovalStatus.APPROVED, reason="runtime cannot approve"
        )

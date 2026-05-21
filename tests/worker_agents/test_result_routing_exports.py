from worker_agents import (
    RESULT_ROUTING_SCHEMA_VERSION,
    ApprovalAndSafetyRoute,
    MessageRouterResultRoute,
    ProposalAndManifestRoute,
    ResultRouteItem,
    ResultRouteItemKind,
    ResultRouteVisibility,
    ResultRoutingError,
    RoutedApprovalKind,
    RoutedApprovalRequest,
    RoutedApprovalStatus,
    RoutedProposalKind,
    RoutedProposalRecord,
    RuntimeResultClassification,
    approval_and_safety_route_to_dict,
    approval_request_with_status,
    classify_runtime_result,
    message_router_result_route_to_dict,
    proposal_and_manifest_route_to_dict,
    route_approval_and_safety_requests,
    route_item_to_dict,
    route_pending_proposals_and_manifests,
    route_user_visible_result_messages,
    routed_approval_request_to_dict,
    routed_proposal_record_to_dict,
    runtime_result_classification_to_dict,
)


def test_result_routing_api_is_available_from_worker_agents_package():
    assert RESULT_ROUTING_SCHEMA_VERSION == 1
    assert ResultRoutingError.__name__ == "ResultRoutingError"
    assert ResultRouteItem.__name__ == "ResultRouteItem"
    assert RuntimeResultClassification.__name__ == "RuntimeResultClassification"
    assert MessageRouterResultRoute.__name__ == "MessageRouterResultRoute"
    assert ProposalAndManifestRoute.__name__ == "ProposalAndManifestRoute"
    assert RoutedProposalRecord.__name__ == "RoutedProposalRecord"
    assert ApprovalAndSafetyRoute.__name__ == "ApprovalAndSafetyRoute"
    assert RoutedApprovalRequest.__name__ == "RoutedApprovalRequest"
    assert ResultRouteItemKind.PUBLIC_MESSAGE.value == "public_message"
    assert ResultRouteVisibility.USER_VISIBLE.value == "user_visible"
    assert RoutedProposalKind.WORKER_MEMORY.value == "worker_memory"
    assert RoutedApprovalKind.SAFETY_REVIEW.value == "safety_review"
    assert RoutedApprovalStatus.PENDING.value == "pending"
    assert classify_runtime_result.__name__ == "classify_runtime_result"
    assert route_item_to_dict.__name__ == "route_item_to_dict"
    assert route_user_visible_result_messages.__name__ == (
        "route_user_visible_result_messages"
    )
    assert route_pending_proposals_and_manifests.__name__ == (
        "route_pending_proposals_and_manifests"
    )
    assert route_approval_and_safety_requests.__name__ == (
        "route_approval_and_safety_requests"
    )
    assert approval_request_with_status.__name__ == "approval_request_with_status"
    assert runtime_result_classification_to_dict.__name__ == (
        "runtime_result_classification_to_dict"
    )
    assert message_router_result_route_to_dict.__name__ == (
        "message_router_result_route_to_dict"
    )
    assert proposal_and_manifest_route_to_dict.__name__ == (
        "proposal_and_manifest_route_to_dict"
    )
    assert approval_and_safety_route_to_dict.__name__ == (
        "approval_and_safety_route_to_dict"
    )
    assert routed_proposal_record_to_dict.__name__ == (
        "routed_proposal_record_to_dict"
    )
    assert routed_approval_request_to_dict.__name__ == (
        "routed_approval_request_to_dict"
    )

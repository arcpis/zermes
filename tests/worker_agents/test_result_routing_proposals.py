import pytest

from worker_agents.result_routing import (
    ResultRouteItem,
    ResultRouteItemKind,
    ResultRouteVisibility,
    ResultRoutingError,
    RuntimeResultClassification,
    RoutedProposalKind,
    classify_runtime_result,
    proposal_and_manifest_route_to_dict,
    route_pending_proposals_and_manifests,
)
from worker_agents.runtime_contract import (
    RuntimeArtifactRef,
    RuntimeMemoryProposal,
    RuntimeResult,
    RuntimeState,
    RuntimeType,
)


def _memory_proposal(proposal_id="memory_prop_123", target_scope="worker:frontend"):
    return RuntimeMemoryProposal(
        proposal_id=proposal_id,
        target_scope=target_scope,
        redacted_summary="Prefer focused tests around worker runtime changes.",
        source_task_id="task_123",
        review_reason="Useful implementation habit.",
    )


def test_routes_manifest_and_memory_candidates_as_pending_proposals():
    result = RuntimeResult(
        request_id="runtime_req_123",
        task_id="task_123",
        worker_id="frontend",
        runtime_type=RuntimeType.INTERNAL_WORKER,
        final_state=RuntimeState.SUCCEEDED,
        started_at="2026-05-21T00:00:00Z",
        completed_at="2026-05-21T00:10:00Z",
        artifact_refs=(
            RuntimeArtifactRef(
                manifest_ref="artifacts/result-manifest.json",
                artifact_type="patch_summary",
                summary="Patch summary manifest.",
                retention_policy_ref="retention/default",
            ),
        ),
        memory_proposals=(_memory_proposal(),),
        department_asset_proposals=(
            _memory_proposal("dept_prop_123", "department:engineering"),
        ),
        audit_summary="No proposal was accepted automatically.",
    )
    classification = classify_runtime_result(result)

    routed = route_pending_proposals_and_manifests(classification)

    assert [proposal.proposal_kind for proposal in routed.pending_proposals] == [
        RoutedProposalKind.ARTIFACT_MANIFEST,
        RoutedProposalKind.WORKER_MEMORY,
        RoutedProposalKind.DEPARTMENT_ASSET,
    ]
    assert {proposal.review_status for proposal in routed.pending_proposals} == {
        "pending"
    }
    manifest = routed.pending_proposals[0]
    assert manifest.payload_ref == "artifacts/result-manifest.json"
    assert manifest.metadata["artifact_type"] == "patch_summary"
    assert proposal_and_manifest_route_to_dict(routed)["pending_proposals"][0][
        "review_status"
    ] == "pending"


def test_non_proposal_route_items_are_skipped():
    result = RuntimeResult(
        request_id="runtime_req_123",
        task_id="task_123",
        worker_id="frontend",
        runtime_type=RuntimeType.INTERNAL_WORKER,
        final_state=RuntimeState.SUCCEEDED,
        started_at="2026-05-21T00:00:00Z",
        completed_at="2026-05-21T00:10:00Z",
        public_message="Done.",
    )
    classification = classify_runtime_result(result)

    routed = route_pending_proposals_and_manifests(classification)

    assert routed.pending_proposals == ()
    assert routed.skipped_route_item_ids == ("runtime_req_123-public_message-1",)


def test_manifest_payload_ref_must_stay_relative():
    route_item = ResultRouteItem(
        route_item_id="route_item_123",
        source_runtime_session_id="runtime_req_123",
        source_worker_id="frontend",
        source_runtime_type=RuntimeType.INTERNAL_WORKER,
        task_id="task_123",
        kind=ResultRouteItemKind.ARTIFACT_MANIFEST,
        visibility=ResultRouteVisibility.PENDING_REVIEW,
        payload={
            "manifest_ref": "../outside/result.json",
            "artifact_type": "patch_summary",
            "summary": "Unsafe manifest reference.",
        },
    )

    classification = RuntimeResultClassification(
        source_result_ref="runtime-results/runtime_req_123.json",
        route_items=(route_item,),
        audit_summary="Unsafe manifest reference test.",
    )

    with pytest.raises(ResultRoutingError, match="traverse parent"):
        route_pending_proposals_and_manifests(classification)


def test_learning_route_item_becomes_pending_learning_proposal():
    route_item = ResultRouteItem(
        route_item_id="route_item_123",
        source_runtime_session_id="runtime_req_123",
        source_worker_id="frontend",
        source_runtime_type=RuntimeType.INTERNAL_WORKER,
        task_id="task_123",
        kind=ResultRouteItemKind.LEARNING_PROPOSAL,
        visibility=ResultRouteVisibility.PENDING_REVIEW,
        payload={
            "proposal_id": "learning_prop_123",
            "target_scope": "worker:frontend:learning",
            "redacted_summary": "Use fake adapters in result routing tests.",
            "review_reason": "Worker-specific testing habit.",
        },
    )

    classification = RuntimeResultClassification(
        source_result_ref="runtime-results/runtime_req_123.json",
        route_items=(route_item,),
        audit_summary="Learning proposal test.",
    )

    routed = route_pending_proposals_and_manifests(classification)

    assert routed.pending_proposals[0].proposal_kind == (
        RoutedProposalKind.WORKER_LEARNING
    )
    assert routed.pending_proposals[0].review_status == "pending"

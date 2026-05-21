from worker_agents.department_memory import (
    DepartmentMemoryKind,
    DepartmentMemoryProposalStore,
    DepartmentMemoryReadRequest,
    DepartmentMemoryReadService,
    DepartmentMemoryReviewAction,
    DepartmentMemoryReviewDecision,
    DepartmentMemoryReviewService,
    DepartmentMemoryReviewerRole,
    DepartmentMemoryVisibility,
    proposal_from_private_asset_input,
)
from worker_agents.private_assets import (
    PrivateAssetSensitivity,
    PrivateAssetShareStatus,
    PrivateMemoryRecord,
    private_memory_to_proposal_input,
)


def test_low_sensitive_private_candidate_reaches_redacted_department_view(tmp_path):
    private_memory = PrivateMemoryRecord(
        worker_id="frontend",
        asset_id="memory-1",
        summary="Always include rollback notes in release handoffs.",
        source_refs=("tasks/task_123/summary.json",),
        sensitivity=PrivateAssetSensitivity.LOW,
        share_status=PrivateAssetShareStatus.PROPOSAL_ALLOWED,
        audit_summary="Private text was summarized before sharing.",
    )
    proposal_input = private_memory_to_proposal_input(
        private_memory,
        proposal_input_id="input-1",
        target_scope="department:platform",
        content_hash="sha256:handoff",
    )
    proposal = proposal_from_private_asset_input(
        proposal_input,
        proposal_id="proposal-1",
        department_id="platform",
        kind=DepartmentMemoryKind.DELIVERY_STANDARD,
        visibility=DepartmentMemoryVisibility.INHERITABLE_SUMMARY,
    )
    store = DepartmentMemoryProposalStore(root=tmp_path)
    store.create_proposal(proposal)
    review = DepartmentMemoryReviewService(store)

    review.approve(
        "platform",
        "proposal-1",
        DepartmentMemoryReviewAction(
            proposal_id="proposal-1",
            decision=DepartmentMemoryReviewDecision.APPROVE,
            actor_id="main-agent",
            actor_role=DepartmentMemoryReviewerRole.MAIN_AGENT,
            reason="Useful repeated delivery standard.",
            reviewed_at="2026-05-21T01:00:00Z",
        ),
    )
    result = DepartmentMemoryReadService(root=tmp_path).read(
        DepartmentMemoryReadRequest(
            department_id="child-platform",
            requester_scope="context_policy",
            include_inherited=True,
            inherited_department_ids=("platform",),
        )
    )

    assert len(result.views) == 1
    assert result.views[0].redacted_summary == (
        "Always include rollback notes in release handoffs."
    )
    assert result.views[0].inherited is True

import pytest

from worker_agents.department_memory import (
    DepartmentMemoryError,
    DepartmentMemoryKind,
    DepartmentMemoryProposal,
    DepartmentMemoryProposalCreateStatus,
    DepartmentMemoryProposalState,
    DepartmentMemoryProposalStore,
    DepartmentMemorySensitivity,
    proposal_from_private_asset_input,
    proposal_from_routed_department_asset,
)
from worker_agents.private_assets import (
    PrivateAssetProposalInput,
    PrivateAssetSensitivity,
)
from worker_agents.result_routing import (
    RoutedProposalKind,
    RoutedProposalRecord,
)


def test_store_creates_and_loads_pending_proposal(tmp_path):
    store = DepartmentMemoryProposalStore(root=tmp_path)
    proposal = DepartmentMemoryProposal(
        proposal_id="proposal-1",
        department_id="platform",
        kind=DepartmentMemoryKind.DELIVERY_STANDARD,
        candidate_summary="Every handoff includes validation evidence.",
        source_actor="main_agent",
        source_hash="sha256:abc",
        created_at="2026-05-21T00:00:00Z",
    )

    result = store.create_proposal(proposal)
    loaded = store.load_proposal("platform", "proposal-1")

    assert result.status == DepartmentMemoryProposalCreateStatus.CREATED
    assert loaded == proposal
    assert store.proposal_path("platform", "proposal-1").parts[-3:] == (
        "memory",
        "proposals",
        "proposal-1.json",
    )


def test_store_filters_proposals_by_state_kind_and_sensitivity(tmp_path):
    store = DepartmentMemoryProposalStore(root=tmp_path)
    first = DepartmentMemoryProposal(
        proposal_id="proposal-1",
        department_id="platform",
        kind=DepartmentMemoryKind.RISK,
        candidate_summary="Watch adapter output boundaries.",
        source_actor="worker-a",
        sensitivity=DepartmentMemorySensitivity.INTERNAL,
    )
    second = DepartmentMemoryProposal(
        proposal_id="proposal-2",
        department_id="platform",
        kind=DepartmentMemoryKind.RETROSPECTIVE,
        candidate_summary="Prefer focused tests for routing changes.",
        source_actor="worker-b",
        sensitivity=DepartmentMemorySensitivity.LOW,
    )
    store.create_proposal(first)
    store.create_proposal(second)

    assert store.list_proposals("platform", kind=DepartmentMemoryKind.RISK) == [first]
    assert store.list_proposals(
        "platform", sensitivity=DepartmentMemorySensitivity.LOW
    ) == [second]
    assert store.list_proposals(
        "platform", state=DepartmentMemoryProposalState.PENDING
    ) == [first, second]


def test_store_returns_existing_pending_duplicate_by_source_hash(tmp_path):
    store = DepartmentMemoryProposalStore(root=tmp_path)
    first = DepartmentMemoryProposal(
        proposal_id="proposal-1",
        department_id="platform",
        kind=DepartmentMemoryKind.RISK,
        candidate_summary="Review timeout risk.",
        source_actor="main_agent",
        source_hash="sha256:same",
    )
    duplicate = DepartmentMemoryProposal(
        proposal_id="proposal-2",
        department_id="platform",
        kind=DepartmentMemoryKind.RISK,
        candidate_summary="Review timeout risk again.",
        source_actor="main_agent",
        source_hash="sha256:same",
    )

    store.create_proposal(first)
    result = store.create_proposal(duplicate)

    assert result.status == DepartmentMemoryProposalCreateStatus.EXISTING
    assert result.proposal == first
    assert store.list_proposals("platform") == [first]


def test_routed_department_asset_becomes_pending_memory_proposal():
    routed = RoutedProposalRecord(
        proposal_id="dept-prop-1",
        proposal_kind=RoutedProposalKind.DEPARTMENT_ASSET,
        source_route_item_id="route-item-1",
        source_runtime_session_id="runtime-1",
        source_worker_id="frontend",
        task_id="task_123",
        target_scope="department:platform",
        summary="Add checklist for release handoffs.",
        metadata={"review_reason": "Repeated handoff issue.", "source_hash": "sha256:a"},
    )

    proposal = proposal_from_routed_department_asset(
        routed,
        kind=DepartmentMemoryKind.DELIVERY_STANDARD,
        created_at="2026-05-21T00:00:00Z",
    )

    assert proposal.department_id == "platform"
    assert proposal.state == DepartmentMemoryProposalState.PENDING
    assert proposal.candidate_summary == "Add checklist for release handoffs."
    assert proposal.source_refs == ("tasks/task_123/runtime/route-item-1",)


def test_private_asset_input_becomes_department_memory_proposal_without_raw_text():
    proposal_input = PrivateAssetProposalInput(
        proposal_input_id="input-1",
        source_worker_id="frontend",
        source_asset_id="memory-1",
        target_scope="department:platform",
        summary="Prefer focused tests around message routing changes.",
        source_refs=("tasks/task_123/summary.json",),
        content_hash="sha256:abc",
        sensitivity=PrivateAssetSensitivity.LOW,
    )

    proposal = proposal_from_private_asset_input(
        proposal_input,
        proposal_id="proposal-1",
        department_id="platform",
        kind=DepartmentMemoryKind.COLLABORATION_NORM,
    )

    assert proposal.candidate_summary == proposal_input.summary
    assert proposal.source_actor == "frontend"
    assert proposal.source_hash == "sha256:abc"
    assert "private_memory_text" not in proposal.candidate_summary


def test_store_rejects_non_pending_creation(tmp_path):
    store = DepartmentMemoryProposalStore(root=tmp_path)
    proposal = DepartmentMemoryProposal(
        proposal_id="proposal-1",
        department_id="platform",
        kind=DepartmentMemoryKind.RISK,
        candidate_summary="Risk summary.",
        source_actor="main_agent",
        state=DepartmentMemoryProposalState.REJECTED,
    )

    with pytest.raises(DepartmentMemoryError, match="must be pending"):
        store.create_proposal(proposal)

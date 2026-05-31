import pytest

from worker_agents.department_memory import (
    DepartmentMemoryError,
    DepartmentMemoryKind,
    DepartmentMemoryProposal,
    DepartmentMemoryProposalState,
    DepartmentMemoryProposalStore,
    DepartmentMemoryReviewAction,
    DepartmentMemoryReviewDecision,
    DepartmentMemoryReviewService,
    DepartmentMemoryReviewerRole,
    DepartmentMemorySensitivity,
)


def _store_with_proposal(tmp_path, proposal=None):
    store = DepartmentMemoryProposalStore(root=tmp_path)
    proposal = proposal or DepartmentMemoryProposal(
        proposal_id="proposal-1",
        department_id="platform",
        kind=DepartmentMemoryKind.DELIVERY_STANDARD,
        candidate_summary="Every release handoff includes test evidence.",
        source_actor="frontend",
        source_refs=("tasks/task_123/summary.json",),
        created_at="2026-05-21T00:00:00Z",
    )
    store.create_proposal(proposal)
    return store, proposal


def _action(decision=DepartmentMemoryReviewDecision.APPROVE, **overrides):
    values = {
        "proposal_id": "proposal-1",
        "decision": decision,
        "actor_id": "lead-worker",
        "actor_role": DepartmentMemoryReviewerRole.DEPARTMENT_LEAD,
        "reason": "Useful department standard.",
        "reviewed_at": "2026-05-21T01:00:00Z",
    }
    values.update(overrides)
    return DepartmentMemoryReviewAction(**values)


def test_approve_pending_proposal_creates_active_memory(tmp_path):
    store, proposal = _store_with_proposal(tmp_path)
    service = DepartmentMemoryReviewService(store)

    memory = service.approve("platform", "proposal-1", _action())
    updated = store.load_proposal("platform", "proposal-1")

    assert memory.memory_id == proposal.proposal_id
    assert memory.summary == proposal.candidate_summary
    assert memory.revision == 1
    assert updated.state == DepartmentMemoryProposalState.APPROVED
    assert service.memory_path("platform", "proposal-1").exists()


@pytest.mark.parametrize(
    ("decision", "method_name", "expected_state"),
    [
        (
            DepartmentMemoryReviewDecision.REJECT,
            "reject",
            DepartmentMemoryProposalState.REJECTED,
        ),
        (
            DepartmentMemoryReviewDecision.REQUEST_CHANGES,
            "request_changes",
            DepartmentMemoryProposalState.CHANGES_REQUESTED,
        ),
        (
            DepartmentMemoryReviewDecision.EXPIRE,
            "expire",
            DepartmentMemoryProposalState.EXPIRED,
        ),
    ],
)
def test_non_approve_decisions_do_not_create_active_memory(
    tmp_path, decision, method_name, expected_state
):
    store, _proposal = _store_with_proposal(tmp_path)
    service = DepartmentMemoryReviewService(store)

    updated = getattr(service, method_name)(
        "platform", "proposal-1", _action(decision)
    )

    assert updated.state == expected_state
    assert not service.memory_path("platform", "proposal-1").exists()


def test_high_sensitivity_approval_requires_user_confirmation(tmp_path):
    proposal = DepartmentMemoryProposal(
        proposal_id="proposal-1",
        department_id="platform",
        kind=DepartmentMemoryKind.RISK,
        candidate_summary="Sensitive operational risk summary.",
        source_actor="main_agent",
        sensitivity=DepartmentMemorySensitivity.USER_CONFIRMATION_REQUIRED,
    )
    store, _proposal = _store_with_proposal(tmp_path, proposal)
    service = DepartmentMemoryReviewService(store)

    with pytest.raises(DepartmentMemoryError, match="user confirmation"):
        service.approve("platform", "proposal-1", _action())

    memory = service.approve(
        "platform",
        "proposal-1",
        _action(user_confirmation_ref="approvals/user-confirmation-1.json"),
    )

    assert memory.sensitivity == DepartmentMemorySensitivity.USER_CONFIRMATION_REQUIRED


def test_supersede_keeps_old_revision_in_history(tmp_path):
    store, _proposal = _store_with_proposal(tmp_path)
    service = DepartmentMemoryReviewService(store)
    first = service.approve("platform", "proposal-1", _action())
    second_proposal = DepartmentMemoryProposal(
        proposal_id="proposal-2",
        department_id="platform",
        kind=DepartmentMemoryKind.DELIVERY_STANDARD,
        candidate_summary="Every release handoff includes tests and known risks.",
        source_actor="frontend",
    )
    store.create_proposal(second_proposal)

    second = service.approve(
        "platform",
        "proposal-2",
        _action(
            proposal_id="proposal-2",
            supersede_memory_id=first.memory_id,
            audit_refs=("tasks/task_456/summary.json",),
        ),
    )

    assert second.memory_id == first.memory_id
    assert second.revision == 2
    assert service.history_path("platform", first.memory_id, 1).exists()
    assert store.load_proposal("platform", "proposal-2").state == (
        DepartmentMemoryProposalState.SUPERSEDED
    )


def test_review_action_must_match_proposal_and_decision(tmp_path):
    store, _proposal = _store_with_proposal(tmp_path)
    service = DepartmentMemoryReviewService(store)

    with pytest.raises(DepartmentMemoryError, match="proposal_id"):
        service.approve("platform", "proposal-1", _action(proposal_id="other"))

    with pytest.raises(DepartmentMemoryError, match="decision"):
        service.approve(
            "platform",
            "proposal-1",
            _action(DepartmentMemoryReviewDecision.REJECT),
        )

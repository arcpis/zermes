import pytest

from worker_agents.organization_evolution import (
    EVOLUTION_PROPOSAL_SCHEMA_VERSION,
    EvolutionProposalStatus,
    OrganizationEvolutionError,
    organization_evolution_proposal_from_dict,
)
from worker_agents.organization_evolution_executor import (
    EvolutionExecutionState,
    EvolutionExecutionStatus,
    EvolutionExecutionStep,
    EvolutionExecutionStore,
    begin_evolution_execution,
    evolution_execution_state_from_dict,
    evolution_execution_state_to_dict,
    mark_execution_failed,
    mark_execution_step_completed,
)


NOW = "2026-05-26T00:00:00Z"


def _proposal_data(**overrides):
    data = {
        "proposal_id": "proposal_001",
        "proposal_type": "create_child_agent",
        "schema_version": EVOLUTION_PROPOSAL_SCHEMA_VERSION,
        "status": "approved",
        "initiator": {
            "kind": "main_agent",
            "initiator_id": "zermes_main_agent",
            "display_name": "Zermes",
        },
        "target_node_ids": ["platform"],
        "affected_worker_ids": ["platform_worker"],
        "reason": "Add a focused platform worker.",
        "before_summary": "Platform has no child specialist.",
        "after_summary": "Platform has one child specialist.",
        "risk_flags": [],
        "approval_policy": "policy approved",
        "asset_disposition_refs": [],
        "chat_disposition_refs": ["chats/platform-create.md"],
        "rollback_summary_ref": "rollback/platform-create.md",
        "source_refs": ["runtime/result-summary.json"],
        "created_at": "2026-05-26T00:00:00Z",
        "updated_at": "2026-05-26T00:00:00Z",
    }
    data.update(overrides)
    return data


def _proposal(**overrides):
    return organization_evolution_proposal_from_dict(_proposal_data(**overrides))


def _store(tmp_path):
    return EvolutionExecutionStore(tmp_path / "worker_agents" / "organization")


def test_approved_proposal_can_begin_running_execution(tmp_path):
    store = _store(tmp_path)

    state = begin_evolution_execution(
        _proposal(),
        actor="executor",
        now=NOW,
        store=store,
        execution_id="execution_001",
    )

    assert state.status is EvolutionExecutionStatus.RUNNING
    assert state.locked_org_node_ids == ("platform",)
    assert state.locked_worker_ids == ("platform_worker",)
    assert store.load_state("execution_001") == state
    assert store.load_locks()["execution_001"] == state


@pytest.mark.parametrize(
    "status",
    [
        EvolutionProposalStatus.DRAFT,
        EvolutionProposalStatus.PENDING_APPROVAL,
        EvolutionProposalStatus.REJECTED,
        EvolutionProposalStatus.EXPIRED,
    ],
)
def test_non_approved_proposal_cannot_begin_execution(tmp_path, status):
    with pytest.raises(OrganizationEvolutionError, match="approved"):
        begin_evolution_execution(
            _proposal(status=status.value),
            actor="executor",
            now=NOW,
            store=_store(tmp_path),
        )


def test_expired_plan_cannot_begin_execution(tmp_path):
    with pytest.raises(OrganizationEvolutionError, match="expired"):
        begin_evolution_execution(
            _proposal(),
            actor="executor",
            now=NOW,
            store=_store(tmp_path),
            plan_expires_at="2026-05-25T23:59:59Z",
        )


def test_blocking_flags_cannot_begin_execution(tmp_path):
    with pytest.raises(OrganizationEvolutionError, match="blocking flags"):
        begin_evolution_execution(
            _proposal(risk_flags=["active_tasks"]),
            actor="executor",
            now=NOW,
            store=_store(tmp_path),
        )


def test_org_node_lock_conflict_rejects_second_execution(tmp_path):
    store = _store(tmp_path)
    begin_evolution_execution(
        _proposal(proposal_id="proposal_001"),
        actor="executor",
        now=NOW,
        store=store,
        execution_id="execution_001",
    )

    with pytest.raises(OrganizationEvolutionError, match="organization node"):
        begin_evolution_execution(
            _proposal(proposal_id="proposal_002"),
            actor="executor",
            now=NOW,
            store=store,
            execution_id="execution_002",
        )


def test_worker_lock_conflict_rejects_second_execution(tmp_path):
    store = _store(tmp_path)
    begin_evolution_execution(
        _proposal(proposal_id="proposal_001", target_node_ids=["platform"]),
        actor="executor",
        now=NOW,
        store=store,
        execution_id="execution_001",
    )

    with pytest.raises(OrganizationEvolutionError, match="worker"):
        begin_evolution_execution(
            _proposal(proposal_id="proposal_002", target_node_ids=["design"]),
            actor="executor",
            now=NOW,
            store=store,
            execution_id="execution_002",
        )


def test_execution_state_serialization_round_trips():
    state = EvolutionExecutionState(
        execution_id="execution_001",
        proposal_id="proposal_001",
        status=EvolutionExecutionStatus.REQUIRES_MANUAL_RECOVERY,
        actor="executor",
        started_at=NOW,
        updated_at=NOW,
        locked_org_node_ids=("platform",),
        locked_worker_ids=("platform_worker",),
        completed_steps=(EvolutionExecutionStep.REGISTRY_PRECHECK,),
        failed_step=EvolutionExecutionStep.ORGANIZATION_TREE_UPDATE,
        failure_reason="tree revision changed",
        manual_recovery_hint="Review active organization before retrying.",
    )

    loaded = evolution_execution_state_from_dict(
        evolution_execution_state_to_dict(state)
    )

    assert loaded == state


def test_execution_state_records_steps_and_failure_hint():
    state = EvolutionExecutionState(
        execution_id="execution_001",
        proposal_id="proposal_001",
        status=EvolutionExecutionStatus.RUNNING,
        actor="executor",
        started_at=NOW,
        updated_at=NOW,
        locked_org_node_ids=("platform",),
        locked_worker_ids=("platform_worker",),
    )

    state = mark_execution_step_completed(
        state,
        EvolutionExecutionStep.REGISTRY_PRECHECK,
        updated_at="2026-05-26T00:01:00Z",
    )
    state = mark_execution_failed(
        state,
        EvolutionExecutionStep.ORGANIZATION_TREE_UPDATE,
        reason="active tree changed",
        manual_recovery_hint="Inspect active tree and resume manually.",
        updated_at="2026-05-26T00:02:00Z",
    )

    assert state.completed_steps == (EvolutionExecutionStep.REGISTRY_PRECHECK,)
    assert state.failed_step is EvolutionExecutionStep.ORGANIZATION_TREE_UPDATE
    assert state.status is EvolutionExecutionStatus.REQUIRES_MANUAL_RECOVERY
    assert state.manual_recovery_hint == "Inspect active tree and resume manually."

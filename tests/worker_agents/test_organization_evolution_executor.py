import pytest

from worker_agents.organization_evolution import (
    EVOLUTION_PROPOSAL_SCHEMA_VERSION,
    EvolutionProposalStatus,
    OrganizationEvolutionError,
    organization_evolution_proposal_from_dict,
)
from worker_agents.organization import (
    OrgLifecycleState,
    OrgLeaderKind,
    OrgLeaderRef,
    OrgNode,
    OrgNodeType,
    OrgTree,
)
from worker_agents.organization_evolution_executor import (
    ControlledEvolutionOperation,
    ControlledEvolutionPlan,
    EvolutionExecutionState,
    EvolutionExecutionStatus,
    EvolutionExecutionStep,
    EvolutionExecutionStore,
    apply_approved_evolution_plan,
    begin_evolution_execution,
    evolution_execution_state_from_dict,
    evolution_execution_state_to_dict,
    mark_execution_failed,
    mark_execution_step_completed,
)
from worker_agents.registry import (
    WorkerLifecycleStatus,
    WorkerRegistryRecord,
    WorkerRegistryStore,
)
from worker_agents.storage.organization_store import OrganizationStore


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


def _organization_store(tmp_path):
    return OrganizationStore(tmp_path / "worker_agents" / "organization")


def _registry_store(tmp_path):
    return WorkerRegistryStore(tmp_path / "worker_agents")


def _node(
    node_id,
    name,
    node_type,
    *,
    parent_id=None,
    child_ids=(),
    worker_id=None,
    lifecycle=OrgLifecycleState.ACTIVE,
):
    return OrgNode(
        org_node_id=node_id,
        name=name,
        node_type=node_type,
        parent_id=parent_id,
        child_ids=child_ids,
        individual_worker_id=worker_id if node_type is OrgNodeType.INDIVIDUAL else None,
        member_worker_ids=(worker_id,) if node_type is not OrgNodeType.INDIVIDUAL and worker_id else (),
        leader=OrgLeaderRef(kind=OrgLeaderKind.WORKER, worker_id=worker_id)
        if worker_id and node_type is not OrgNodeType.INDIVIDUAL
        else OrgLeaderRef(),
        lifecycle=lifecycle,
    )


def _tree(*, revision=1):
    root = OrgNode(
        org_node_id="root",
        name="Zermes",
        node_type=OrgNodeType.ROOT,
        child_ids=("platform", "design"),
        leader=OrgLeaderRef(kind=OrgLeaderKind.MAIN_AGENT),
        lifecycle=OrgLifecycleState.ACTIVE,
    )
    platform = _node(
        "platform",
        "Platform",
        OrgNodeType.DEPARTMENT,
        parent_id="root",
        child_ids=("legacy_worker_node",),
    )
    design = _node("design", "Design", OrgNodeType.DEPARTMENT, parent_id="root")
    legacy = _node(
        "legacy_worker_node",
        "Legacy Worker",
        OrgNodeType.INDIVIDUAL,
        parent_id="platform",
        worker_id="legacy_worker",
    )
    nodes = {node.org_node_id: node for node in (root, platform, design, legacy)}
    return OrgTree(tree_id="default", root_node_id="root", nodes=nodes, revision=revision)


def _worker(worker_id, *, status=WorkerLifecycleStatus.ENABLED):
    return WorkerRegistryRecord(
        worker_id=worker_id,
        display_name=worker_id.replace("_", " ").title(),
        role="worker",
        runtime_type="internal",
        status=status,
    )


def _begin(tmp_path, proposal):
    return begin_evolution_execution(
        proposal,
        actor="executor",
        now=NOW,
        store=_store(tmp_path),
        execution_id=f"execution_{proposal.proposal_id}",
    )


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


def test_revision_mismatch_blocks_controlled_writes(tmp_path):
    organization_store = _organization_store(tmp_path)
    organization_store.save_active_organization(_tree(revision=2))
    registry_store = _registry_store(tmp_path)
    registry_store.save_records({"platform_worker": _worker("platform_worker")})
    execution_store = _store(tmp_path)
    proposal = _proposal()
    state = _begin(tmp_path, proposal)
    plan = ControlledEvolutionPlan(
        proposal=proposal,
        operation=ControlledEvolutionOperation.CREATE_CHILD_AGENT,
        expected_tree_revision=1,
    )

    with pytest.raises(OrganizationEvolutionError, match="revision mismatch"):
        apply_approved_evolution_plan(
            plan,
            state=state,
            actor="executor",
            now=NOW,
            organization_store=organization_store,
            registry_store=registry_store,
            execution_store=execution_store,
        )

    failed_state = execution_store.load_state(state.execution_id)
    assert failed_state.failed_step is EvolutionExecutionStep.REGISTRY_PRECHECK


def test_controlled_plan_rejects_node_outside_proposal_scope():
    outside_node = _node("design_child", "Design Child", OrgNodeType.TEAM, parent_id="design")

    with pytest.raises(OrganizationEvolutionError, match="outside proposal scope"):
        ControlledEvolutionPlan(
            proposal=_proposal(),
            operation=ControlledEvolutionOperation.CREATE_CHILD_AGENT,
            expected_tree_revision=1,
            org_nodes_to_write=(outside_node,),
        )


def test_create_child_agent_updates_registry_tree_chat_and_asset_markers(tmp_path):
    organization_store = _organization_store(tmp_path)
    organization_store.save_active_organization(_tree(revision=1))
    registry_store = _registry_store(tmp_path)
    registry_store.save_records({})
    execution_store = _store(tmp_path)
    proposal = _proposal(
        target_node_ids=["platform_child"],
        affected_worker_ids=["platform_worker"],
    )
    state = _begin(tmp_path, proposal)
    child_node = _node(
        "platform_child",
        "Platform Worker",
        OrgNodeType.INDIVIDUAL,
        parent_id="platform",
        worker_id="platform_worker",
    )
    plan = ControlledEvolutionPlan(
        proposal=proposal,
        operation=ControlledEvolutionOperation.CREATE_CHILD_AGENT,
        expected_tree_revision=1,
        org_nodes_to_write=(child_node,),
        registry_records_to_create=(_worker("platform_worker"),),
        chat_binding_updates={"platform_child": "active"},
        asset_disposition_markers={"platform_child": "adopted"},
    )

    updated_state = apply_approved_evolution_plan(
        plan,
        state=state,
        actor="executor",
        now="2026-05-26T00:05:00Z",
        organization_store=organization_store,
        registry_store=registry_store,
        execution_store=execution_store,
    )

    assert updated_state.completed_steps == (
        EvolutionExecutionStep.REGISTRY_PRECHECK,
        EvolutionExecutionStep.REGISTRY_LIFECYCLE_UPDATE,
        EvolutionExecutionStep.ORGANIZATION_TREE_UPDATE,
        EvolutionExecutionStep.CHAT_BINDING_UPDATE,
        EvolutionExecutionStep.ASSET_DISPOSITION_UPDATE,
    )
    assert registry_store.load_records()["platform_worker"].status is WorkerLifecycleStatus.ENABLED
    tree = organization_store.load_active_organization()
    assert tree.nodes["platform_child"].individual_worker_id == "platform_worker"
    assert "platform_child" in tree.nodes["platform"].child_ids
    assert execution_store.load_chat_binding_statuses()["platform_child"] == "active"
    assert execution_store.load_asset_disposition_markers()["platform_child"] == "adopted"


def test_delete_child_agent_archives_registry_and_removes_tree_node(tmp_path):
    organization_store = _organization_store(tmp_path)
    organization_store.save_active_organization(_tree(revision=1))
    registry_store = _registry_store(tmp_path)
    registry_store.save_records({"legacy_worker": _worker("legacy_worker")})
    execution_store = _store(tmp_path)
    proposal = _proposal(
        proposal_id="proposal_delete",
        proposal_type="delete_child_agent",
        target_node_ids=["legacy_worker_node"],
        affected_worker_ids=["legacy_worker"],
    )
    state = _begin(tmp_path, proposal)
    plan = ControlledEvolutionPlan(
        proposal=proposal,
        operation=ControlledEvolutionOperation.DELETE_CHILD_AGENT,
        expected_tree_revision=1,
        org_node_ids_to_remove=("legacy_worker_node",),
        worker_lifecycle_updates={"legacy_worker": WorkerLifecycleStatus.ARCHIVED},
        chat_binding_updates={"legacy_worker_node": "closed"},
        asset_disposition_markers={"legacy_worker_node": "archived"},
    )

    apply_approved_evolution_plan(
        plan,
        state=state,
        actor="executor",
        now=NOW,
        organization_store=organization_store,
        registry_store=registry_store,
        execution_store=execution_store,
    )

    tree = organization_store.load_active_organization()
    assert "legacy_worker_node" not in tree.nodes
    assert "legacy_worker_node" not in tree.nodes["platform"].child_ids
    assert registry_store.load_records()["legacy_worker"].status is WorkerLifecycleStatus.ARCHIVED


def test_merge_department_archives_source_and_migrates_members(tmp_path):
    organization_store = _organization_store(tmp_path)
    base_tree = _tree(revision=1)
    nodes = dict(base_tree.nodes)
    nodes["design"] = _node(
        "design",
        "Design",
        OrgNodeType.DEPARTMENT,
        parent_id="root",
        worker_id="design_worker",
    )
    organization_store.save_active_organization(
        OrgTree(tree_id="default", root_node_id="root", nodes=nodes, revision=1)
    )
    registry_store = _registry_store(tmp_path)
    registry_store.save_records({"design_worker": _worker("design_worker")})
    execution_store = _store(tmp_path)
    proposal = _proposal(
        proposal_id="proposal_merge",
        proposal_type="merge_department",
        target_node_ids=["design", "platform"],
        affected_worker_ids=["design_worker"],
    )
    state = _begin(tmp_path, proposal)
    plan = ControlledEvolutionPlan(
        proposal=proposal,
        operation=ControlledEvolutionOperation.MERGE_DEPARTMENT,
        expected_tree_revision=1,
        merge_source_node_ids=("design",),
        merge_target_node_id="platform",
        chat_binding_updates={"design": "archived"},
        asset_disposition_markers={"design": "merged"},
    )

    apply_approved_evolution_plan(
        plan,
        state=state,
        actor="executor",
        now=NOW,
        organization_store=organization_store,
        registry_store=registry_store,
        execution_store=execution_store,
    )

    tree = organization_store.load_active_organization()
    assert tree.nodes["design"].lifecycle is OrgLifecycleState.ARCHIVED
    assert "design_worker" in tree.nodes["platform"].member_worker_ids


def test_archive_org_node_marks_node_archived(tmp_path):
    organization_store = _organization_store(tmp_path)
    organization_store.save_active_organization(_tree(revision=1))
    registry_store = _registry_store(tmp_path)
    registry_store.save_records({})
    execution_store = _store(tmp_path)
    proposal = _proposal(
        proposal_id="proposal_archive",
        proposal_type="archive_org_node",
        target_node_ids=["design"],
        affected_worker_ids=[],
    )
    state = _begin(tmp_path, proposal)
    archived_design = _node(
        "design",
        "Design",
        OrgNodeType.DEPARTMENT,
        parent_id="root",
        lifecycle=OrgLifecycleState.ARCHIVED,
    )
    plan = ControlledEvolutionPlan(
        proposal=proposal,
        operation=ControlledEvolutionOperation.ARCHIVE_ORG_NODE,
        expected_tree_revision=1,
        org_nodes_to_write=(archived_design,),
        chat_binding_updates={"design": "archived"},
        asset_disposition_markers={"design": "archived"},
    )

    apply_approved_evolution_plan(
        plan,
        state=state,
        actor="executor",
        now=NOW,
        organization_store=organization_store,
        registry_store=registry_store,
        execution_store=execution_store,
    )

    assert organization_store.load_active_organization().nodes["design"].lifecycle is OrgLifecycleState.ARCHIVED


def test_partial_failure_preserves_completed_steps(tmp_path):
    organization_store = _organization_store(tmp_path)
    organization_store.save_active_organization(_tree(revision=1))
    registry_store = _registry_store(tmp_path)
    registry_store.save_records({"legacy_worker": _worker("legacy_worker")})
    execution_store = _store(tmp_path)
    proposal = _proposal(
        proposal_id="proposal_delete",
        proposal_type="delete_child_agent",
        target_node_ids=["platform"],
        affected_worker_ids=["legacy_worker"],
    )
    state = _begin(tmp_path, proposal)
    plan = ControlledEvolutionPlan(
        proposal=proposal,
        operation=ControlledEvolutionOperation.DELETE_CHILD_AGENT,
        expected_tree_revision=1,
        org_node_ids_to_remove=("platform",),
        worker_lifecycle_updates={"legacy_worker": WorkerLifecycleStatus.ARCHIVED},
    )

    with pytest.raises(OrganizationEvolutionError, match="children"):
        apply_approved_evolution_plan(
            plan,
            state=state,
            actor="executor",
            now=NOW,
            organization_store=organization_store,
            registry_store=registry_store,
            execution_store=execution_store,
        )

    failed_state = execution_store.load_state(state.execution_id)
    assert failed_state.completed_steps == (
        EvolutionExecutionStep.REGISTRY_PRECHECK,
        EvolutionExecutionStep.REGISTRY_LIFECYCLE_UPDATE,
    )
    assert failed_state.failed_step is EvolutionExecutionStep.ORGANIZATION_TREE_UPDATE

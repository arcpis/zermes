import pytest

from worker_agents.organization import (
    OrgLifecycleState,
    OrgLeaderKind,
    OrgLeaderRef,
    OrgNode,
    OrgNodeType,
    OrgTree,
    OrganizationError,
    validate_org_tree_references,
)
from worker_agents.registry import WorkerLifecycleStatus, WorkerRegistryRecord


def _tree_with_worker_refs():
    root = OrgNode(
        org_node_id="root",
        name="Zermes",
        node_type=OrgNodeType.ROOT,
        child_ids=("engineering",),
        leader=OrgLeaderRef(kind=OrgLeaderKind.MAIN_AGENT),
        lifecycle=OrgLifecycleState.ACTIVE,
    )
    engineering = OrgNode(
        org_node_id="engineering",
        name="Engineering",
        node_type=OrgNodeType.DEPARTMENT,
        parent_id="root",
        child_ids=("frontend_lead_node",),
        leader=OrgLeaderRef(kind=OrgLeaderKind.WORKER, worker_id="engineering_lead"),
        member_worker_ids=("engineering_lead", "frontend_lead"),
        lifecycle=OrgLifecycleState.ACTIVE,
    )
    frontend_lead = OrgNode(
        org_node_id="frontend_lead_node",
        name="Frontend lead",
        node_type=OrgNodeType.INDIVIDUAL,
        parent_id="engineering",
        individual_worker_id="frontend_lead",
        lifecycle=OrgLifecycleState.ACTIVE,
    )
    return OrgTree(
        tree_id="default",
        root_node_id="root",
        nodes={
            "root": root,
            "engineering": engineering,
            "frontend_lead_node": frontend_lead,
        },
    )


def test_org_reference_validation_accepts_worker_id_sets():
    validate_org_tree_references(
        _tree_with_worker_refs(),
        {"engineering_lead", "frontend_lead"},
    )


def test_org_reference_validation_accepts_registry_records():
    validate_org_tree_references(
        _tree_with_worker_refs(),
        {
            "engineering_lead": WorkerRegistryRecord(
                worker_id="engineering_lead",
                display_name="Engineering lead",
                role="engineering",
                runtime_type="internal",
                status=WorkerLifecycleStatus.ENABLED,
            ),
            "frontend_lead": WorkerRegistryRecord(
                worker_id="frontend_lead",
                display_name="Frontend lead",
                role="frontend",
                runtime_type="internal",
                status=WorkerLifecycleStatus.REGISTERED,
            ),
        },
    )


def test_org_reference_validation_accepts_callable_lookup():
    records = {
        "engineering_lead": {"status": "enabled"},
        "frontend_lead": {"status": "disabled"},
    }

    validate_org_tree_references(_tree_with_worker_refs(), records.get)


def test_org_reference_validation_rejects_missing_leader_worker():
    with pytest.raises(OrganizationError, match="leader.worker_id"):
        validate_org_tree_references(_tree_with_worker_refs(), {"frontend_lead"})


def test_org_reference_validation_rejects_missing_member_worker():
    with pytest.raises(OrganizationError, match="member_worker_ids"):
        validate_org_tree_references(_tree_with_worker_refs(), {"engineering_lead"})


def test_org_reference_validation_rejects_missing_individual_worker():
    root = OrgNode(
        org_node_id="root",
        name="Zermes",
        node_type=OrgNodeType.ROOT,
        child_ids=("frontend_lead_node",),
        lifecycle=OrgLifecycleState.ACTIVE,
    )
    frontend_lead = OrgNode(
        org_node_id="frontend_lead_node",
        name="Frontend lead",
        node_type=OrgNodeType.INDIVIDUAL,
        parent_id="root",
        individual_worker_id="frontend_lead",
        lifecycle=OrgLifecycleState.ACTIVE,
    )
    tree = OrgTree(
        tree_id="default",
        root_node_id="root",
        nodes={"root": root, "frontend_lead_node": frontend_lead},
    )

    with pytest.raises(OrganizationError, match="individual_worker_id"):
        validate_org_tree_references(tree, set())


@pytest.mark.parametrize(
    "status",
    [WorkerLifecycleStatus.ARCHIVED, WorkerLifecycleStatus.DELETED],
)
def test_org_reference_validation_rejects_unavailable_worker_statuses(status):
    with pytest.raises(OrganizationError, match="unavailable worker"):
        validate_org_tree_references(
            _tree_with_worker_refs(),
            {
                "engineering_lead": WorkerLifecycleStatus.ENABLED,
                "frontend_lead": status,
            },
        )


def test_org_reference_validation_does_not_require_main_agent_in_registry():
    root_only = OrgNode(
        org_node_id="root",
        name="Zermes",
        node_type=OrgNodeType.ROOT,
        leader=OrgLeaderRef(kind=OrgLeaderKind.MAIN_AGENT),
        lifecycle=OrgLifecycleState.ACTIVE,
    )
    tree = OrgTree(tree_id="default", root_node_id="root", nodes={"root": root_only})

    validate_org_tree_references(tree, set())


def test_org_reference_validation_rejects_duplicate_individual_workers_under_parent():
    root = OrgNode(
        org_node_id="root",
        name="Zermes",
        node_type=OrgNodeType.ROOT,
        child_ids=("node_a", "node_b"),
        lifecycle=OrgLifecycleState.ACTIVE,
    )
    node_a = OrgNode(
        org_node_id="node_a",
        name="Frontend A",
        node_type=OrgNodeType.INDIVIDUAL,
        parent_id="root",
        individual_worker_id="frontend",
        lifecycle=OrgLifecycleState.ACTIVE,
    )
    node_b = OrgNode(
        org_node_id="node_b",
        name="Frontend B",
        node_type=OrgNodeType.INDIVIDUAL,
        parent_id="root",
        individual_worker_id="frontend",
        lifecycle=OrgLifecycleState.ACTIVE,
    )
    tree = OrgTree(
        tree_id="default",
        root_node_id="root",
        nodes={"root": root, "node_a": node_a, "node_b": node_b},
    )

    with pytest.raises(OrganizationError, match="more than once"):
        validate_org_tree_references(tree, {"frontend"})

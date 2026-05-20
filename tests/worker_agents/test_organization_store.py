import pytest

from worker_agents.organization import (
    OrgLifecycleState,
    OrgLeaderKind,
    OrgLeaderRef,
    OrgNode,
    OrgNodeType,
    OrgTree,
    OrganizationError,
)
from worker_agents.storage.organization_store import OrganizationStore


def _node(
    node_id,
    name,
    node_type,
    *,
    parent_id=None,
    child_ids=(),
    lifecycle=OrgLifecycleState.ACTIVE,
):
    kwargs = {}
    if node_type == OrgNodeType.INDIVIDUAL:
        kwargs["individual_worker_id"] = node_id
    return OrgNode(
        org_node_id=node_id,
        name=name,
        node_type=node_type,
        parent_id=parent_id,
        child_ids=child_ids,
        lifecycle=lifecycle,
        **kwargs,
    )


def _valid_tree(*, revision=1):
    root = OrgNode(
        org_node_id="root",
        name="Zermes",
        node_type=OrgNodeType.ROOT,
        child_ids=("engineering",),
        leader=OrgLeaderRef(kind=OrgLeaderKind.MAIN_AGENT),
        lifecycle=OrgLifecycleState.ACTIVE,
    )
    engineering = _node(
        "engineering",
        "Engineering",
        OrgNodeType.DEPARTMENT,
        parent_id="root",
        child_ids=("frontend",),
    )
    frontend = _node(
        "frontend",
        "Frontend",
        OrgNodeType.TEAM,
        parent_id="engineering",
        child_ids=("web_frontend",),
    )
    web_frontend = _node(
        "web_frontend", "Web Frontend", OrgNodeType.INDIVIDUAL, parent_id="frontend"
    )
    nodes = {
        node.org_node_id: node
        for node in (root, engineering, frontend, web_frontend)
    }
    return OrgTree(
        tree_id="default",
        revision=revision,
        root_node_id="root",
        nodes=nodes,
        created_at="2026-05-20T00:00:00Z",
        updated_at="2026-05-20T01:00:00Z",
    )


def test_active_organization_missing_loads_as_none(tmp_path):
    store = OrganizationStore(tmp_path / "worker_agents" / "organization")

    assert store.load_active_organization() is None
    assert not store.active_path.exists()


def test_active_organization_round_trips(tmp_path):
    store = OrganizationStore(tmp_path / "worker_agents" / "organization")
    tree = _valid_tree(revision=1)

    path = store.save_active_organization(tree)

    assert path == store.active_path
    assert store.load_active_organization() == tree


def test_active_organization_preserves_existing_file_on_invalid_json(tmp_path):
    store = OrganizationStore(tmp_path / "worker_agents" / "organization")
    original = _valid_tree(revision=1)
    store.save_active_organization(original)

    with pytest.raises(OrganizationError, match="Invalid organization tree JSON"):
        store.active_path.write_text("{bad json", encoding="utf-8")
        store.load_active_organization()


def test_active_organization_invalid_save_does_not_overwrite(tmp_path):
    store = OrganizationStore(tmp_path / "worker_agents" / "organization")
    original = _valid_tree(revision=1)
    store.save_active_organization(original)
    invalid = _valid_tree(revision=2)
    invalid.nodes["orphan"] = _node("orphan", "Orphan", OrgNodeType.TEAM)

    with pytest.raises(OrganizationError, match="parent_id"):
        store.save_active_organization(invalid, expected_revision=1)

    assert store.load_active_organization() == original


def test_active_organization_revision_conflict_does_not_overwrite(tmp_path):
    store = OrganizationStore(tmp_path / "worker_agents" / "organization")
    original = _valid_tree(revision=1)
    store.save_active_organization(original)

    with pytest.raises(OrganizationError, match="revision conflict"):
        store.save_active_organization(_valid_tree(revision=2), expected_revision=0)

    assert store.load_active_organization() == original


def test_active_organization_expected_revision_must_advance(tmp_path):
    store = OrganizationStore(tmp_path / "worker_agents" / "organization")
    original = _valid_tree(revision=1)
    store.save_active_organization(original)

    with pytest.raises(OrganizationError, match="must advance"):
        store.save_active_organization(_valid_tree(revision=1), expected_revision=1)

    assert store.load_active_organization() == original

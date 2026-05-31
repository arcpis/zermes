import pytest

from worker_agents.organization import (
    ORGANIZATION_SCHEMA_VERSION,
    OrgChatPolicy,
    OrgLifecycleState,
    OrgLeaderKind,
    OrgLeaderRef,
    OrgNode,
    OrgNodeType,
    OrgTree,
    OrganizationError,
    dump_org_tree_json,
    load_org_tree_json,
    org_tree_from_dict,
    org_tree_to_dict,
)


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


def _valid_tree():
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
        child_ids=("frontend", "backend"),
    )
    frontend = _node(
        "frontend",
        "Frontend",
        OrgNodeType.TEAM,
        parent_id="engineering",
        child_ids=("web_frontend",),
    )
    backend = _node("backend", "Backend", OrgNodeType.TEAM, parent_id="engineering")
    web_frontend = _node(
        "web_frontend", "Web Frontend", OrgNodeType.INDIVIDUAL, parent_id="frontend"
    )
    nodes = {
        node.org_node_id: node
        for node in (root, engineering, frontend, backend, web_frontend)
    }
    return OrgTree(
        tree_id="default",
        revision=3,
        root_node_id="root",
        nodes=nodes,
        created_at="2026-05-20T00:00:00Z",
        updated_at="2026-05-20T01:00:00Z",
    )


def test_org_tree_round_trips_through_json():
    tree = _valid_tree()

    loaded = load_org_tree_json(dump_org_tree_json(tree))

    assert loaded == tree


def test_org_tree_dict_output_is_stable():
    tree = _valid_tree()

    data = org_tree_to_dict(tree)

    assert list(data) == [
        "tree_id",
        "schema_version",
        "revision",
        "root_node_id",
        "nodes",
        "created_at",
        "updated_at",
        "metadata",
    ]
    assert data["schema_version"] == ORGANIZATION_SCHEMA_VERSION
    assert data["revision"] == 3
    assert list(data["nodes"]) == sorted(data["nodes"])


def test_org_tree_rejects_missing_root_reference():
    tree = _valid_tree()

    with pytest.raises(OrganizationError, match="root_node_id"):
        OrgTree(
            tree_id="default",
            root_node_id="missing",
            nodes=tree.nodes,
        )


def test_org_tree_rejects_multiple_root_nodes():
    tree = _valid_tree()
    extra_root = OrgNode(
        org_node_id="other_root",
        name="Other",
        node_type=OrgNodeType.ROOT,
        lifecycle=OrgLifecycleState.ACTIVE,
    )

    with pytest.raises(OrganizationError, match="exactly one root"):
        OrgTree(
            tree_id="default",
            root_node_id="root",
            nodes={**tree.nodes, extra_root.org_node_id: extra_root},
        )


def test_org_tree_rejects_missing_parent():
    tree = _valid_tree()
    orphan = _node("orphan", "Orphan", OrgNodeType.TEAM)

    with pytest.raises(OrganizationError, match="parent_id"):
        OrgTree(
            tree_id="default",
            root_node_id="root",
            nodes={**tree.nodes, orphan.org_node_id: orphan},
        )


def test_org_tree_rejects_mismatched_child_links():
    tree = _valid_tree()
    changed = dict(tree.nodes)
    changed["frontend"] = _node(
        "frontend",
        "Frontend",
        OrgNodeType.TEAM,
        parent_id="engineering",
    )

    with pytest.raises(OrganizationError, match="child_ids"):
        OrgTree(tree_id="default", root_node_id="root", nodes=changed)


def test_org_tree_rejects_cycles():
    root = OrgNode(
        org_node_id="root",
        name="Zermes",
        node_type=OrgNodeType.ROOT,
        child_ids=("team",),
        lifecycle=OrgLifecycleState.ACTIVE,
    )
    team = _node(
        "team",
        "Team",
        OrgNodeType.TEAM,
        parent_id="worker",
        child_ids=("worker",),
    )
    worker = _node(
        "worker",
        "Worker",
        OrgNodeType.INDIVIDUAL,
        parent_id="team",
        child_ids=("team",),
    )

    with pytest.raises(OrganizationError, match="cycle|parent"):
        OrgTree(
            tree_id="default",
            root_node_id="root",
            nodes={"root": root, "team": team, "worker": worker},
        )


def test_org_tree_rejects_duplicate_sibling_names():
    root = OrgNode(
        org_node_id="root",
        name="Zermes",
        node_type=OrgNodeType.ROOT,
        child_ids=("team_a", "team_b"),
        lifecycle=OrgLifecycleState.ACTIVE,
    )
    team_a = _node("team_a", "Frontend", OrgNodeType.TEAM, parent_id="root")
    team_b = _node("team_b", "Frontend", OrgNodeType.TEAM, parent_id="root")

    with pytest.raises(OrganizationError, match="unique names"):
        OrgTree(
            tree_id="default",
            root_node_id="root",
            nodes={"root": root, "team_a": team_a, "team_b": team_b},
        )


def test_archived_nodes_cannot_be_default_chat_targets():
    root = OrgNode(
        org_node_id="root",
        name="Zermes",
        node_type=OrgNodeType.ROOT,
        child_ids=("old_team",),
        lifecycle=OrgLifecycleState.ACTIVE,
    )
    old_team = OrgNode(
        org_node_id="old_team",
        name="Old team",
        node_type=OrgNodeType.TEAM,
        parent_id="root",
        lifecycle=OrgLifecycleState.ARCHIVED,
        chat_policy=OrgChatPolicy(
            default_thread_policy="department_default",
            allow_default_group_chat=True,
        ),
    )

    with pytest.raises(OrganizationError, match="archived"):
        OrgTree(
            tree_id="default",
            root_node_id="root",
            nodes={"root": root, "old_team": old_team},
        )


def test_org_tree_from_dict_rejects_unknown_fields():
    with pytest.raises(OrganizationError, match="unknown fields"):
        org_tree_from_dict(
            {
                "tree_id": "default",
                "schema_version": ORGANIZATION_SCHEMA_VERSION,
                "revision": 0,
                "root_node_id": "root",
                "nodes": {},
                "raw_transcript": "nope",
            }
        )

from worker_agents.organization import (
    OrgLifecycleState,
    OrgLeaderKind,
    OrgLeaderRef,
    OrgNode,
    OrgNodeType,
    OrgTree,
    org_node_summary_to_dict,
    org_tree_summary_to_dict,
    summarize_org_node,
    summarize_org_tree,
)


def _summary_tree():
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
        description="Builds and operates product systems.",
        applicable_task_types=("implementation", "review"),
        parent_id="root",
        child_ids=("frontend", "archived_team"),
        leader=OrgLeaderRef(kind=OrgLeaderKind.WORKER, worker_id="engineering_lead"),
        member_worker_ids=("engineering_lead",),
        lifecycle=OrgLifecycleState.ACTIVE,
    )
    frontend = OrgNode(
        org_node_id="frontend",
        name="Frontend",
        node_type=OrgNodeType.TEAM,
        parent_id="engineering",
        child_ids=("web_frontend",),
        lifecycle=OrgLifecycleState.ACTIVE,
    )
    web_frontend = OrgNode(
        org_node_id="web_frontend",
        name="Web Frontend",
        node_type=OrgNodeType.INDIVIDUAL,
        parent_id="frontend",
        individual_worker_id="web_frontend",
        lifecycle=OrgLifecycleState.ACTIVE,
    )
    archived_team = OrgNode(
        org_node_id="archived_team",
        name="Archived Team",
        node_type=OrgNodeType.TEAM,
        parent_id="engineering",
        lifecycle=OrgLifecycleState.ARCHIVED,
    )
    return OrgTree(
        tree_id="default",
        revision=5,
        root_node_id="root",
        nodes={
            node.org_node_id: node
            for node in (
                root,
                engineering,
                frontend,
                web_frontend,
                archived_team,
            )
        },
    )


def test_org_node_summary_contains_low_sensitivity_fields():
    node = _summary_tree().nodes["engineering"]

    summary = summarize_org_node(node)
    data = org_node_summary_to_dict(summary)

    assert data == {
        "org_node_id": "engineering",
        "name": "Engineering",
        "node_type": "department",
        "lifecycle": "active",
        "parent_id": "root",
        "child_count": 2,
        "member_count": 1,
        "leader_kind": "worker",
        "leader_worker_id": "engineering_lead",
        "responsibility_summary": "Builds and operates product systems.",
        "applicable_task_types": ["implementation", "review"],
    }


def test_org_tree_summary_counts_active_nodes_and_node_types():
    summary = summarize_org_tree(_summary_tree())
    data = org_tree_summary_to_dict(summary)

    assert data["tree_id"] == "default"
    assert data["revision"] == 5
    assert data["root_node_id"] == "root"
    assert data["active_node_count"] == 4
    assert data["department_count"] == 1
    assert data["team_count"] == 2
    assert data["individual_count"] == 1
    assert [node["org_node_id"] for node in data["node_summaries"]] == sorted(
        node["org_node_id"] for node in data["node_summaries"]
    )


def test_org_summary_excludes_private_profile_and_runtime_details():
    data = org_tree_summary_to_dict(summarize_org_tree(_summary_tree()))
    text = repr(data)

    assert "profile" not in text
    assert "private_memory" not in text
    assert "skill" not in text
    assert "credential" not in text
    assert "transcript" not in text
    assert "runtime" not in text

import pytest

from worker_agents.organization import (
    ORGANIZATION_SCHEMA_VERSION,
    OrgLeaderKind,
    OrgLeaderRef,
    OrgNode,
    OrgNodeType,
    OrganizationError,
    dump_org_node_json,
    load_org_node_json,
    org_node_from_dict,
    org_node_to_dict,
)


def test_org_node_round_trips_through_json():
    node = OrgNode(
        org_node_id="frontend",
        name="Frontend",
        node_type=OrgNodeType.TEAM,
        description="Builds user interfaces.",
        responsibilities=("web", "app"),
        applicable_task_types=("implementation",),
        parent_id="engineering",
        child_ids=("web_frontend",),
        leader=OrgLeaderRef(kind=OrgLeaderKind.WORKER, worker_id="lead_frontend"),
        member_worker_ids=("lead_frontend", "web_frontend"),
    )

    loaded = load_org_node_json(dump_org_node_json(node))

    assert loaded == node


@pytest.mark.parametrize("node_type", list(OrgNodeType))
def test_org_node_accepts_supported_node_types(node_type):
    kwargs = {}
    if node_type == OrgNodeType.INDIVIDUAL:
        kwargs["individual_worker_id"] = "researcher"

    node = OrgNode(
        org_node_id=f"{node_type.value}_node",
        name=node_type.value.title(),
        node_type=node_type,
        **kwargs,
    )

    assert node.node_type == node_type
    assert node.schema_version == ORGANIZATION_SCHEMA_VERSION


@pytest.mark.parametrize("org_node_id", ["", ".", "..", "team/frontend", r"team\frontend"])
def test_org_node_rejects_path_like_node_ids(org_node_id):
    with pytest.raises(OrganizationError):
        OrgNode(
            org_node_id=org_node_id,
            name="Frontend",
            node_type=OrgNodeType.TEAM,
        )


def test_org_node_rejects_unknown_fields():
    with pytest.raises(OrganizationError, match="unknown fields"):
        org_node_from_dict(
            {
                "org_node_id": "frontend",
                "schema_version": ORGANIZATION_SCHEMA_VERSION,
                "name": "Frontend",
                "node_type": "team",
                "private_memory": "do not store this here",
            }
        )


def test_org_node_rejects_unknown_schema_version():
    with pytest.raises(OrganizationError, match="schema_version"):
        OrgNode(
            org_node_id="frontend",
            schema_version=ORGANIZATION_SCHEMA_VERSION + 1,
            name="Frontend",
            node_type=OrgNodeType.TEAM,
        )


def test_org_node_supports_main_agent_and_empty_leaders():
    root = OrgNode(
        org_node_id="root",
        name="Zermes",
        node_type=OrgNodeType.ROOT,
        leader=OrgLeaderRef(kind=OrgLeaderKind.MAIN_AGENT),
    )
    unassigned = OrgNode(
        org_node_id="draft_team",
        name="Draft team",
        node_type=OrgNodeType.TEAM,
    )

    assert root.leader.kind == OrgLeaderKind.MAIN_AGENT
    assert unassigned.leader.kind == OrgLeaderKind.NONE


def test_worker_leader_requires_worker_id():
    with pytest.raises(OrganizationError, match="worker_id"):
        OrgLeaderRef(kind=OrgLeaderKind.WORKER)


def test_non_worker_leader_rejects_worker_id():
    with pytest.raises(OrganizationError, match="only valid"):
        OrgLeaderRef(kind=OrgLeaderKind.MAIN_AGENT, worker_id="researcher")


def test_individual_node_requires_worker_reference():
    with pytest.raises(OrganizationError, match="individual_worker_id"):
        OrgNode(
            org_node_id="researcher_node",
            name="Researcher",
            node_type=OrgNodeType.INDIVIDUAL,
        )


def test_node_dict_does_not_embed_profile_or_private_assets():
    node = OrgNode(
        org_node_id="researcher_node",
        name="Researcher",
        node_type=OrgNodeType.INDIVIDUAL,
        individual_worker_id="researcher",
        member_worker_ids=("researcher",),
    )

    data = org_node_to_dict(node)

    assert data["individual_worker_id"] == "researcher"
    assert data["member_worker_ids"] == ["researcher"]
    assert "profile" not in data
    assert "memory" not in data
    assert "skills" not in data
    assert "tools" not in data

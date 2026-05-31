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
from worker_agents.storage.organization_store import (
    OrganizationHistorySummary,
    OrganizationProposalStatus,
    OrganizationProposalSummary,
    OrganizationStore,
    organization_history_summary_from_dict,
    organization_proposal_summary_from_dict,
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


def test_proposal_summary_round_trips_and_lists_without_touching_active(tmp_path):
    store = OrganizationStore(tmp_path / "worker_agents" / "organization")
    proposal = OrganizationProposalSummary(
        proposal_id="proposal-1",
        created_at="2026-05-20T02:00:00Z",
        updated_at="2026-05-20T02:05:00Z",
        submitted_by="zermes_main_agent",
        target_node_id="engineering",
        summary="Move frontend coordination under Engineering.",
        status=OrganizationProposalStatus.PROPOSED,
    )

    path = store.save_proposal_summary(proposal)

    assert path == store.proposals_dir / "proposal-1.json"
    assert store.load_proposal_summary("proposal-1") == proposal
    assert store.list_proposal_summaries() == [proposal]
    assert not store.active_path.exists()


def test_history_summary_round_trips_and_lists(tmp_path):
    store = OrganizationStore(tmp_path / "worker_agents" / "organization")
    history = OrganizationHistorySummary(
        change_id="change-1",
        created_at="2026-05-20T03:00:00Z",
        actor="zermes_main_agent",
        affected_node_ids=("engineering", "frontend"),
        previous_revision=1,
        new_revision=2,
        summary="Accepted frontend reporting structure update.",
    )

    path = store.save_history_summary(history)

    assert path == store.history_dir / "change-1.json"
    assert store.load_history_summary("change-1") == history
    assert store.list_history_summaries() == [history]


def test_summary_ids_reject_path_traversal(tmp_path):
    store = OrganizationStore(tmp_path / "worker_agents" / "organization")

    with pytest.raises(ValueError, match="single proposal id"):
        store.proposal_summary_path("../outside")
    with pytest.raises(ValueError, match="single change id"):
        store.history_summary_path("nested/change")


def test_summary_load_missing_raises_clear_error(tmp_path):
    store = OrganizationStore(tmp_path / "worker_agents" / "organization")

    with pytest.raises(OrganizationError, match="proposal does not exist"):
        store.load_proposal_summary("missing")
    with pytest.raises(OrganizationError, match="history does not exist"):
        store.load_history_summary("missing")


def test_proposal_summary_rejects_unknown_fields():
    with pytest.raises(OrganizationError, match="unknown fields"):
        organization_proposal_summary_from_dict(
            {
                "proposal_id": "proposal-1",
                "created_at": "2026-05-20T02:00:00Z",
                "submitted_by": "zermes_main_agent",
                "summary": "Looks useful.",
                "raw_transcript": "nope",
            }
        )


def test_history_summary_rejects_invalid_revision():
    with pytest.raises(OrganizationError, match="new_revision"):
        organization_history_summary_from_dict(
            {
                "change_id": "change-1",
                "created_at": "2026-05-20T03:00:00Z",
                "actor": "zermes_main_agent",
                "summary": "Changed org.",
                "new_revision": -1,
            }
        )

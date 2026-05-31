from worker_agents.management import (
    DashboardDataSources,
    DepartmentManagementSummary,
    OrganizationManagementNodeSummary,
    build_dashboard_snapshot,
    build_organization_tree_view,
    build_worker_management_list,
    dashboard_snapshot_to_dict,
    filter_worker_management_list,
    organization_tree_view_node_to_dict,
)
from worker_agents.organization import (
    OrgChatPolicy,
    OrgLeaderKind,
    OrgLeaderRef,
    OrgLifecycleState,
    OrgNode,
    OrgNodeType,
    OrgTree,
)
from worker_agents.registry import WorkerLifecycleStatus, WorkerRegistryRecord


def _worker(worker_id: str, **kwargs):
    return WorkerRegistryRecord(
        worker_id=worker_id,
        display_name=kwargs.get("display_name", worker_id.title()),
        role=kwargs.get("role", "developer"),
        runtime_type=kwargs.get("runtime_type", "internal"),
        status=kwargs.get("status", WorkerLifecycleStatus.ENABLED),
        updated_at="2026-05-26T00:00:00Z",
        metadata=kwargs.get("metadata", {}),
    )


def test_dashboard_snapshot_serializes_stable_low_sensitive_data():
    snapshot = build_dashboard_snapshot(
        DashboardDataSources(
            worker_records={
                "worker-a": _worker(
                    "worker-a",
                    metadata={
                        "department_ids": ["engineering"],
                        "api_key": "should-not-render",
                        "public_note": "release support",
                    },
                )
            },
            department_summaries=[
                {
                    "department_id": "engineering",
                    "display_name": "Engineering",
                    "member_count": 1,
                    "default_chat_available": True,
                    "public_metadata": {"raw_transcript": "hidden", "summary": "ok"},
                }
            ],
            source_revision="rev-1",
            source_updated_at="2026-05-26T00:00:00Z",
        )
    )

    data = dashboard_snapshot_to_dict(snapshot)

    assert data["source_ref"]["revision"] == "rev-1"
    assert data["workers"][0]["department_ids"] == ["engineering"]
    assert data["workers"][0]["public_metadata"] == {
        "department_ids": ["engineering"],
        "public_note": "release support",
    }
    assert data["departments"][0]["default_chat_available"] is False
    assert data["departments"][0]["collaboration_mode"] == "private_or_parent_chat"
    assert data["departments"][0]["public_metadata"] == {"summary": "ok"}


def test_dashboard_reports_missing_worker_references_as_warnings():
    tree = OrgTree(
        tree_id="active",
        root_node_id="root",
        revision=7,
        nodes={
            "root": OrgNode(
                org_node_id="root",
                name="Root",
                node_type=OrgNodeType.ROOT,
                child_ids=("engineering",),
                lifecycle=OrgLifecycleState.ACTIVE,
            ),
            "engineering": OrgNode(
                org_node_id="engineering",
                name="Engineering",
                node_type=OrgNodeType.DEPARTMENT,
                parent_id="root",
                leader=OrgLeaderRef(
                    kind=OrgLeaderKind.WORKER,
                    worker_id="worker-a",
                ),
                member_worker_ids=("worker-a",),
                chat_policy=OrgChatPolicy(allow_default_group_chat=True),
                lifecycle=OrgLifecycleState.ACTIVE,
            ),
        },
    )

    snapshot = build_dashboard_snapshot(
        DashboardDataSources(
            worker_records={},
            organization_tree=tree,
        )
    )

    assert "missing worker 'worker-a'" in snapshot.warnings[0]
    assert any(badge.code == "missing_owner" for badge in snapshot.risk_badges)


def test_worker_management_list_filters_archived_and_risk_badges():
    snapshot = build_dashboard_snapshot(
        DashboardDataSources(
            worker_records={
                "active-worker": _worker("active-worker"),
                "archived-worker": _worker(
                    "archived-worker",
                    runtime_type="external",
                    status=WorkerLifecycleStatus.ARCHIVED,
                ),
            },
            health_summaries={"archived-worker": {"status": "unhealthy"}},
        )
    )
    rows = build_worker_management_list(snapshot)

    archived = filter_worker_management_list(rows, status="archived")
    risky = filter_worker_management_list(rows, risk_badge="external_unhealthy")

    assert [row.worker_id for row in archived] == ["archived-worker"]
    assert [row.worker_id for row in risky] == ["archived-worker"]
    assert set(risky[0].action_links) == {
        "view_approvals",
        "view_operations",
        "view_assets",
    }


def test_organization_tree_view_is_nested_and_marks_read_only_nodes():
    nodes = (
        OrganizationManagementNodeSummary(
            org_node_id="root",
            name="Root",
            node_type="root",
            lifecycle="active",
            parent_id=None,
            child_ids=("archived-dept",),
        ),
        OrganizationManagementNodeSummary(
            org_node_id="archived-dept",
            name="Archived",
            node_type="department",
            lifecycle="archived",
            parent_id="root",
            read_only=True,
        ),
    )

    view = build_organization_tree_view(nodes)
    data = organization_tree_view_node_to_dict(view[0])

    assert data["children"][0]["summary"]["org_node_id"] == "archived-dept"
    assert data["children"][0]["summary"]["read_only"] is True
    assert data["children"][0]["warnings"] == [
        "organization node 'archived-dept' is read-only"
    ]


def test_department_summary_dataclass_filters_private_metadata():
    summary = DepartmentManagementSummary(
        department_id="ops",
        display_name="Ops",
        public_metadata={"secret_token": "hidden", "summary": "visible"},
    )

    assert summary.public_metadata == {"summary": "visible"}

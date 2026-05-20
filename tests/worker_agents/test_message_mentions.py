from worker_agents.message_mentions import (
    MentionResolutionStatus,
    MentionTarget,
    MentionTargetKind,
    resolve_mention_targets,
)
from worker_agents.message_router import ChatParticipantKind
from worker_agents.organization import (
    OrgLeaderKind,
    OrgLeaderRef,
    OrgLifecycleState,
    OrgNode,
    OrgNodeType,
    OrgTree,
)
from worker_agents.registry import WorkerLifecycleStatus


def _organization_tree(*, duplicate_team_name: bool = False) -> OrgTree:
    team_name = "Platform"
    nodes = {
        "root": OrgNode(
            org_node_id="root",
            name="Root",
            node_type=OrgNodeType.ROOT,
            child_ids=("engineering", "ops"),
            leader=OrgLeaderRef(OrgLeaderKind.MAIN_AGENT),
            lifecycle=OrgLifecycleState.ACTIVE,
        ),
        "engineering": OrgNode(
            org_node_id="engineering",
            name="Engineering",
            node_type=OrgNodeType.DEPARTMENT,
            parent_id="root",
            child_ids=("platform",),
            leader=OrgLeaderRef(OrgLeaderKind.WORKER, "eng_lead"),
            lifecycle=OrgLifecycleState.ACTIVE,
        ),
        "platform": OrgNode(
            org_node_id="platform",
            name=team_name,
            node_type=OrgNodeType.TEAM,
            parent_id="engineering",
            leader=OrgLeaderRef(OrgLeaderKind.WORKER, "platform_lead"),
            lifecycle=OrgLifecycleState.ACTIVE,
        ),
        "ops": OrgNode(
            org_node_id="ops",
            name=team_name if duplicate_team_name else "Operations",
            node_type=OrgNodeType.DEPARTMENT,
            parent_id="root",
            leader=OrgLeaderRef(),
            lifecycle=OrgLifecycleState.ACTIVE,
        ),
    }
    return OrgTree(tree_id="company", root_node_id="root", nodes=nodes)


def test_resolves_worker_target_with_enabled_registry_record():
    resolved = resolve_mention_targets(
        ("@frontend",),
        worker_lookup={"frontend": {"status": WorkerLifecycleStatus.ENABLED.value}},
    )

    assert resolved[0].status == MentionResolutionStatus.RESOLVED
    assert resolved[0].recipient_ref is not None
    assert resolved[0].recipient_ref.kind == ChatParticipantKind.WORKER
    assert resolved[0].recipient_ref.participant_id == "frontend"


def test_archived_worker_target_is_inactive():
    resolved = resolve_mention_targets(
        ("frontend",),
        worker_lookup={"frontend": WorkerLifecycleStatus.ARCHIVED},
    )

    assert resolved[0].status == MentionResolutionStatus.INACTIVE
    assert resolved[0].failure_reason == "worker is archived or deleted"


def test_resolves_department_to_worker_leader():
    resolved = resolve_mention_targets(
        (MentionTarget("Engineering", MentionTargetKind.DEPARTMENT),),
        organization_tree=_organization_tree(),
    )

    assert resolved[0].status == MentionResolutionStatus.RESOLVED
    assert resolved[0].mentioned_ref is not None
    assert resolved[0].mentioned_ref.participant_id == "engineering"
    assert resolved[0].recipient_ref is not None
    assert resolved[0].recipient_ref.participant_id == "eng_lead"
    assert resolved[0].routed_via_org_node_id == "engineering"


def test_resolves_team_to_worker_leader_by_name():
    resolved = resolve_mention_targets(
        (MentionTarget("@Platform", MentionTargetKind.TEAM),),
        organization_tree=_organization_tree(),
    )

    assert resolved[0].status == MentionResolutionStatus.RESOLVED
    assert resolved[0].recipient_ref is not None
    assert resolved[0].recipient_ref.participant_id == "platform_lead"


def test_org_node_without_worker_leader_reports_missing_owner():
    resolved = resolve_mention_targets(
        (MentionTarget("@Operations", MentionTargetKind.DEPARTMENT),),
        organization_tree=_organization_tree(),
    )

    assert resolved[0].status == MentionResolutionStatus.MISSING_OWNER
    assert "worker leader" in resolved[0].failure_reason


def test_duplicate_org_labels_report_ambiguous_result():
    resolved = resolve_mention_targets(
        ("@Platform",),
        organization_tree=_organization_tree(duplicate_team_name=True),
        worker_lookup=set(),
    )

    assert resolved[0].status == MentionResolutionStatus.AMBIGUOUS


def test_multi_target_resolution_keeps_successes_and_failures():
    resolved = resolve_mention_targets(
        ("@frontend", "@missing", MentionTarget("Engineering")),
        organization_tree=_organization_tree(),
        worker_lookup={"frontend": WorkerLifecycleStatus.ENABLED},
    )

    assert [item.status for item in resolved] == [
        MentionResolutionStatus.RESOLVED,
        MentionResolutionStatus.NOT_FOUND,
        MentionResolutionStatus.RESOLVED,
    ]


def test_invalid_target_is_reported_without_raising():
    resolved = resolve_mention_targets(("@bad/path",))

    assert resolved[0].status == MentionResolutionStatus.INVALID
    assert "path separators" in resolved[0].failure_reason

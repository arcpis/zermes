import pytest

from worker_agents.department_chats import (
    DepartmentChatError,
    DepartmentChatSummaryType,
    DepartmentProjectChat,
    department_chat_summary_to_dict,
    plan_department_chat_summary,
    plan_final_department_chat_archive_summary,
)
from worker_agents.organization import (
    OrgLeaderKind,
    OrgLeaderRef,
    OrgLifecycleState,
    OrgNode,
    OrgNodeType,
)


def _node(node_id, *, parent_id="root"):
    return OrgNode(
        org_node_id=node_id,
        name=node_id.title(),
        node_type=OrgNodeType.DEPARTMENT,
        parent_id=parent_id,
        leader=OrgLeaderRef(kind=OrgLeaderKind.WORKER, worker_id=f"{node_id}_lead"),
        member_worker_ids=(f"{node_id}_lead", f"{node_id}_member"),
        lifecycle=OrgLifecycleState.ACTIVE,
    )


def test_child_department_can_summarize_to_parent():
    summary = plan_department_chat_summary(
        summary_id="frontend-summary-1",
        source_node=_node("frontend", parent_id="engineering"),
        source_thread_id="frontend-thread",
        target_node=_node("engineering", parent_id="root"),
        target_thread_id="engineering-thread",
        summary_type=DepartmentChatSummaryType.DECISION,
        body="Frontend chose the router boundary and will deliver a patch.",
        manifest_refs=("manifest-1",),
        audit_refs=("audit-1",),
    )

    data = department_chat_summary_to_dict(summary)

    assert data["source_org_node_id"] == "frontend"
    assert data["target_org_node_id"] == "engineering"
    assert data["manifest_refs"] == ["manifest-1"]
    assert "transcript" not in data
    assert "private_memory" not in data


def test_non_parent_summary_requires_project_marker():
    with pytest.raises(DepartmentChatError, match="project summaries"):
        plan_department_chat_summary(
            summary_id="frontend-backend-summary",
            source_node=_node("frontend", parent_id="engineering"),
            source_thread_id="frontend-thread",
            target_node=_node("design", parent_id="root"),
            target_thread_id="design-thread",
            summary_type=DepartmentChatSummaryType.HANDOFF,
            body="Frontend needs a design handoff.",
        )


def test_project_summary_allows_cross_department_target():
    summary = plan_department_chat_summary(
        summary_id="project-summary",
        source_node=_node("frontend", parent_id="engineering"),
        source_thread_id="project-thread",
        target_node=_node("design", parent_id="root"),
        target_thread_id="design-thread",
        summary_type=DepartmentChatSummaryType.DELIVERABLE,
        body="Project shared a low-sensitivity deliverable summary.",
        is_project_summary=True,
    )

    assert summary.is_project_summary is True


@pytest.mark.parametrize(
    "body",
    [
        "raw_transcript: full chat goes here",
        "private_memory should not move upward",
        "credentials are forbidden",
        "environment variables are forbidden",
        "external_agent_raw_output must stay out",
    ],
)
def test_summary_body_rejects_sensitive_markers(body):
    with pytest.raises(DepartmentChatError):
        plan_department_chat_summary(
            summary_id="bad-summary",
            source_node=_node("frontend", parent_id="engineering"),
            source_thread_id="frontend-thread",
            target_node=_node("engineering", parent_id="root"),
            target_thread_id="engineering-thread",
            summary_type=DepartmentChatSummaryType.RISK,
            body=body,
        )


def test_final_archive_summary_records_close_reason_and_replacement():
    summary = plan_final_department_chat_archive_summary(
        summary_id="frontend-final",
        source_node=_node("frontend", parent_id="engineering"),
        source_thread_id="frontend-thread",
        target_node=_node("engineering", parent_id="root"),
        target_thread_id="engineering-thread",
        close_reason="team merged into engineering",
        replacement_thread_id="engineering-thread",
        audit_refs=("close-audit",),
    )

    assert summary.summary_type == DepartmentChatSummaryType.FINAL_ARCHIVE
    assert "team merged into engineering" in summary.body
    assert summary.audit_refs == ("close-audit",)


def test_project_chat_keeps_minimal_structure_only():
    project = DepartmentProjectChat(
        project_id="launch-project",
        thread_id="launch-thread",
        participant_org_node_ids=("frontend", "design"),
        summary_target_org_node_ids=("engineering",),
        deliverable_manifest_refs=("manifest-1",),
    )

    assert project.participant_org_node_ids == ("frontend", "design")
    assert project.deliverable_manifest_refs == ("manifest-1",)

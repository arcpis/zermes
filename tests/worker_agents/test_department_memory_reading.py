from worker_agents.department_memory import (
    DepartmentMemoryKind,
    DepartmentMemoryProposal,
    DepartmentMemoryProposalStore,
    DepartmentMemoryReadRequest,
    DepartmentMemoryReadService,
    DepartmentMemoryReviewAction,
    DepartmentMemoryReviewDecision,
    DepartmentMemoryReviewService,
    DepartmentMemoryReviewerRole,
    DepartmentMemorySensitivity,
    DepartmentMemoryVisibility,
    department_memory_read_result_to_dict,
)


def _approve_memory(
    tmp_path,
    *,
    department_id="platform",
    proposal_id="proposal-1",
    kind=DepartmentMemoryKind.DELIVERY_STANDARD,
    summary="Every handoff includes tests and known risks.",
    visibility=DepartmentMemoryVisibility.PRIVATE_TO_DEPARTMENT,
    sensitivity=DepartmentMemorySensitivity.INTERNAL,
    source_refs=("tasks/task_123/summary.json",),
):
    store = DepartmentMemoryProposalStore(root=tmp_path)
    proposal = DepartmentMemoryProposal(
        proposal_id=proposal_id,
        department_id=department_id,
        kind=kind,
        candidate_summary=summary,
        source_actor="frontend",
        source_refs=source_refs,
        visibility=visibility,
        sensitivity=sensitivity,
    )
    store.create_proposal(proposal)
    service = DepartmentMemoryReviewService(store)
    return service.approve(
        department_id,
        proposal_id,
        DepartmentMemoryReviewAction(
            proposal_id=proposal_id,
            decision=DepartmentMemoryReviewDecision.APPROVE,
            actor_id="lead-worker",
            actor_role=DepartmentMemoryReviewerRole.DEPARTMENT_LEAD,
            reason="Useful department memory.",
            reviewed_at="2026-05-21T01:00:00Z",
            user_confirmation_ref=(
                "approvals/user-confirmation-1.json"
                if sensitivity
                is DepartmentMemorySensitivity.USER_CONFIRMATION_REQUIRED
                else None
            ),
        ),
    )


def test_read_returns_redacted_views_for_active_memories(tmp_path):
    _approve_memory(tmp_path)
    service = DepartmentMemoryReadService(root=tmp_path)

    result = service.read(
        DepartmentMemoryReadRequest(
            department_id="platform",
            requester_scope="context_policy",
            kinds=(DepartmentMemoryKind.DELIVERY_STANDARD,),
        )
    )

    assert len(result.views) == 1
    assert result.views[0].redacted_summary == (
        "Every handoff includes tests and known risks."
    )
    assert result.views[0].source_ref_summaries == ("summary.json",)
    assert department_memory_read_result_to_dict(result)["views"][0][
        "redacted_summary"
    ]


def test_read_filters_by_sensitivity_and_source_ref(tmp_path):
    _approve_memory(
        tmp_path,
        proposal_id="proposal-1",
        kind=DepartmentMemoryKind.RISK,
        sensitivity=DepartmentMemorySensitivity.INTERNAL,
        source_refs=("tasks/task_123/summary.json",),
    )
    _approve_memory(
        tmp_path,
        proposal_id="proposal-2",
        kind=DepartmentMemoryKind.RETROSPECTIVE,
        sensitivity=DepartmentMemorySensitivity.LOW,
        source_refs=("tasks/task_456/summary.json",),
    )
    service = DepartmentMemoryReadService(root=tmp_path)

    result = service.read(
        DepartmentMemoryReadRequest(
            department_id="platform",
            requester_scope="ui",
            maximum_sensitivity=DepartmentMemorySensitivity.LOW,
            source_ref_filters=("tasks/task_456/summary.json",),
        )
    )

    assert [view.memory_id for view in result.views] == ["proposal-2"]


def test_inherited_read_only_returns_inheritable_summaries(tmp_path):
    _approve_memory(
        tmp_path,
        department_id="parent",
        proposal_id="parent-private",
        visibility=DepartmentMemoryVisibility.PRIVATE_TO_DEPARTMENT,
    )
    _approve_memory(
        tmp_path,
        department_id="parent",
        proposal_id="parent-public",
        visibility=DepartmentMemoryVisibility.INHERITABLE_SUMMARY,
        summary="All child teams include rollback notes.",
    )
    service = DepartmentMemoryReadService(root=tmp_path)

    result = service.read(
        DepartmentMemoryReadRequest(
            department_id="child",
            requester_scope="context_policy",
            include_inherited=True,
            inherited_department_ids=("parent",),
        )
    )

    assert [view.memory_id for view in result.views] == ["parent-public"]
    assert result.views[0].inherited is True


def test_restricted_memory_without_permission_returns_placeholder(tmp_path):
    _approve_memory(
        tmp_path,
        sensitivity=DepartmentMemorySensitivity.USER_CONFIRMATION_REQUIRED,
        summary="Sensitive risk summary.",
    )
    service = DepartmentMemoryReadService(root=tmp_path)

    without_permission = service.read(
        DepartmentMemoryReadRequest(
            department_id="platform",
            requester_scope="ui",
            maximum_sensitivity=DepartmentMemorySensitivity.USER_CONFIRMATION_REQUIRED,
        )
    )
    with_permission = service.read(
        DepartmentMemoryReadRequest(
            department_id="platform",
            requester_scope="ui",
            maximum_sensitivity=DepartmentMemorySensitivity.USER_CONFIRMATION_REQUIRED,
            permission_refs=("approvals/user-confirmation-1.json",),
        )
    )

    assert without_permission.views[0].redacted_summary == (
        "Restricted department memory summary withheld."
    )
    assert without_permission.views[0].restricted is True
    assert with_permission.views[0].redacted_summary == "Sensitive risk summary."


def test_pending_and_history_records_are_not_read(tmp_path):
    first = _approve_memory(tmp_path)
    store = DepartmentMemoryProposalStore(root=tmp_path)
    store.create_proposal(
        DepartmentMemoryProposal(
            proposal_id="proposal-2",
            department_id="platform",
            kind=DepartmentMemoryKind.RISK,
            candidate_summary="Pending risk.",
            source_actor="main_agent",
        )
    )
    review = DepartmentMemoryReviewService(store)
    review.approve(
        "platform",
        "proposal-2",
        DepartmentMemoryReviewAction(
            proposal_id="proposal-2",
            decision=DepartmentMemoryReviewDecision.APPROVE,
            actor_id="lead-worker",
            actor_role=DepartmentMemoryReviewerRole.DEPARTMENT_LEAD,
            reason="Update existing memory.",
            reviewed_at="2026-05-21T02:00:00Z",
            supersede_memory_id=first.memory_id,
        ),
    )

    result = DepartmentMemoryReadService(root=tmp_path).read(
        DepartmentMemoryReadRequest(
            department_id="platform",
            requester_scope="context_policy",
        )
    )

    assert [view.revision for view in result.views] == [2]
    assert "Pending risk." in result.views[0].redacted_summary

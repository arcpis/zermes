import pytest

from worker_agents.department_chats import (
    DepartmentChatBinding,
    DepartmentChatBindingService,
    DepartmentChatBindingState,
    DepartmentChatBindingType,
    DepartmentChatError,
    DepartmentChatFallbackKind,
    DepartmentChatMemberSyncAction,
    DepartmentChatPlanStatus,
    count_department_chat_employees,
    plan_department_chat_member_sync,
    plan_single_worker_department_chat,
    required_department_chat_participants,
)
from worker_agents.message_router import (
    ChatParticipantKind,
    ChatParticipantRef,
    ChatThreadType,
    WorkerChatThread,
)
from worker_agents.organization import (
    OrgChatPolicy,
    OrgLeaderKind,
    OrgLeaderRef,
    OrgLifecycleState,
    OrgNode,
    OrgNodeType,
)
from worker_agents.registry import WorkerLifecycleStatus


def _node(member_worker_ids=("engineering_lead", "backend")):
    return OrgNode(
        org_node_id="engineering",
        name="Engineering",
        node_type=OrgNodeType.DEPARTMENT,
        parent_id="root",
        leader=OrgLeaderRef(
            kind=OrgLeaderKind.WORKER,
            worker_id="engineering_lead",
        ),
        member_worker_ids=member_worker_ids,
        chat_policy=OrgChatPolicy(
            default_thread_policy="department_default",
            allow_default_group_chat=True,
        ),
        lifecycle=OrgLifecycleState.ACTIVE,
    )


def _service(worker_lookup=None):
    return DepartmentChatBindingService(
        user_id="user",
        worker_lookup=worker_lookup
        or {
            "engineering_lead": WorkerLifecycleStatus.ENABLED,
            "backend": WorkerLifecycleStatus.ENABLED,
            "frontend": WorkerLifecycleStatus.ENABLED,
        },
    )


def _binding(member_worker_ids=("engineering_lead", "backend")):
    return DepartmentChatBinding(
        binding_id="engineering-default",
        org_node_id="engineering",
        thread_id="engineering-thread",
        binding_type=DepartmentChatBindingType.DEPARTMENT_DEFAULT,
        owner_worker_id="engineering_lead",
        member_worker_ids=member_worker_ids,
        required_participants=required_department_chat_participants("user"),
    )


def test_service_plans_default_binding_from_department_node():
    plan = _service().plan_default_binding(
        org_node=_node(),
        thread_id="engineering-thread",
    )

    assert plan.status == DepartmentChatPlanStatus.READY
    assert plan.binding is not None
    assert plan.binding.binding_type == DepartmentChatBindingType.DEPARTMENT_DEFAULT
    assert plan.binding.owner_worker_id == "engineering_lead"
    assert plan.binding.member_worker_ids == ("engineering_lead", "backend")
    assert plan.binding.parent_summary_targets == ("root",)


def test_service_rejects_inactive_or_non_department_nodes():
    inactive = OrgNode(
        org_node_id="engineering",
        name="Engineering",
        node_type=OrgNodeType.DEPARTMENT,
        parent_id="root",
        leader=OrgLeaderRef(
            kind=OrgLeaderKind.WORKER,
            worker_id="engineering_lead",
        ),
        member_worker_ids=("engineering_lead",),
        lifecycle=OrgLifecycleState.ARCHIVED,
    )

    plan = _service().plan_default_binding(
        org_node=inactive,
        thread_id="engineering-thread",
    )

    assert plan.status == DepartmentChatPlanStatus.REJECTED


def test_service_requires_worker_leader():
    no_leader = OrgNode(
        org_node_id="engineering",
        name="Engineering",
        node_type=OrgNodeType.DEPARTMENT,
        parent_id="root",
        lifecycle=OrgLifecycleState.ACTIVE,
    )

    plan = _service().plan_default_binding(
        org_node=no_leader,
        thread_id="engineering-thread",
    )

    assert plan.status == DepartmentChatPlanStatus.NEEDS_REVIEW


def test_service_rejects_archived_and_deleted_workers():
    plan = _service(
        {
            "engineering_lead": WorkerLifecycleStatus.ENABLED,
            "backend": WorkerLifecycleStatus.ARCHIVED,
        }
    ).plan_default_binding(
        org_node=_node(),
        thread_id="engineering-thread",
    )

    assert plan.status == DepartmentChatPlanStatus.REJECTED
    assert "backend" in plan.reason


def test_validate_binding_participants_requires_user_and_main_agent():
    thread = WorkerChatThread(
        thread_id="engineering-thread",
        thread_type=ChatThreadType.ORGANIZATION_GROUP,
        participants=(
            ChatParticipantRef(ChatParticipantKind.USER, "user"),
            ChatParticipantRef(ChatParticipantKind.WORKER, "engineering_lead"),
            ChatParticipantRef(ChatParticipantKind.WORKER, "backend"),
        ),
    )

    with pytest.raises(DepartmentChatError, match="user and main agent"):
        _service().validate_binding_participants(_binding(), thread)


def test_validate_binding_participants_requires_bound_workers():
    thread = WorkerChatThread(
        thread_id="engineering-thread",
        thread_type=ChatThreadType.ORGANIZATION_GROUP,
        participants=(
            ChatParticipantRef(ChatParticipantKind.USER, "user"),
            ChatParticipantRef(ChatParticipantKind.MAIN_AGENT, "zermes_main_agent"),
            ChatParticipantRef(ChatParticipantKind.WORKER, "engineering_lead"),
        ),
    )

    with pytest.raises(DepartmentChatError, match="missing workers"):
        _service().validate_binding_participants(_binding(), thread)


def test_member_sync_plan_tracks_add_keep_and_remove():
    current = _binding(member_worker_ids=("engineering_lead", "backend"))
    planned = _binding(member_worker_ids=("engineering_lead", "frontend"))

    plan = plan_department_chat_member_sync(
        current_binding=current,
        planned_binding=planned,
    )

    assert plan.status == DepartmentChatPlanStatus.READY
    assert {
        (item.worker_id, item.action)
        for item in plan.items
    } == {
        ("frontend", DepartmentChatMemberSyncAction.ADD),
        ("engineering_lead", DepartmentChatMemberSyncAction.KEEP),
        ("backend", DepartmentChatMemberSyncAction.REMOVE),
    }


def test_member_sync_plan_does_not_reopen_closed_bindings():
    current = DepartmentChatBinding(
        binding_id="engineering-default",
        org_node_id="engineering",
        thread_id="engineering-thread",
        binding_type=DepartmentChatBindingType.DEPARTMENT_DEFAULT,
        state=DepartmentChatBindingState.CLOSED,
        required_participants=required_department_chat_participants("user"),
    )

    plan = plan_department_chat_member_sync(
        current_binding=current,
        planned_binding=_binding(),
    )

    assert plan.status == DepartmentChatPlanStatus.NEEDS_REVIEW
    assert "reopening" in plan.reason


def test_single_worker_department_does_not_create_group_binding():
    plan = _service().plan_default_binding(
        org_node=_node(member_worker_ids=("engineering_lead",)),
        thread_id="engineering-thread",
    )

    assert plan.status == DepartmentChatPlanStatus.NEEDS_REVIEW
    assert plan.binding is None
    assert plan.fallback_target is not None
    assert plan.fallback_target.fallback_kind == DepartmentChatFallbackKind.DIRECT_THREAD_PLAN
    assert plan.fallback_target.worker_id == "engineering_lead"


def test_single_worker_rule_uses_existing_direct_thread_first():
    plan = plan_single_worker_department_chat(
        org_node=_node(member_worker_ids=("engineering_lead",)),
        employee_worker_ids=("engineering_lead",),
        direct_thread_id_by_worker={"engineering_lead": "direct-engineering-lead"},
        parent_thread_id_by_org={"root": "root-thread"},
    )

    assert plan.status == DepartmentChatPlanStatus.NEEDS_REVIEW
    assert plan.fallback_target is not None
    assert plan.fallback_target.fallback_kind == DepartmentChatFallbackKind.DIRECT_THREAD
    assert plan.fallback_target.thread_id == "direct-engineering-lead"


def test_single_worker_rule_can_use_parent_group_thread():
    plan = plan_single_worker_department_chat(
        org_node=_node(member_worker_ids=("engineering_lead",)),
        employee_worker_ids=("engineering_lead",),
        direct_thread_id_by_worker={},
        parent_thread_id_by_org={"root": "root-thread"},
    )

    assert plan.fallback_target is not None
    assert plan.fallback_target.fallback_kind == DepartmentChatFallbackKind.PARENT_GROUP_THREAD
    assert plan.fallback_target.parent_org_node_id == "root"


def test_single_worker_rule_deduplicates_leader_and_member():
    employees = count_department_chat_employees(
        ("engineering_lead",),
        ("engineering_lead",),
    )

    assert employees == ("engineering_lead",)


def test_existing_group_that_shrinks_to_single_worker_needs_close_plan():
    plan = plan_single_worker_department_chat(
        org_node=_node(member_worker_ids=("engineering_lead",)),
        employee_worker_ids=("engineering_lead",),
        direct_thread_id_by_worker={},
        parent_thread_id_by_org={},
        current_binding=_binding(member_worker_ids=("engineering_lead", "backend")),
    )

    assert plan.member_sync_plan is not None
    assert plan.member_sync_plan.status == DepartmentChatPlanStatus.NEEDS_REVIEW
    assert plan.member_sync_plan.items[0].action == DepartmentChatMemberSyncAction.REVIEW

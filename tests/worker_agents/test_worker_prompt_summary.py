from worker_agents.department_chats import (
    DepartmentChatBinding,
    DepartmentChatBindingType,
    required_department_chat_participants,
)
from worker_agents.organization import (
    OrgLeaderKind,
    OrgLeaderRef,
    OrgLifecycleState,
    OrgNode,
    OrgNodeType,
    OrgTree,
)
from worker_agents.profile import WorkerAgentProfile, WorkerDelegationPolicy
from worker_agents.worker_prompt_summary import (
    build_worker_prompt_summary,
    worker_prompt_summary_to_dict,
)


def _profile(worker_id: str, *, allow_delegation: bool = False) -> WorkerAgentProfile:
    return WorkerAgentProfile(
        worker_id=worker_id,
        display_name=worker_id.replace("-", " ").title(),
        description="Build and review implementation tasks.",
        role="implementation",
        responsibilities=("Implement scoped changes", "Report risks"),
        delegation=WorkerDelegationPolicy(
            allow_temporary_child_agents=allow_delegation,
            allowed_child_models=("fast-model",) if allow_delegation else (),
            allowed_child_tools=("read_file",) if allow_delegation else (),
            max_child_task_tokens=500 if allow_delegation else 0,
        ),
    )


def _tree() -> OrgTree:
    return OrgTree(
        tree_id="active",
        root_node_id="root",
        nodes={
            "root": OrgNode(
                org_node_id="root",
                name="Root",
                node_type=OrgNodeType.ROOT,
                child_ids=("code-implementation", "research"),
                leader=OrgLeaderRef(kind=OrgLeaderKind.MAIN_AGENT),
                lifecycle=OrgLifecycleState.ACTIVE,
            ),
            "code-implementation": OrgNode(
                org_node_id="code-implementation",
                name="Code Implementation",
                node_type=OrgNodeType.DEPARTMENT,
                parent_id="root",
                child_ids=("frontend-implementation",),
                leader=OrgLeaderRef(
                    kind=OrgLeaderKind.WORKER,
                    worker_id="code-implementation",
                ),
                member_worker_ids=("code-implementation", "backend-implementation"),
                lifecycle=OrgLifecycleState.ACTIVE,
            ),
            "frontend-implementation": OrgNode(
                org_node_id="frontend-implementation",
                name="Frontend Implementation",
                node_type=OrgNodeType.TEAM,
                parent_id="code-implementation",
                leader=OrgLeaderRef(
                    kind=OrgLeaderKind.WORKER,
                    worker_id="frontend-implementation",
                ),
                member_worker_ids=("frontend-implementation",),
                lifecycle=OrgLifecycleState.ACTIVE,
            ),
            "research": OrgNode(
                org_node_id="research",
                name="Research",
                node_type=OrgNodeType.DEPARTMENT,
                parent_id="root",
                leader=OrgLeaderRef(kind=OrgLeaderKind.WORKER, worker_id="researcher"),
                member_worker_ids=("researcher",),
                lifecycle=OrgLifecycleState.ACTIVE,
            ),
        },
    )


def _bindings() -> tuple[DepartmentChatBinding, ...]:
    return (
        DepartmentChatBinding(
            binding_id="code-implementation-default",
            org_node_id="code-implementation",
            thread_id="dept-code-implementation",
            binding_type=DepartmentChatBindingType.DEPARTMENT_DEFAULT,
            owner_worker_id="code-implementation",
            member_worker_ids=(
                "code-implementation",
                "backend-implementation",
                "frontend-implementation",
            ),
            required_participants=required_department_chat_participants("user"),
            audit_summary="Code implementation department chat.",
        ),
        DepartmentChatBinding(
            binding_id="research-default",
            org_node_id="research",
            thread_id="dept-research",
            binding_type=DepartmentChatBindingType.DEPARTMENT_DEFAULT,
            owner_worker_id="researcher",
            member_worker_ids=("researcher",),
            required_participants=required_department_chat_participants("user"),
            audit_summary="Research department chat.",
        ),
    )


def test_department_owner_prompt_summary_includes_identity_and_reply_thread():
    summary = build_worker_prompt_summary(
        profile=_profile("code-implementation", allow_delegation=True),
        organization_tree=_tree(),
        department_chat_bindings=_bindings(),
    )
    data = worker_prompt_summary_to_dict(summary)

    assert data["worker_id"] == "code-implementation"
    assert data["department_ids"] == ["code-implementation"]
    assert "backend-implementation" in data["direct_member_worker_ids"]
    assert "frontend-implementation" in data["direct_member_worker_ids"]
    assert data["default_reply_thread_id"] == "dept-code-implementation"
    assert data["delegation"]["delegation_allowed"] is True
    assert {"target_type": "worker", "worker_id": "backend-implementation"} in data[
        "delegation"
    ]["delegation_targets"]


def test_child_worker_prompt_summary_names_manager_and_default_department_chat():
    summary = build_worker_prompt_summary(
        profile=_profile("backend-implementation"),
        organization_tree=_tree(),
        department_chat_bindings=_bindings(),
    )
    data = worker_prompt_summary_to_dict(summary)

    assert data["department_names"] == ["Code Implementation"]
    assert data["manager_worker_id"] == "code-implementation"
    assert data["department_chat_threads"][0]["thread_id"] == "dept-code-implementation"
    assert data["delegation"]["delegation_allowed"] is False
    assert data["delegation"]["delegation_reason"] == (
        "worker has no direct subordinate workers"
    )


def test_owner_with_subordinates_but_no_policy_cannot_delegate():
    summary = build_worker_prompt_summary(
        profile=_profile("code-implementation", allow_delegation=False),
        organization_tree=_tree(),
        department_chat_bindings=_bindings(),
    )

    assert summary.delegation.delegation_allowed is False
    assert summary.delegation.delegation_targets == ()
    assert summary.delegation.delegation_reason == (
        "worker delegation policy does not allow child agents"
    )


def test_delegation_targets_stay_within_owned_department():
    summary = build_worker_prompt_summary(
        profile=_profile("code-implementation", allow_delegation=True),
        organization_tree=_tree(),
        department_chat_bindings=_bindings(),
    )
    rendered = worker_prompt_summary_to_dict(summary)

    target_ids = {
        target.get("worker_id")
        for target in rendered["delegation"]["delegation_targets"]
        if target["target_type"] == "worker"
    }
    assert "researcher" not in target_ids
    assert rendered["delegation"]["required_reply_threads"] == [
        "dept-code-implementation"
    ]

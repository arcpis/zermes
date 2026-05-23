import pytest

from worker_agents.organization_evolution import (
    DepartmentCollaborationSurface,
    DepartmentContractionMode,
    OrganizationEvolutionError,
    department_contraction_plan_from_dict,
    department_contraction_plan_to_dict,
    plan_department_contraction,
    validate_department_contraction_plan,
)


def _plan(**overrides):
    data = {
        "plan_id": "contract_platform",
        "department_node_id": "platform",
        "parent_node_id": "engineering",
        "remaining_worker_ids": ["platform_lead", "platform_engineer"],
        "remaining_child_node_ids": ["platform_runtime"],
        "responsibilities_remain": True,
        "contraction_mode": "keep_department",
        "collaboration_surface": "department_group_chat",
        "reason": "Department still has multiple workers.",
        "chat_disposition_ref": None,
        "asset_disposition_ref": None,
        "source_refs": ["delete/platform-researcher.json"],
    }
    data.update(overrides)
    return data


def test_multi_member_department_keeps_department_group_chat():
    plan = plan_department_contraction(
        plan_id="contract_platform",
        department_node_id="platform",
        parent_node_id="engineering",
        remaining_worker_ids=("platform_lead", "platform_engineer"),
        remaining_child_node_ids=("platform_runtime",),
        responsibilities_remain=True,
    )

    loaded = validate_department_contraction_plan(
        department_contraction_plan_to_dict(plan)
    )

    assert loaded == plan
    assert plan.contraction_mode is DepartmentContractionMode.KEEP_DEPARTMENT
    assert (
        plan.collaboration_surface
        is DepartmentCollaborationSurface.DEPARTMENT_GROUP_CHAT
    )


def test_deleting_last_downstream_node_triggers_single_worker_contraction():
    plan = plan_department_contraction(
        plan_id="contract_platform",
        department_node_id="platform",
        parent_node_id="engineering",
        remaining_worker_ids=("platform_lead",),
        remaining_child_node_ids=(),
        responsibilities_remain=True,
    )

    assert (
        plan.contraction_mode
        is DepartmentContractionMode.KEEP_SINGLE_WORKER_DEPARTMENT
    )
    assert plan.collaboration_surface is DepartmentCollaborationSurface.DIRECT_WORKER_CHAT


def test_single_worker_department_can_rebind_chat_to_parent():
    plan = plan_department_contraction(
        plan_id="contract_platform",
        department_node_id="platform",
        parent_node_id="engineering",
        remaining_worker_ids=("platform_lead",),
        remaining_child_node_ids=(),
        responsibilities_remain=True,
        chat_disposition_ref="chats/rebind-platform-to-engineering.json",
    )

    assert plan.contraction_mode is DepartmentContractionMode.REBIND_CHAT_TO_PARENT
    assert plan.collaboration_surface is DepartmentCollaborationSurface.PARENT_GROUP_CHAT


def test_single_worker_department_rejects_department_group_chat():
    with pytest.raises(OrganizationEvolutionError, match="at least two"):
        department_contraction_plan_from_dict(
            _plan(
                remaining_worker_ids=["platform_lead"],
                remaining_child_node_ids=[],
                contraction_mode="keep_single_worker_department",
                collaboration_surface="department_group_chat",
            )
        )


def test_empty_department_generates_archive_plan():
    plan = plan_department_contraction(
        plan_id="archive_platform",
        department_node_id="platform",
        parent_node_id="engineering",
        remaining_worker_ids=(),
        remaining_child_node_ids=(),
        responsibilities_remain=False,
        chat_disposition_ref="chats/archive-platform.json",
        asset_disposition_ref="assets/archive-platform.json",
    )

    assert plan.contraction_mode is DepartmentContractionMode.ARCHIVE_NODE
    assert plan.collaboration_surface is DepartmentCollaborationSurface.NONE


def test_archive_plan_requires_asset_disposition_ref():
    with pytest.raises(OrganizationEvolutionError, match="asset_disposition_ref"):
        department_contraction_plan_from_dict(
            _plan(
                remaining_worker_ids=[],
                remaining_child_node_ids=[],
                responsibilities_remain=False,
                contraction_mode="archive_node",
                collaboration_surface="none",
                chat_disposition_ref="chats/archive-platform.json",
                asset_disposition_ref=None,
            )
        )


def test_department_contraction_plan_rejects_sensitive_payload():
    with pytest.raises(OrganizationEvolutionError, match="sensitive data"):
        validate_department_contraction_plan(_plan(raw_stderr="not allowed"))

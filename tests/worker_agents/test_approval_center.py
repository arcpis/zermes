import pytest

from worker_agents.management import (
    ApprovalActionRequest,
    approval_audit_record_to_dict,
    approval_queue_item_to_dict,
    approval_risk_presentation_to_dict,
    build_approval_queue_item,
    build_approval_risk_presentation,
    create_approval_audit_record,
    filter_approval_queue_items,
    validate_approval_action_request,
)


def test_approval_queue_accepts_evolution_and_department_asset_proposals():
    evolution = build_approval_queue_item(
        {
            "source_kind": "organization_evolution",
            "proposal_id": "evo-1",
            "status": "pending",
            "requestor_id": "main-agent",
            "impact_summary": "Create child worker.",
        }
    )
    memory = build_approval_queue_item(
        {
            "source_kind": "department_memory",
            "proposal_id": "mem-1",
            "status": "pending",
            "requestor_id": "worker-a",
            "impact_summary": "raw private memory text",
        }
    )

    assert approval_queue_item_to_dict(evolution)["source_kind"] == "organization_evolution"
    assert approval_queue_item_to_dict(memory)["impact_summary"] == "[redacted summary]"


def test_approval_queue_filters_high_risk_and_statuses():
    pending_high = build_approval_queue_item(
        {
            "source_kind": "department_tool_policy",
            "proposal_id": "tool-1",
            "status": "pending",
            "requestor_id": "worker-a",
            "risks": [{"code": "permission_expansion", "severity": "blocker"}],
        }
    )
    expired = build_approval_queue_item(
        {
            "source_kind": "organization_evolution",
            "proposal_id": "evo-1",
            "status": "expired",
            "requestor_id": "worker-a",
        }
    )

    assert filter_approval_queue_items([pending_high, expired], high_risk=True) == (
        pending_high,
    )
    assert filter_approval_queue_items([pending_high, expired], status="expired") == (
        expired,
    )


def test_approval_action_requires_allowed_actor_and_explicit_high_risk_confirmation():
    item = build_approval_queue_item(
        {
            "source_kind": "department_tool_policy",
            "proposal_id": "tool-1",
            "status": "pending",
            "requestor_id": "worker-a",
            "risks": [{"code": "permission_expansion", "severity": "blocker"}],
            "user_confirmation_required": True,
        }
    )

    with pytest.raises(ValueError, match="not allowed"):
        validate_approval_action_request(
            item,
            ApprovalActionRequest("tool-1", "approve", "worker-a", "ok", True),
            allowed_actor_ids=["lead"],
        )
    with pytest.raises(ValueError, match="explicit confirmation"):
        validate_approval_action_request(
            item,
            ApprovalActionRequest("tool-1", "approve", "lead", "ok"),
            allowed_actor_ids=["lead"],
        )

    request = ApprovalActionRequest("tool-1", "approve", "lead", "ok", True)
    validate_approval_action_request(item, request, allowed_actor_ids=["lead"])
    audit = create_approval_audit_record(item, request, timestamp="2026-05-26T00:00:00Z")

    assert approval_audit_record_to_dict(audit)["risk_summary"] == "permission_expansion"


def test_terminal_approval_states_are_not_executable():
    item = build_approval_queue_item(
        {
            "source_kind": "organization_evolution",
            "proposal_id": "evo-1",
            "status": "rejected",
            "requestor_id": "worker-a",
        }
    )

    with pytest.raises(ValueError, match="terminal"):
        validate_approval_action_request(
            item,
            ApprovalActionRequest("evo-1", "approve", "lead", "ok", True),
            allowed_actor_ids=["lead"],
        )


def test_risk_presentation_separates_blockers_warnings_and_disabled_reason():
    item = build_approval_queue_item(
        {
            "source_kind": "external_agent",
            "proposal_id": "ext-1",
            "status": "pending",
            "requestor_id": "worker-a",
            "blockers": ["adapter review missing"],
            "warnings": ["budget should be checked"],
            "risks": [
                {"code": "external_agent", "label": "External agent access", "severity": "blocker"},
                {"code": "sensitive_memory", "label": "Sensitive memory summary", "severity": "warning"},
            ],
            "user_confirmation_required": True,
        }
    )

    data = approval_risk_presentation_to_dict(build_approval_risk_presentation(item))

    assert data["disabled_action_reason"] == "adapter review missing"
    assert "budget should be checked" in data["warnings"]
    assert "Sensitive memory summary" in data["warnings"]
    assert data["user_required_summary"]

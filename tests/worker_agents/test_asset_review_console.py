from worker_agents.management import (
    asset_adoption_history_item_to_dict,
    asset_review_item_to_dict,
    build_asset_adoption_history_item,
    build_asset_review_item,
    build_memory_review_detail,
    build_skill_review_detail,
    build_tool_policy_review_detail,
    filter_asset_adoption_history,
    memory_review_detail_to_dict,
    skill_review_detail_to_dict,
    tool_policy_review_detail_to_dict,
)


def test_asset_review_model_accepts_memory_skill_and_tool_proposals():
    memory = build_asset_review_item(
        {
            "proposal_kind": "memory",
            "proposal_id": "mem-1",
            "status": "pending",
            "target_department_id": "engineering",
            "summary": "raw private memory",
            "sensitivity": "sensitive",
        }
    )
    skill = build_asset_review_item(
        {
            "proposal_kind": "skill_binding",
            "proposal_id": "skill-1",
            "status": "pending",
            "target_department_id": "engineering",
            "summary": "Use release skill.",
        }
    )
    tool = build_asset_review_item(
        {
            "proposal_kind": "tool_policy",
            "proposal_id": "tool-1",
            "status": "pending",
            "target_department_id": "engineering",
            "summary": "Allow read-only tool.",
            "conflict_refs": ["profiles/worker-a/tool-policy"],
        }
    )

    assert asset_review_item_to_dict(memory)["redaction_required"] is True
    assert asset_review_item_to_dict(memory)["summary"] == "[redacted summary]"
    assert asset_review_item_to_dict(skill)["proposal_kind"] == "skill_binding"
    assert asset_review_item_to_dict(tool)["conflict_refs"] == [
        "profiles/worker-a/tool-policy"
    ]


def test_memory_skill_and_tool_details_are_low_sensitive_action_requests():
    memory = build_memory_review_detail(
        {
            "proposal_id": "mem-1",
            "classification": "private",
            "summary": "raw private memory",
            "conflict_refs": ["memory/a"],
        }
    )
    skill = build_skill_review_detail(
        {
            "proposal_id": "skill-1",
            "skill_id": "release-review",
            "skill_available": False,
            "applicability_summary": "release review",
            "tool_dependency_warnings": ["missing shell_read"],
        }
    )
    tool = build_tool_policy_review_detail(
        {
            "proposal_id": "tool-1",
            "permission_impact": "workspace write",
            "approval_requirement": "user_confirmation",
            "profile_cross_check_summary": "profile denies write",
            "high_risk": True,
            "action_request": {
                "proposal_id": "tool-1",
                "decision": "request_redaction",
                "actor_id": "lead",
                "reason": "needs safer summary",
            },
        }
    )

    assert memory_review_detail_to_dict(memory)["redaction_required"] is True
    assert memory_review_detail_to_dict(memory)["summary"] == "[redacted summary]"
    assert skill_review_detail_to_dict(skill)["tool_dependency_warnings"] == [
        "missing shell_read"
    ]
    tool_data = tool_policy_review_detail_to_dict(tool)
    assert tool_data["high_risk"] is True
    assert tool_data["action_request"]["decision"] == "request_redaction"


def test_asset_adoption_history_filters_and_keeps_partial_rejections():
    accepted = build_asset_adoption_history_item(
        {
            "asset_id": "asset-1",
            "proposal_id": "proposal-1",
            "department_id": "engineering",
            "asset_kind": "memory",
            "decision": "accept",
            "reviewer_id": "lead",
            "reason": "Looks useful.",
            "decided_at": "2026-05-26T00:00:00Z",
        }
    )
    partial = build_asset_adoption_history_item(
        {
            "asset_id": "asset-2",
            "proposal_id": "proposal-2",
            "department_id": "engineering",
            "asset_kind": "skill_binding",
            "decision": "partial_accept",
            "reviewer_id": "lead",
            "reason": "raw secret explanation",
            "decided_at": "2026-05-26T00:00:00Z",
            "accepted_refs": ["skill/release-review"],
            "rejected_refs": ["tool/shell_write"],
        }
    )

    assert filter_asset_adoption_history([accepted, partial], decision="accept") == (
        accepted,
    )
    partial_data = asset_adoption_history_item_to_dict(partial)
    assert partial_data["rejected_refs"] == ["tool/shell_write"]
    assert partial_data["reason"] == "[redacted summary]"

import pytest

from worker_agents.department_tool_policies import (
    DepartmentToolInheritanceMode,
    DepartmentToolPolicyError,
    DepartmentToolPolicyProposal,
    DepartmentToolPolicyProposalAction,
    DepartmentToolPolicyProposalState,
    DepartmentToolPolicyRecord,
    DepartmentToolPolicySnapshot,
    DepartmentToolPolicyState,
    DepartmentToolPolicyVisibility,
    DepartmentToolRiskLevel,
    DepartmentToolRuleEffect,
    department_tool_policy_dir,
    department_tool_policy_from_dict,
    department_tool_policy_proposal_from_dict,
    department_tool_policy_proposal_to_dict,
    department_tool_policy_snapshot_to_dict,
    department_tool_policy_to_dict,
    validate_department_tool_policy_payload,
)


def test_department_tool_policy_serializes_stable_contract():
    policy = DepartmentToolPolicyRecord(
        department_id="platform",
        policy_id="write-review",
        tool_refs=("write_file",),
        effect=DepartmentToolRuleEffect.REQUIRES_APPROVAL,
        risk_level=DepartmentToolRiskLevel.HIGH,
        visibility=DepartmentToolPolicyVisibility.INHERITABLE_POLICY,
        inheritance_mode=DepartmentToolInheritanceMode.EXTEND_REQUIRES_APPROVAL,
        workspace_read_roots=("repo",),
        workspace_write_roots=("repo/src",),
        max_task_tokens=4000,
        max_turn_tokens=1000,
        max_task_cost_usd=2.5,
        approval_requirement="department_lead",
        disabled_conditions=("credential_files",),
        owner="platform-lead",
        source_refs=("tasks/task-1/tool-policy.json",),
        accepted_at="2026-05-22T00:00:00Z",
        audit_summary="Accepted by department lead.",
    )

    payload = department_tool_policy_to_dict(policy)
    loaded = department_tool_policy_from_dict(payload)

    assert loaded == policy
    assert list(payload) == [
        "department_id",
        "policy_id",
        "schema_version",
        "tool_refs",
        "effect",
        "risk_level",
        "state",
        "visibility",
        "inheritance_mode",
        "workspace_read_roots",
        "workspace_write_roots",
        "max_task_tokens",
        "max_turn_tokens",
        "max_task_cost_usd",
        "approval_requirement",
        "disabled_conditions",
        "owner",
        "source_refs",
        "revision",
        "active",
        "accepted_at",
        "created_at",
        "updated_at",
        "audit_summary",
    ]


def test_department_tool_policy_proposal_defaults_to_pending():
    proposal = DepartmentToolPolicyProposal(
        proposal_id="proposal-1",
        department_id="platform",
        proposed_action=DepartmentToolPolicyProposalAction.ADD_POLICY,
        tool_refs=("read_file",),
        candidate_effect=DepartmentToolRuleEffect.ALLOW,
        source_actor="main_agent",
        rationale="Useful for review tasks.",
    )

    assert proposal.state == DepartmentToolPolicyProposalState.PENDING
    assert proposal.risk_level == DepartmentToolRiskLevel.MEDIUM
    payload = department_tool_policy_proposal_to_dict(proposal)
    assert department_tool_policy_proposal_from_dict(payload) == proposal


def test_department_tool_policy_snapshot_excludes_credentials():
    snapshot = DepartmentToolPolicySnapshot(
        department_id="platform",
        allowed_tools=("read_file",),
        denied_tools=("shell",),
        approval_required_tools=("write_file",),
        user_confirmation_required_tools=("network",),
        workspace_read_roots=("repo",),
        workspace_write_roots=("repo/src",),
        policy_refs=("organization/departments/platform/policies/tools/policy.json",),
        denial_reasons=("deny_policy",),
        audit_summary="Resolved from department policy.",
    )

    payload = department_tool_policy_snapshot_to_dict(snapshot)

    assert payload["allowed_tools"] == ["read_file"]
    assert "credential" not in payload
    assert "token" not in payload
    assert "env" not in payload


@pytest.mark.parametrize(
    "payload",
    [
        {"secret": "value"},
        {"nested": {"credential": "value"}},
        {"items": [{"raw_stdout": "full log"}]},
        {"sensitive_path_content": "private file text"},
    ],
)
def test_department_tool_policy_payload_rejects_sensitive_fields(payload):
    with pytest.raises(DepartmentToolPolicyError):
        validate_department_tool_policy_payload(payload)


@pytest.mark.parametrize("value", ["../policy.json", "/tmp/policy.json", r"C:\tmp\x"])
def test_department_tool_policy_rejects_unsafe_refs(value):
    with pytest.raises(DepartmentToolPolicyError, match="source_refs"):
        DepartmentToolPolicyRecord(
            department_id="platform",
            policy_id="read-policy",
            tool_refs=("read_file",),
            effect=DepartmentToolRuleEffect.ALLOW,
            source_refs=(value,),
        )


def test_department_tool_policy_rejects_path_like_ids():
    with pytest.raises(ValueError):
        DepartmentToolPolicyRecord(
            department_id="team/platform",
            policy_id="read-policy",
            tool_refs=("read_file",),
            effect=DepartmentToolRuleEffect.ALLOW,
        )

    with pytest.raises(DepartmentToolPolicyError):
        DepartmentToolPolicyProposal(
            proposal_id="../proposal-1",
            department_id="platform",
            proposed_action=DepartmentToolPolicyProposalAction.ADD_POLICY,
            tool_refs=("read_file",),
            candidate_effect=DepartmentToolRuleEffect.ALLOW,
            source_actor="main_agent",
            rationale="Useful for review tasks.",
        )


def test_department_tool_policy_path_stays_in_department_policy_area():
    path = department_tool_policy_dir("/profile/worker_agents", "platform")

    assert path.parts[-5:] == (
        "organization",
        "departments",
        "platform",
        "policies",
        "tools",
    )
    assert "workers" not in path.parts


def test_disabled_policy_can_be_serialized_but_not_marked_active_by_default():
    policy = DepartmentToolPolicyRecord(
        department_id="platform",
        policy_id="disabled-shell",
        tool_refs=("shell",),
        effect=DepartmentToolRuleEffect.DENY,
        state=DepartmentToolPolicyState.DISABLED,
        active=False,
    )

    assert department_tool_policy_from_dict(department_tool_policy_to_dict(policy)) == policy

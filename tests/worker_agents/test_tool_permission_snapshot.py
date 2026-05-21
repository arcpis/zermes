import pytest

from worker_agents.private_assets import PrivateAssetError
from worker_agents.profile import (
    WorkerAgentProfile,
    WorkerBudgetPolicy,
    WorkerToolPolicy,
    WorkerWorkspacePolicy,
)
from worker_agents.tool_permission_snapshot import (
    ToolPolicyCandidate,
    ToolPolicyViolationCode,
    build_tool_permission_snapshot,
    check_tool_policy_within_worker_snapshot,
    tool_permission_snapshot_to_dict,
)


def _profile():
    return WorkerAgentProfile(
        worker_id="frontend",
        display_name="Frontend",
        description="Builds UI features.",
        role="frontend",
        tools=WorkerToolPolicy(
            allowed_tools=("read_file", "write_file"),
            approval_required_tools=("write_file",),
        ),
        workspace=WorkerWorkspacePolicy(
            read_roots=("src", "tests"),
            write_roots=("src",),
        ),
        budgets=WorkerBudgetPolicy(
            max_task_tokens=1000,
            max_turn_tokens=200,
            max_task_cost_usd=1.5,
        ),
    )


def test_empty_profile_generates_minimum_permission_snapshot():
    profile = WorkerAgentProfile(
        worker_id="frontend",
        display_name="Frontend",
        description="Builds UI features.",
        role="frontend",
    )

    snapshot = build_tool_permission_snapshot(profile)

    assert snapshot.allowed_tools == ()
    assert snapshot.read_roots == ()
    assert snapshot.max_task_tokens == 0
    assert snapshot.redaction_status == "credentials_excluded"


def test_tool_permission_snapshot_excludes_credentials_and_is_stable():
    snapshot = build_tool_permission_snapshot(_profile(), created_at="2026-05-21T00:00:00Z")

    payload = tool_permission_snapshot_to_dict(snapshot)

    assert payload["profile_hash"].startswith("sha256:")
    assert payload["allowed_tools"] == ["read_file", "write_file"]
    assert "credential" not in payload
    assert "secret" not in payload


def test_policy_candidate_within_snapshot_is_allowed():
    snapshot = build_tool_permission_snapshot(_profile())
    candidate = ToolPolicyCandidate(
        requested_tools=("read_file",),
        requested_read_roots=("src",),
        requested_max_task_tokens=500,
        requested_max_turn_tokens=100,
        requested_max_task_cost_usd=1.0,
    )

    result = check_tool_policy_within_worker_snapshot(snapshot, candidate)

    assert result.allowed is True
    assert result.violations == ()
    assert result.approval_required == ()


def test_policy_candidate_cannot_exceed_worker_tool_or_workspace_permissions():
    snapshot = build_tool_permission_snapshot(_profile())
    candidate = ToolPolicyCandidate(
        requested_tools=("shell",),
        requested_write_roots=("outside",),
    )

    result = check_tool_policy_within_worker_snapshot(snapshot, candidate)

    assert result.allowed is False
    assert ToolPolicyViolationCode.TOOL_NOT_IN_PROFILE.value in result.violations
    assert ToolPolicyViolationCode.WORKSPACE_OUT_OF_SCOPE.value in result.violations


def test_policy_candidate_cannot_exceed_worker_budget_limits():
    snapshot = build_tool_permission_snapshot(_profile())
    candidate = ToolPolicyCandidate(
        requested_tools=("read_file",),
        requested_max_task_tokens=1001,
        requested_max_turn_tokens=201,
        requested_max_task_cost_usd=2.0,
    )

    result = check_tool_policy_within_worker_snapshot(snapshot, candidate)

    assert result.allowed is False
    assert ToolPolicyViolationCode.TASK_TOKEN_BUDGET_EXCEEDED.value in result.violations
    assert ToolPolicyViolationCode.TURN_TOKEN_BUDGET_EXCEEDED.value in result.violations
    assert ToolPolicyViolationCode.COST_BUDGET_EXCEEDED.value in result.violations


def test_high_risk_tool_returns_approval_required_instead_of_allowed():
    snapshot = build_tool_permission_snapshot(_profile())
    candidate = ToolPolicyCandidate(
        requested_tools=("write_file",),
        high_risk_tools=("write_file",),
    )

    result = check_tool_policy_within_worker_snapshot(snapshot, candidate)

    assert result.allowed is False
    assert result.violations == ()
    assert result.approval_required == (
        ToolPolicyViolationCode.HIGH_RISK_REQUIRES_APPROVAL.value,
    )


def test_policy_candidate_metadata_rejects_secret_material():
    with pytest.raises(PrivateAssetError):
        ToolPolicyCandidate(metadata={"api_key": "secret"})


def test_building_snapshot_does_not_mutate_profile():
    profile = _profile()
    before = profile.tools.allowed_tools

    build_tool_permission_snapshot(profile)

    assert profile.tools.allowed_tools == before

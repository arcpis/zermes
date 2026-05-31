import pytest

from worker_agents.organization_evolution import (
    EVOLUTION_PROPOSAL_SCHEMA_VERSION,
    EvolutionApprovalLevel,
    EvolutionInitiatorKind,
    EvolutionProposalInitiator,
    EvolutionProposalStatus,
    EvolutionProposalType,
    EvolutionRiskContext,
    EvolutionRiskFlag,
    OrganizationEvolutionError,
    OrganizationEvolutionProposal,
    apply_manual_approval_override,
    classify_evolution_risks,
    dump_organization_evolution_proposal_json,
    load_organization_evolution_proposal_json,
    organization_evolution_proposal_from_dict,
    organization_evolution_proposal_to_dict,
    resolve_approval_requirement,
    validate_evolution_proposal,
)
from worker_agents.storage.organization_evolution_store import (
    EvolutionProposalStatusChange,
    EvolutionProposalStore,
    StoredEvolutionProposal,
    evolution_proposal_status_change_from_dict,
    stored_evolution_proposal_from_dict,
)


def _proposal_data(**overrides):
    data = {
        "proposal_id": "proposal_001",
        "proposal_type": "create_child_agent",
        "schema_version": EVOLUTION_PROPOSAL_SCHEMA_VERSION,
        "status": "draft",
        "initiator": {
            "kind": "main_agent",
            "initiator_id": "zermes_main_agent",
            "display_name": "Zermes",
        },
        "target_node_ids": ["platform"],
        "affected_worker_ids": ["researcher"],
        "reason": "Add a focused platform worker.",
        "before_summary": "Platform has no child specialist.",
        "after_summary": "Platform has one child specialist.",
        "risk_flags": [],
        "approval_policy": "unresolved",
        "asset_disposition_refs": [],
        "chat_disposition_refs": ["chats/platform-create.md"],
        "rollback_summary_ref": "rollback/platform-create.md",
        "source_refs": ["runtime/result-summary.json"],
        "created_at": "2026-05-23T00:00:00Z",
        "updated_at": "2026-05-23T00:00:00Z",
    }
    data.update(overrides)
    return data


@pytest.mark.parametrize("proposal_type", list(EvolutionProposalType))
def test_evolution_proposal_accepts_supported_types(proposal_type):
    extra = {}
    if proposal_type is EvolutionProposalType.TRANSFER_ASSETS:
        extra["asset_disposition_refs"] = ["assets/transfer-plan.json"]

    proposal = organization_evolution_proposal_from_dict(
        _proposal_data(proposal_type=proposal_type.value, **extra)
    )

    assert proposal.proposal_type is proposal_type
    assert proposal.status is EvolutionProposalStatus.DRAFT


def test_evolution_proposal_round_trips_through_json():
    proposal = organization_evolution_proposal_from_dict(_proposal_data())

    loaded = load_organization_evolution_proposal_json(
        dump_organization_evolution_proposal_json(proposal)
    )

    assert loaded == proposal


def test_evolution_proposal_dataclass_serializes_to_stable_dict():
    proposal = OrganizationEvolutionProposal(
        proposal_id="proposal_002",
        proposal_type=EvolutionProposalType.ARCHIVE_ORG_NODE,
        status=EvolutionProposalStatus.PENDING_APPROVAL,
        initiator=EvolutionProposalInitiator(
            kind=EvolutionInitiatorKind.MANAGEMENT_COMMAND,
            initiator_id="ops_console",
        ),
        target_node_ids=("legacy_team",),
        affected_worker_ids=(),
        reason="Archive an unused team.",
        before_summary="Legacy team is present.",
        after_summary="Legacy team is archived.",
        rollback_summary_ref="rollback/archive-legacy.md",
    )

    data = organization_evolution_proposal_to_dict(proposal)

    assert data["proposal_id"] == "proposal_002"
    assert data["proposal_type"] == "archive_org_node"
    assert data["initiator"]["kind"] == "management_command"


@pytest.mark.parametrize(
    "missing_field",
    [
        "proposal_id",
        "proposal_type",
        "initiator",
        "target_node_ids",
        "reason",
        "before_summary",
        "after_summary",
        "rollback_summary_ref",
    ],
)
def test_evolution_proposal_rejects_missing_required_fields(missing_field):
    data = _proposal_data()
    data.pop(missing_field)

    with pytest.raises(OrganizationEvolutionError):
        organization_evolution_proposal_from_dict(data)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("proposal_id", "proposal/001"),
        ("proposal_id", r"proposal\001"),
        ("proposal_id", ".."),
        ("target_node_ids", ["../platform"]),
        ("affected_worker_ids", ["worker/one"]),
        ("rollback_summary_ref", "../rollback.md"),
        ("source_refs", ["/absolute/source.json"]),
    ],
)
def test_evolution_proposal_rejects_path_like_identifiers(field, value):
    with pytest.raises(OrganizationEvolutionError):
        organization_evolution_proposal_from_dict(_proposal_data(**{field: value}))


def test_evolution_proposal_rejects_unknown_type():
    with pytest.raises(OrganizationEvolutionError, match="Unknown evolution proposal type"):
        organization_evolution_proposal_from_dict(
            _proposal_data(proposal_type="promote_worker")
        )


def test_evolution_proposal_rejects_unknown_fields():
    with pytest.raises(OrganizationEvolutionError, match="unknown fields"):
        organization_evolution_proposal_from_dict(_proposal_data(raw_plan="too broad"))


@pytest.mark.parametrize(
    "sensitive_field",
    [
        "raw_transcript",
        "secret",
        "credential",
        "raw_stdout",
        "raw_stderr",
        "private_memory_text",
    ],
)
def test_evolution_proposal_rejects_sensitive_fields(sensitive_field):
    with pytest.raises(OrganizationEvolutionError, match="sensitive data"):
        validate_evolution_proposal(_proposal_data(**{sensitive_field: "do not store"}))


def test_transfer_assets_requires_asset_disposition_ref():
    with pytest.raises(OrganizationEvolutionError, match="asset_disposition_refs"):
        organization_evolution_proposal_from_dict(
            _proposal_data(proposal_type="transfer_assets")
        )


@pytest.mark.parametrize(
    ("context_kwargs", "expected_flag"),
    [
        ({"permission_expands": True}, EvolutionRiskFlag.PERMISSION_EXPANSION),
        ({"budget_increases": True}, EvolutionRiskFlag.BUDGET_INCREASE),
        ({"model_tier_increases": True}, EvolutionRiskFlag.MODEL_TIER_INCREASE),
        ({"external_agent_involved": True}, EvolutionRiskFlag.EXTERNAL_AGENT),
        ({"sensitive_memory_moves": True}, EvolutionRiskFlag.SENSITIVE_MEMORY),
        ({"active_task_refs": ("tasks/active.json",)}, EvolutionRiskFlag.ACTIVE_TASKS),
        (
            {"pending_high_risk_approval_refs": ("approvals/pending.json",)},
            EvolutionRiskFlag.PENDING_HIGH_RISK_APPROVALS,
        ),
        ({"group_chat_closes": True}, EvolutionRiskFlag.GROUP_CHAT_CLOSURE),
        (
            {"responsibilities_change": True},
            EvolutionRiskFlag.RESPONSIBILITY_CHANGE,
        ),
    ],
)
def test_classify_evolution_risks_returns_expected_flags(
    context_kwargs, expected_flag
):
    proposal = organization_evolution_proposal_from_dict(_proposal_data())

    risks = classify_evolution_risks(
        proposal,
        EvolutionRiskContext(**context_kwargs, source_refs=("analysis/risk.json",)),
    )

    assert expected_flag in {risk.flag for risk in risks}
    assert all(risk.reason for risk in risks)


@pytest.mark.parametrize(
    "context_kwargs",
    [
        {"permission_expands": True},
        {"budget_increases": True},
        {"model_tier_increases": True},
        {"external_agent_involved": True},
        {"sensitive_memory_moves": True},
    ],
)
def test_user_confirmation_risks_require_user_approval(context_kwargs):
    proposal = organization_evolution_proposal_from_dict(_proposal_data())

    risks = classify_evolution_risks(proposal, EvolutionRiskContext(**context_kwargs))
    requirement = resolve_approval_requirement(proposal, risks)

    assert requirement.level is EvolutionApprovalLevel.USER_APPROVAL
    assert requirement.required_approvers == ("user",)


def test_multiple_risks_use_highest_approval_level():
    proposal = organization_evolution_proposal_from_dict(_proposal_data())

    risks = classify_evolution_risks(
        proposal,
        EvolutionRiskContext(
            group_chat_closes=True,
            responsibilities_change=True,
            budget_increases=True,
        ),
    )
    requirement = resolve_approval_requirement(proposal, risks)

    assert requirement.level is EvolutionApprovalLevel.USER_APPROVAL
    assert EvolutionRiskFlag.BUDGET_INCREASE in requirement.risk_flags
    assert EvolutionRiskFlag.GROUP_CHAT_CLOSURE in requirement.risk_flags


def test_active_tasks_and_pending_approvals_are_execution_blockers():
    proposal = organization_evolution_proposal_from_dict(_proposal_data())

    risks = classify_evolution_risks(
        proposal,
        EvolutionRiskContext(
            active_task_refs=("tasks/active.json",),
            pending_high_risk_approval_refs=("approvals/high-risk.json",),
        ),
    )
    requirement = resolve_approval_requirement(proposal, risks)

    assert requirement.blocking_flags == (
        EvolutionRiskFlag.ACTIVE_TASKS,
        EvolutionRiskFlag.PENDING_HIGH_RISK_APPROVALS,
    )
    assert "main_agent" in requirement.required_approvers


def test_low_risk_create_can_be_policy_approved():
    proposal = organization_evolution_proposal_from_dict(_proposal_data())

    requirement = resolve_approval_requirement(
        proposal,
        classify_evolution_risks(proposal),
    )

    assert requirement.level is EvolutionApprovalLevel.POLICY_APPROVED
    assert requirement.blocking_flags == ()


def test_manual_override_preserves_original_risk_reasons():
    proposal = organization_evolution_proposal_from_dict(_proposal_data())
    risks = classify_evolution_risks(
        proposal,
        EvolutionRiskContext(responsibilities_change=True),
    )
    requirement = resolve_approval_requirement(proposal, risks)

    overridden = apply_manual_approval_override(
        requirement,
        level=EvolutionApprovalLevel.USER_APPROVAL,
        actor="zermes_main_agent",
        reason="Escalate for user review.",
    )

    assert overridden.level is EvolutionApprovalLevel.USER_APPROVAL
    assert overridden.reasons == requirement.reasons
    assert overridden.risk_flags == requirement.risk_flags
    assert overridden.manual_override_by == "zermes_main_agent"


def test_manual_override_cannot_lower_high_risk_requirement():
    proposal = organization_evolution_proposal_from_dict(_proposal_data())
    risks = classify_evolution_risks(
        proposal,
        EvolutionRiskContext(permission_expands=True),
    )
    requirement = resolve_approval_requirement(proposal, risks)

    with pytest.raises(OrganizationEvolutionError, match="cannot lower"):
        apply_manual_approval_override(
            requirement,
            level=EvolutionApprovalLevel.MAIN_AGENT_APPROVAL,
            actor="zermes_main_agent",
            reason="Too low.",
        )


def test_evolution_proposal_store_creates_reads_and_filters(tmp_path):
    store = EvolutionProposalStore(tmp_path / "worker_agents" / "organization" / "proposals")
    proposal = organization_evolution_proposal_from_dict(_proposal_data())

    store.create_proposal(
        proposal,
        actor="zermes_main_agent",
        changed_at="2026-05-23T00:00:00Z",
        reason="Initial proposal.",
    )

    assert store.load_proposal("proposal_001") == proposal
    assert store.list_proposals(status=EvolutionProposalStatus.DRAFT) == [proposal]
    assert store.list_proposals(proposal_type=EvolutionProposalType.CREATE_CHILD_AGENT)
    assert store.list_proposals(target_node_id="platform") == [proposal]
    assert not (tmp_path / "worker_agents" / "organization" / "active.json").exists()


def test_evolution_proposal_store_records_status_history(tmp_path):
    store = EvolutionProposalStore(tmp_path / "worker_agents" / "organization" / "proposals")
    proposal = organization_evolution_proposal_from_dict(_proposal_data())
    store.create_proposal(
        proposal,
        actor="zermes_main_agent",
        changed_at="2026-05-23T00:00:00Z",
        reason="Initial proposal.",
    )

    store.update_status(
        "proposal_001",
        EvolutionProposalStatus.PENDING_APPROVAL,
        actor="zermes_main_agent",
        changed_at="2026-05-23T00:10:00Z",
        reason="Ready for review.",
    )
    store.update_status(
        "proposal_001",
        EvolutionProposalStatus.APPROVED,
        actor="user",
        changed_at="2026-05-23T00:20:00Z",
        reason="Approved by user.",
    )

    record = store.load_record("proposal_001")

    assert record.proposal.status is EvolutionProposalStatus.APPROVED
    assert [change.to_status for change in record.status_history] == [
        EvolutionProposalStatus.DRAFT,
        EvolutionProposalStatus.PENDING_APPROVAL,
        EvolutionProposalStatus.APPROVED,
    ]
    assert record.status_history[-1].from_status is EvolutionProposalStatus.PENDING_APPROVAL


def test_evolution_proposal_store_rejects_invalid_status_transition(tmp_path):
    store = EvolutionProposalStore(tmp_path / "worker_agents" / "organization" / "proposals")
    store.create_proposal(
        organization_evolution_proposal_from_dict(_proposal_data()),
        actor="zermes_main_agent",
        changed_at="2026-05-23T00:00:00Z",
        reason="Initial proposal.",
    )

    with pytest.raises(OrganizationEvolutionError, match="status transition"):
        store.update_status(
            "proposal_001",
            EvolutionProposalStatus.EXECUTED,
            actor="executor",
            changed_at="2026-05-23T00:10:00Z",
            reason="Cannot execute directly.",
        )


@pytest.mark.parametrize(
    "terminal_status",
    [EvolutionProposalStatus.REJECTED, EvolutionProposalStatus.EXPIRED],
)
def test_rejected_or_expired_proposal_cannot_become_executable(
    tmp_path, terminal_status
):
    store = EvolutionProposalStore(tmp_path / "worker_agents" / "organization" / "proposals")
    store.create_proposal(
        organization_evolution_proposal_from_dict(_proposal_data()),
        actor="zermes_main_agent",
        changed_at="2026-05-23T00:00:00Z",
        reason="Initial proposal.",
    )
    store.update_status(
        "proposal_001",
        terminal_status,
        actor="zermes_main_agent",
        changed_at="2026-05-23T00:10:00Z",
        reason="Stop proposal.",
    )

    with pytest.raises(OrganizationEvolutionError, match="status transition"):
        store.update_status(
            "proposal_001",
            EvolutionProposalStatus.EXECUTED,
            actor="executor",
            changed_at="2026-05-23T00:20:00Z",
            reason="Cannot execute terminal status.",
        )


def test_evolution_proposal_store_rejects_invalid_id_and_sensitive_payload(tmp_path):
    store = EvolutionProposalStore(tmp_path / "worker_agents" / "organization" / "proposals")

    with pytest.raises(OrganizationEvolutionError):
        store.proposal_path("../proposal")

    with pytest.raises(OrganizationEvolutionError, match="sensitive data"):
        store.create_proposal(
            _proposal_data(raw_stdout="full output"),
            actor="zermes_main_agent",
            changed_at="2026-05-23T00:00:00Z",
            reason="Initial proposal.",
        )


def test_stored_evolution_proposal_round_trips_status_history():
    proposal = organization_evolution_proposal_from_dict(_proposal_data())
    record = StoredEvolutionProposal(
        proposal=proposal,
        status_history=(
            EvolutionProposalStatusChange(
                actor="zermes_main_agent",
                changed_at="2026-05-23T00:00:00Z",
                from_status=None,
                to_status=EvolutionProposalStatus.DRAFT,
                reason="Initial proposal.",
            ),
        ),
    )

    loaded = stored_evolution_proposal_from_dict(
        {
            "schema_version": 1,
            "proposal": organization_evolution_proposal_to_dict(proposal),
            "status_history": [
                {
                    "actor": "zermes_main_agent",
                    "changed_at": "2026-05-23T00:00:00Z",
                    "from_status": None,
                    "to_status": "draft",
                    "reason": "Initial proposal.",
                }
            ],
        }
    )

    assert loaded == record


def test_status_change_rejects_unknown_fields():
    with pytest.raises(OrganizationEvolutionError, match="unknown fields"):
        evolution_proposal_status_change_from_dict(
            {
                "actor": "zermes_main_agent",
                "changed_at": "2026-05-23T00:00:00Z",
                "from_status": None,
                "to_status": "draft",
                "reason": "Initial proposal.",
                "raw_transcript": "not allowed",
            }
        )

import pytest

from worker_agents.organization_evolution import (
    EVOLUTION_PROPOSAL_SCHEMA_VERSION,
    EvolutionInitiatorKind,
    EvolutionProposalInitiator,
    EvolutionProposalStatus,
    EvolutionProposalType,
    OrganizationEvolutionError,
    OrganizationEvolutionProposal,
    dump_organization_evolution_proposal_json,
    load_organization_evolution_proposal_json,
    organization_evolution_proposal_from_dict,
    organization_evolution_proposal_to_dict,
    validate_evolution_proposal,
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

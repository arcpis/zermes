import pytest

from worker_agents.department_memory import (
    DepartmentMemoryError,
    DepartmentMemoryKind,
    DepartmentMemoryProposal,
    DepartmentMemoryProposalState,
    DepartmentMemoryRecord,
    DepartmentMemorySensitivity,
    DepartmentMemoryVisibility,
    department_memory_dir,
    department_memory_from_dict,
    department_memory_proposal_from_dict,
    department_memory_proposal_to_dict,
    department_memory_to_dict,
    validate_department_memory_payload,
)


def test_department_memory_record_serializes_stable_contract():
    memory = DepartmentMemoryRecord(
        department_id="platform",
        memory_id="delivery-standard",
        kind=DepartmentMemoryKind.DELIVERY_STANDARD,
        summary="Every handoff includes test evidence and known risks.",
        source_refs=("tasks/task_123/summary.json",),
        visibility=DepartmentMemoryVisibility.INHERITABLE_SUMMARY,
        sensitivity=DepartmentMemorySensitivity.INTERNAL,
        accepted_at="2026-05-21T00:00:00Z",
        audit_summary="Accepted by department lead.",
    )

    payload = department_memory_to_dict(memory)
    loaded = department_memory_from_dict(payload)

    assert loaded == memory
    assert list(payload) == [
        "department_id",
        "memory_id",
        "schema_version",
        "kind",
        "summary",
        "source_refs",
        "visibility",
        "sensitivity",
        "revision",
        "active",
        "accepted_at",
        "created_at",
        "updated_at",
        "audit_summary",
    ]


def test_department_memory_proposal_defaults_to_pending():
    proposal = DepartmentMemoryProposal(
        proposal_id="proposal-1",
        department_id="platform",
        kind=DepartmentMemoryKind.RISK,
        candidate_summary="Check downstream chat binding risk before rollout.",
        source_actor="main_agent",
    )

    assert proposal.state == DepartmentMemoryProposalState.PENDING
    assert proposal.sensitivity == DepartmentMemorySensitivity.INTERNAL
    payload = department_memory_proposal_to_dict(proposal)
    assert department_memory_proposal_from_dict(payload) == proposal
    assert payload["candidate_summary"] == (
        "Check downstream chat binding risk before rollout."
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"raw_transcript": "full chat"},
        {"nested": {"secret": "token"}},
        {"items": [{"external_raw_output": "adapter log"}]},
        {"private_memory_text": "worker-only memory"},
    ],
)
def test_department_memory_payload_rejects_sensitive_fields(payload):
    with pytest.raises(DepartmentMemoryError):
        validate_department_memory_payload(payload)


@pytest.mark.parametrize("value", ["../task.json", "/tmp/task.json", r"C:\tmp\task.json"])
def test_department_memory_rejects_unsafe_source_refs(value):
    with pytest.raises(DepartmentMemoryError, match="source_refs"):
        DepartmentMemoryRecord(
            department_id="platform",
            memory_id="memory-1",
            kind=DepartmentMemoryKind.RETROSPECTIVE,
            summary="Keep summary only.",
            source_refs=(value,),
        )


def test_department_memory_rejects_path_like_ids():
    with pytest.raises(ValueError):
        DepartmentMemoryRecord(
            department_id="team/platform",
            memory_id="memory-1",
            kind=DepartmentMemoryKind.RISK,
            summary="Summary.",
        )

    with pytest.raises(DepartmentMemoryError):
        DepartmentMemoryProposal(
            proposal_id="../proposal-1",
            department_id="platform",
            kind=DepartmentMemoryKind.RISK,
            candidate_summary="Summary.",
            source_actor="main_agent",
        )


def test_department_memory_path_stays_in_department_memory_area():
    path = department_memory_dir("/profile/worker_agents", "platform")

    assert path.parts[-4:] == ("organization", "departments", "platform", "memory")
    assert "workers" not in path.parts

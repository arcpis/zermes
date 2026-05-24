import pytest

from worker_agents.department_memory import (
    DepartmentMemoryKind,
    DepartmentMemoryProposal,
    DepartmentMemoryRecord,
    DepartmentMemorySensitivity,
)
from worker_agents.organization_memory_merge import (
    MemoryMergeCandidate,
    MemoryMergeCandidateSourceKind,
    MemoryMergeClassification,
    MemoryMergeDisposition,
    OrganizationMemoryMergeError,
    build_memory_dedup_conflict_report,
    classify_memory_merge_candidate,
    memory_dedup_conflict_report_to_dict,
    memory_merge_candidate_from_department_memory,
    memory_merge_candidate_from_department_proposal,
    memory_merge_candidate_from_historical_summary,
    memory_merge_candidate_from_private_asset_proposal_input,
    memory_merge_classification_result_to_dict,
    validate_memory_merge_candidate_payload,
)
from worker_agents.private_assets import (
    PrivateAssetProposalInput,
    PrivateAssetSensitivity,
)


def test_department_memory_summary_becomes_adoptable_candidate():
    memory = DepartmentMemoryRecord(
        department_id="support",
        memory_id="handoff-standard",
        kind=DepartmentMemoryKind.DELIVERY_STANDARD,
        summary="Escalate billing incidents with customer impact summaries.",
        source_refs=("tasks/task-123/runtime/result.json",),
        sensitivity=DepartmentMemorySensitivity.LOW,
    )

    candidate = memory_merge_candidate_from_department_memory(
        memory,
        target_scope="department:operations",
    )
    result = classify_memory_merge_candidate(candidate)

    assert candidate.source_kind is MemoryMergeCandidateSourceKind.DEPARTMENT_MEMORY
    assert result.classification is MemoryMergeClassification.VALID
    assert result.disposition is MemoryMergeDisposition.ADOPT_CANDIDATE
    assert result.sensitivity is DepartmentMemorySensitivity.LOW
    assert result.source_refs == (
        "departments/support/memory/handoff-standard",
        "tasks/task-123/runtime/result.json",
    )
    assert memory_merge_classification_result_to_dict(result) == {
        "candidate_id": "handoff-standard",
        "source_kind": "department_memory",
        "classification": "valid",
        "disposition": "adopt_candidate",
        "sensitivity": "low",
        "reasons": ["metadata_allows_adoption_candidate"],
        "source_refs": [
            "departments/support/memory/handoff-standard",
            "tasks/task-123/runtime/result.json",
        ],
        "target_scope": "department:operations",
    }


def test_department_proposal_candidate_keeps_pending_reason():
    proposal = DepartmentMemoryProposal(
        proposal_id="proposal-1",
        department_id="support",
        kind=DepartmentMemoryKind.PLAYBOOK_NOTE,
        candidate_summary="Use the refund checklist before promising credits.",
        source_actor="worker-a",
        source_refs=("tasks/task-456/runtime/result.json",),
        sensitivity=DepartmentMemorySensitivity.INTERNAL,
    )

    result = classify_memory_merge_candidate(
        memory_merge_candidate_from_department_proposal(
            proposal,
            target_scope="department:operations",
        )
    )

    assert result.classification is MemoryMergeClassification.VALID
    assert result.disposition is MemoryMergeDisposition.ADOPT_CANDIDATE
    assert "pending_department_proposal" in result.reasons


def test_private_asset_enters_only_as_low_sensitive_proposal_input():
    proposal_input = PrivateAssetProposalInput(
        proposal_input_id="input-1",
        source_worker_id="worker-a",
        source_asset_id="asset-1",
        target_scope="department:operations",
        summary="Worker prefers concise release handoff notes.",
        source_refs=("workers/worker-a/private_assets/summaries/asset-1.json",),
        sensitivity=PrivateAssetSensitivity.LOW,
    )

    candidate = memory_merge_candidate_from_private_asset_proposal_input(
        proposal_input,
        candidate_id="private-summary-1",
    )
    result = classify_memory_merge_candidate(candidate)

    assert candidate.summary == proposal_input.summary
    assert candidate.source_kind is (
        MemoryMergeCandidateSourceKind.PRIVATE_ASSET_PROPOSAL_INPUT
    )
    assert result.sensitivity is DepartmentMemorySensitivity.LOW
    assert result.disposition is MemoryMergeDisposition.ADOPT_CANDIDATE
    assert "private_asset_summary_only" in result.reasons


def test_private_asset_rejects_non_low_sensitive_proposal_input():
    proposal_input = PrivateAssetProposalInput(
        proposal_input_id="input-1",
        source_worker_id="worker-a",
        source_asset_id="asset-1",
        target_scope="department:operations",
        summary="Review-required personal preference.",
        sensitivity=PrivateAssetSensitivity.REVIEW_REQUIRED,
    )

    with pytest.raises(
        OrganizationMemoryMergeError,
        match="private asset proposal input must be low sensitivity",
    ):
        memory_merge_candidate_from_private_asset_proposal_input(
            proposal_input,
            candidate_id="private-summary-1",
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"summary": "safe", "raw_transcript": "full transcript"},
        {"summary": "safe", "nested": {"secret": "token"}},
        {"summary": "safe", "logs": [{"raw_stdout": "complete output"}]},
        {"summary": "safe", "credentials": {"api_key": "redacted"}},
    ],
)
def test_sensitive_payload_fields_are_rejected(payload):
    with pytest.raises(OrganizationMemoryMergeError, match="sensitive field"):
        validate_memory_merge_candidate_payload(payload)


def test_stale_marker_archives_candidate():
    result = classify_memory_merge_candidate(
        MemoryMergeCandidate(
            candidate_id="memory-1",
            source_kind=MemoryMergeCandidateSourceKind.DEPARTMENT_MEMORY,
            source_ref="departments/support/memory/memory-1",
            summary="Old escalation rota.",
            sensitivity=DepartmentMemorySensitivity.LOW,
            freshness="stale",
            target_scope="department:operations",
        )
    )

    assert result.classification is MemoryMergeClassification.STALE
    assert result.disposition is MemoryMergeDisposition.ARCHIVE
    assert "stale_freshness" in result.reasons


def test_sensitive_candidate_requires_redaction_and_confirmation():
    result = classify_memory_merge_candidate(
        MemoryMergeCandidate(
            candidate_id="memory-1",
            source_kind=MemoryMergeCandidateSourceKind.DEPARTMENT_MEMORY,
            source_ref="departments/support/memory/memory-1",
            summary="Restricted operational pattern summary.",
            sensitivity=DepartmentMemorySensitivity.RESTRICTED,
            freshness="current",
            target_scope="department:operations",
        )
    )

    assert result.classification is MemoryMergeClassification.SENSITIVE
    assert result.disposition is MemoryMergeDisposition.REQUIRES_REDACTION
    assert "user_confirmation_required" in result.reasons


def test_sensitive_candidate_requires_redaction_before_duplicate_decision():
    result = classify_memory_merge_candidate(
        MemoryMergeCandidate(
            candidate_id="memory-1",
            source_kind=MemoryMergeCandidateSourceKind.DEPARTMENT_MEMORY,
            source_ref="departments/support/memory/memory-1",
            summary="Restricted summary with a possible duplicate.",
            sensitivity=DepartmentMemorySensitivity.RESTRICTED,
            freshness="current",
            target_scope="department:operations",
            explicit_markers=("duplicate",),
        )
    )

    assert result.classification is MemoryMergeClassification.SENSITIVE
    assert result.disposition is MemoryMergeDisposition.REQUIRES_REDACTION


def test_historical_summary_is_archived_as_reference():
    result = classify_memory_merge_candidate(
        memory_merge_candidate_from_historical_summary(
            candidate_id="history-1",
            source_ref="departments/support/memory/history/memory-1/1.json",
            summary="Previous policy before support merged into operations.",
            target_scope="department:operations",
        )
    )

    assert result.classification is MemoryMergeClassification.HISTORICAL_REFERENCE
    assert result.disposition is MemoryMergeDisposition.ARCHIVE


@pytest.mark.parametrize(
    ("marker", "classification", "disposition", "reason"),
    [
        (
            "duplicate",
            MemoryMergeClassification.DUPLICATE,
            MemoryMergeDisposition.REQUIRES_DECISION,
            "explicit_duplicate_marker",
        ),
        (
            "conflict",
            MemoryMergeClassification.CONFLICT,
            MemoryMergeDisposition.REQUIRES_DECISION,
            "explicit_conflict_marker",
        ),
    ],
)
def test_explicit_duplicate_and_conflict_markers_require_decision(
    marker,
    classification,
    disposition,
    reason,
):
    result = classify_memory_merge_candidate(
        MemoryMergeCandidate(
            candidate_id="memory-1",
            source_kind=MemoryMergeCandidateSourceKind.DEPARTMENT_MEMORY,
            source_ref="departments/support/memory/memory-1",
            summary="Potentially overlapping memory.",
            sensitivity=DepartmentMemorySensitivity.LOW,
            freshness="current",
            target_scope="department:operations",
            explicit_markers=(marker,),
        )
    )

    assert result.classification is classification
    assert result.disposition is disposition
    assert reason in result.reasons


def test_same_source_hash_candidates_enter_duplicate_group_with_all_sources():
    first = MemoryMergeCandidate(
        candidate_id="candidate-1",
        source_kind=MemoryMergeCandidateSourceKind.DEPARTMENT_PROPOSAL,
        source_ref="departments/support/memory/proposals/candidate-1",
        summary="Escalate failed deployments with rollback evidence.",
        sensitivity=DepartmentMemorySensitivity.LOW,
        freshness="current",
        target_scope="department:operations",
        source_refs=("tasks/task-1/result.json",),
        source_hash="sha256:same",
    )
    second = MemoryMergeCandidate(
        candidate_id="candidate-2",
        source_kind=MemoryMergeCandidateSourceKind.DEPARTMENT_PROPOSAL,
        source_ref="departments/release/memory/proposals/candidate-2",
        summary="Escalate failed deployments with rollback evidence.",
        sensitivity=DepartmentMemorySensitivity.LOW,
        freshness="current",
        target_scope="department:operations",
        source_refs=("tasks/task-2/result.json",),
        source_hash="sha256:same",
    )

    report = build_memory_dedup_conflict_report((first, second))

    assert len(report.duplicate_groups) == 1
    duplicate_group = report.duplicate_groups[0]
    assert duplicate_group.candidate_ids == ("candidate-1", "candidate-2")
    assert duplicate_group.reason == "matching_source_hash"
    assert duplicate_group.source_refs == (
        "departments/support/memory/proposals/candidate-1",
        "tasks/task-1/result.json",
        "departments/release/memory/proposals/candidate-2",
        "tasks/task-2/result.json",
    )
    assert report.rejected_candidate_ids == ("candidate-1", "candidate-2")
    assert report.adoptable_candidate_ids == ()


def test_normalized_summary_duplicate_keeps_all_sources():
    first = MemoryMergeCandidate(
        candidate_id="candidate-1",
        source_kind=MemoryMergeCandidateSourceKind.DEPARTMENT_PROPOSAL,
        source_ref="departments/support/memory/proposals/candidate-1",
        summary="Run release checks before handoff.",
        sensitivity=DepartmentMemorySensitivity.LOW,
        freshness="current",
        target_scope="department:operations",
    )
    second = MemoryMergeCandidate(
        candidate_id="candidate-2",
        source_kind=MemoryMergeCandidateSourceKind.DEPARTMENT_PROPOSAL,
        source_ref="departments/release/memory/proposals/candidate-2",
        summary="  run   RELEASE checks before handoff.  ",
        sensitivity=DepartmentMemorySensitivity.LOW,
        freshness="current",
        target_scope="department:operations",
    )

    report = build_memory_dedup_conflict_report((first, second))

    assert len(report.duplicate_groups) == 1
    assert report.duplicate_groups[0].reason == "matching_normalized_summary"
    assert report.duplicate_groups[0].source_refs == (
        "departments/support/memory/proposals/candidate-1",
        "departments/release/memory/proposals/candidate-2",
    )


def test_candidate_duplicate_of_target_memory_rejects_only_candidate():
    target = MemoryMergeCandidate(
        candidate_id="target-memory",
        source_kind=MemoryMergeCandidateSourceKind.DEPARTMENT_MEMORY,
        source_ref="departments/operations/memory/target-memory",
        summary="Run release checks before handoff.",
        sensitivity=DepartmentMemorySensitivity.LOW,
        freshness="current",
        target_scope="department:operations",
    )
    incoming = MemoryMergeCandidate(
        candidate_id="incoming-memory",
        source_kind=MemoryMergeCandidateSourceKind.DEPARTMENT_PROPOSAL,
        source_ref="departments/support/memory/proposals/incoming-memory",
        summary="Run release checks before handoff.",
        sensitivity=DepartmentMemorySensitivity.LOW,
        freshness="current",
        target_scope="department:operations",
    )

    report = build_memory_dedup_conflict_report(
        (incoming,),
        target_candidates=(target,),
    )

    assert report.duplicate_groups[0].candidate_ids == (
        "target-memory",
        "incoming-memory",
    )
    assert report.rejected_candidate_ids == ("incoming-memory",)


def test_same_task_type_opposite_tool_rules_enter_conflict():
    source = MemoryMergeCandidate(
        candidate_id="source-policy",
        source_kind=MemoryMergeCandidateSourceKind.DEPARTMENT_PROPOSAL,
        source_ref="departments/support/memory/proposals/source-policy",
        summary="Release workers may use shell for smoke-test checks.",
        sensitivity=DepartmentMemorySensitivity.LOW,
        freshness="current",
        target_scope="department:operations",
        source_refs=("tasks/source/result.json",),
        policy_type="tool_policy",
        task_type="release_review",
        tool_rule="allow:shell",
    )
    target = MemoryMergeCandidate(
        candidate_id="target-policy",
        source_kind=MemoryMergeCandidateSourceKind.DEPARTMENT_MEMORY,
        source_ref="departments/operations/memory/target-policy",
        summary="Release workers must not use shell during smoke-test checks.",
        sensitivity=DepartmentMemorySensitivity.LOW,
        freshness="current",
        target_scope="department:operations",
        source_refs=("tasks/target/result.json",),
        policy_type="tool_policy",
        task_type="release_review",
        tool_rule="deny:shell",
    )

    report = build_memory_dedup_conflict_report(
        (source,),
        target_candidates=(target,),
        suggested_reviewer="operations_lead",
    )

    assert report.adoptable_candidate_ids == ()
    assert len(report.conflict_items) == 1
    conflict = report.conflict_items[0]
    assert conflict.conflict_field == "tool_rule"
    assert conflict.source_candidate_id == "source-policy"
    assert conflict.target_candidate_id == "target-policy"
    assert conflict.source_summary == source.summary
    assert conflict.target_summary == target.summary
    assert conflict.source_refs == (
        "departments/support/memory/proposals/source-policy",
        "tasks/source/result.json",
        "departments/operations/memory/target-policy",
        "tasks/target/result.json",
    )
    assert conflict.suggested_reviewer == "operations_lead"


def test_stale_candidate_is_reported_for_archive_not_silent_delete():
    stale = MemoryMergeCandidate(
        candidate_id="stale-policy",
        source_kind=MemoryMergeCandidateSourceKind.DEPARTMENT_PROPOSAL,
        source_ref="departments/support/memory/proposals/stale-policy",
        summary="Use the old cutover checklist.",
        sensitivity=DepartmentMemorySensitivity.LOW,
        freshness="expired",
        target_scope="department:operations",
    )

    report = build_memory_dedup_conflict_report((stale,))

    assert report.archive_candidate_ids == ("stale-policy",)
    assert report.rejected_candidate_ids == ()
    assert report.adoptable_candidate_ids == ()
    assert memory_dedup_conflict_report_to_dict(report)["archive_candidate_ids"] == [
        "stale-policy"
    ]

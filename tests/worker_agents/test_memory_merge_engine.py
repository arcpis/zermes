import pytest

from worker_agents.department_memory import DepartmentMemorySensitivity
from worker_agents.organization_memory_merge import (
    MemoryMergeCandidate,
    MemoryMergeCandidateSourceKind,
    MemoryMergeClassification,
    MemoryMergeDisposition,
    OrganizationMemoryMergeError,
    build_memory_dedup_conflict_report,
    build_memory_merge_report,
    classify_memory_merge_candidate,
    validate_memory_merge_candidate_payload,
)


def _candidate(
    candidate_id: str,
    summary: str,
    *,
    sensitivity: DepartmentMemorySensitivity = DepartmentMemorySensitivity.LOW,
    freshness: str = "current",
    source_hash: str | None = None,
    explicit_markers: tuple[str, ...] = (),
    policy_type: str = "",
    task_type: str = "",
    tool_rule: str = "",
) -> MemoryMergeCandidate:
    return MemoryMergeCandidate(
        candidate_id=candidate_id,
        source_kind=MemoryMergeCandidateSourceKind.DEPARTMENT_PROPOSAL,
        source_ref=f"departments/support/memory/proposals/{candidate_id}",
        summary=summary,
        sensitivity=sensitivity,
        freshness=freshness,
        target_scope="department:operations",
        source_hash=source_hash,
        explicit_markers=explicit_markers,
        policy_type=policy_type,
        task_type=task_type,
        tool_rule=tool_rule,
    )


def test_candidate_classification_uses_metadata_without_external_models():
    result = classify_memory_merge_candidate(
        _candidate("handoff-standard", "Use concise customer-impact handoffs.")
    )

    assert result.classification is MemoryMergeClassification.VALID
    assert result.disposition is MemoryMergeDisposition.ADOPT_CANDIDATE
    assert result.source_refs == (
        "departments/support/memory/proposals/handoff-standard",
    )


def test_sensitive_raw_payload_fields_are_rejected_before_planning():
    with pytest.raises(OrganizationMemoryMergeError, match="sensitive field"):
        validate_memory_merge_candidate_payload(
            {
                "summary": "Safe summary.",
                "nested": {"private_memory_text": "raw worker-private text"},
            }
        )


def test_duplicate_group_blocks_duplicate_adoption():
    first = _candidate(
        "release-standard-a",
        "Run smoke checks before release handoff.",
        source_hash="sha256:same",
    )
    second = _candidate(
        "release-standard-b",
        "Run smoke checks before release handoff.",
        source_hash="sha256:same",
    )

    report = build_memory_dedup_conflict_report((first, second))

    assert report.duplicate_groups[0].candidate_ids == (
        "release-standard-a",
        "release-standard-b",
    )
    assert report.rejected_candidate_ids == (
        "release-standard-a",
        "release-standard-b",
    )
    assert report.adoptable_candidate_ids == ()


def test_conflict_item_records_manual_policy_decision():
    source = _candidate(
        "allow-shell",
        "Release workers may use shell for smoke checks.",
        policy_type="tool_policy",
        task_type="release_review",
        tool_rule="allow:shell",
    )
    target = _candidate(
        "deny-shell",
        "Release workers must not use shell for smoke checks.",
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
    assert report.conflict_items[0].conflict_field == "tool_rule"
    assert report.conflict_items[0].suggested_reviewer == "operations_lead"


def test_merge_report_blocks_pending_conflicts_and_redactions():
    report = build_memory_merge_report(
        (
            _candidate(
                "restricted-standard",
                "Restricted operational pattern summary.",
                sensitivity=DepartmentMemorySensitivity.RESTRICTED,
            ),
            _candidate(
                "allow-shell",
                "Release workers may use shell for smoke checks.",
                policy_type="tool_policy",
                task_type="release_review",
                tool_rule="allow:shell",
            ),
        ),
        target_candidates=(
            _candidate(
                "deny-shell",
                "Release workers must not use shell for smoke checks.",
                policy_type="tool_policy",
                task_type="release_review",
                tool_rule="deny:shell",
            ),
        ),
        source_departments=("support",),
        target_department="operations",
        report_id="report-1",
        created_at="2026-05-25T00:00:00Z",
    )

    assert report.has_blockers is True
    assert report.active_write_plan_candidate_refs == ()
    assert report.candidate_counts["redactions"] == 1
    assert report.candidate_counts["conflicts"] == 1

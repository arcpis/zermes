from worker_agents.department_context_selection import (
    DepartmentContextCandidate,
    DepartmentContextSelectionInput,
    select_department_context_assets,
)


def _candidate(
    asset_id: str,
    *,
    department_id: str = "engineering",
    asset_kind: str = "memory",
    summary: str = "Use focused tests for release tasks.",
    sensitivity: str = "low",
    accepted_state: str = "accepted",
    source_refs: tuple[str, ...] = ("departments/engineering/memory/release.json",),
    task_types: tuple[str, ...] = ("release",),
    worker_roles: tuple[str, ...] = ("developer",),
    thread_refs: tuple[str, ...] = (),
    org_refs: tuple[str, ...] = (),
    freshness: str = "fresh",
) -> DepartmentContextCandidate:
    return DepartmentContextCandidate(
        asset_kind=asset_kind,
        asset_id=asset_id,
        department_id=department_id,
        summary=summary,
        sensitivity=sensitivity,
        accepted_state=accepted_state,
        source_refs=source_refs,
        task_types=task_types,
        worker_roles=worker_roles,
        thread_refs=thread_refs,
        org_refs=org_refs,
        freshness=freshness,
        title=asset_id.replace("-", " ").title(),
    )


def _request(
    candidates: tuple[DepartmentContextCandidate, ...],
    **overrides,
) -> DepartmentContextSelectionInput:
    values = {
        "task_ref": "tasks/release-check",
        "task_type": "release",
        "target_department_id": "engineering",
        "department_ancestry": ("platform",),
        "worker_id": "release_worker",
        "worker_role": "developer",
        "asset_candidates": candidates,
        "thread_refs": (),
        "org_refs": (),
        "max_memories": 3,
        "max_skill_guidance": 2,
        "max_total_items": 5,
        "max_summary_chars": 500,
        "sensitivity_ceiling": "internal",
    }
    values.update(overrides)
    return DepartmentContextSelectionInput(**values)


def test_selection_order_is_deterministic_for_same_input():
    candidates = (
        _candidate("b-note", summary="Use release checklist."),
        _candidate("a-note", summary="Use release checklist."),
        _candidate("role-note", summary="Developer release guidance."),
    )

    first = select_department_context_assets(_request(candidates))
    second = select_department_context_assets(_request(tuple(reversed(candidates))))

    assert [item.asset_id for item in first.selected_candidates] == [
        item.asset_id for item in second.selected_candidates
    ]


def test_thread_ref_boosts_priority_without_bypassing_sensitivity():
    explicit = _candidate(
        "explicit",
        sensitivity="restricted",
        thread_refs=("threads/main",),
    )
    normal = _candidate("normal")

    result = select_department_context_assets(
        _request((normal, explicit), thread_refs=("threads/main",))
    )

    assert [item.asset_id for item in result.selected_candidates] == ["normal"]
    assert ("explicit", "sensitivity_ceiling_exceeded") in {
        (item.asset_id, item.reason) for item in result.excluded_candidates
    }


def test_unaccepted_proposal_is_never_selected():
    pending = _candidate("pending", accepted_state="pending")

    result = select_department_context_assets(_request((pending,)))

    assert result.selected_candidates == ()
    assert result.excluded_candidates[0].reason == "unaccepted_proposal"


def test_cross_department_requires_ancestry_or_org_reference():
    unrelated = _candidate("support-note", department_id="support")
    inherited = _candidate("platform-note", department_id="platform")
    org_referenced = _candidate(
        "security-note",
        department_id="security",
        org_refs=("department:security",),
    )

    result = select_department_context_assets(
        _request(
            (unrelated, inherited, org_referenced),
            org_refs=("department:security",),
        )
    )

    assert [item.asset_id for item in result.selected_candidates] == [
        "security-note",
        "platform-note",
    ]
    assert ("support-note", "department_not_in_scope") in {
        (item.asset_id, item.reason) for item in result.excluded_candidates
    }


def test_item_and_summary_limits_are_enforced_with_audit_reasons():
    candidates = (
        _candidate("short", summary="Short release guidance."),
        _candidate("long", summary="x" * 200),
        _candidate("extra", summary="Another release guidance."),
    )

    result = select_department_context_assets(
        _request(candidates, max_memories=1, max_total_items=2, max_summary_chars=80)
    )

    assert [item.asset_id for item in result.selected_candidates] == ["short"]
    assert result.limit_summary.limit_reached is True
    assert set(result.limit_summary.reasons) == {
        "limit_reached",
        "token_budget_pressure",
    }


def test_selection_candidates_do_not_carry_raw_private_fields():
    candidate = _candidate("safe")
    public_fields = set(candidate.__dataclass_fields__)

    assert "raw_transcript" not in public_fields
    assert "private_memory_text" not in public_fields
    assert "unaccepted_proposal_body" not in public_fields

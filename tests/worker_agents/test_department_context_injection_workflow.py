from worker_agents import (
    DepartmentContextBuildInput,
    DepartmentContextCandidate,
    DepartmentContextInjectionLimits,
    DepartmentContextSelectionInput,
    DepartmentToolPolicyContextSnapshot,
    build_department_context_bundle,
    department_context_bundle_to_dict,
    render_department_context_bundle,
    select_department_context_assets,
)
from worker_agents.runtime_boundary import (
    AgentRuntimeLifecycle,
    AgentRuntimePersona,
    AgentRuntimeRole,
    AgentRuntimeSessionConfig,
    AgentRuntimeSessionScope,
    RuntimeBudgetSnapshot,
    RuntimeContextBundle,
    RuntimePermissionSnapshot,
    RuntimeProfileSummary,
)


def _candidate(asset_id, **overrides):
    values = {
        "asset_kind": "memory",
        "asset_id": asset_id,
        "department_id": "engineering",
        "summary": "Use release checklist summaries for release tasks.",
        "source_refs": (f"departments/engineering/assets/{asset_id}.json",),
        "freshness": "fresh",
        "sensitivity": "low",
        "accepted_state": "accepted",
        "task_types": ("release",),
        "worker_roles": ("developer",),
        "title": asset_id.replace("-", " ").title(),
        "constraints": ("summary_only",),
        "guardrail_refs": (f"departments/engineering/guardrails/{asset_id}.json",),
        "audit_refs": (f"audits/{asset_id}.json",),
    }
    values.update(overrides)
    return DepartmentContextCandidate(**values)


def _session_config(department_context=None):
    return AgentRuntimeSessionConfig(
        scope=AgentRuntimeSessionScope.MANAGED_WORKER_TASK,
        persona=AgentRuntimePersona(
            role=AgentRuntimeRole.MANAGED_WORKER,
            lifecycle=AgentRuntimeLifecycle.DURABLE_WORKER,
            display_name="Release Worker",
            responsibility_summary="Run release checks.",
            worker_id="release_worker",
        ),
        profile_summary=RuntimeProfileSummary(worker_id="release_worker"),
        permissions=RuntimePermissionSnapshot(allowed_tool_names=("pytest",)),
        budget=RuntimeBudgetSnapshot(model_policy_ref="worker-default"),
        context=RuntimeContextBundle(
            user_instruction="Run release checks.",
            task_summary="Release check task.",
        ),
        department_context=department_context,
    )


def test_department_context_injection_end_to_end_summary_only():
    candidates = (
        _candidate("release-memory"),
        _candidate(
            "pytest-guidance",
            asset_kind="skill_guidance",
            summary="Run focused pytest cases before broader worker tests.",
        ),
        _candidate("stale-memory", freshness="stale"),
        _candidate("restricted-memory", sensitivity="restricted"),
        _candidate("pending-proposal", accepted_state="pending"),
    )
    selection = select_department_context_assets(
        DepartmentContextSelectionInput(
            task_ref="tasks/release-check",
            task_type="release",
            target_department_id="engineering",
            department_ancestry=("platform",),
            worker_id="release_worker",
            worker_role="developer",
            asset_candidates=candidates,
            sensitivity_ceiling="internal",
        )
    )
    tool_policy = DepartmentToolPolicyContextSnapshot(
        department_id="engineering",
        allowed_tool_summaries=("pytest read-only execution",),
        denied_tool_summaries=("deploy commands denied",),
        approval_required_tool_summaries=("write shell commands pending approval",),
        approval_status_refs=("approvals/write-shell/pending.json",),
        policy_refs=("departments/engineering/tool-policy.json",),
    )
    bundle = build_department_context_bundle(
        DepartmentContextBuildInput(
            task_ref="tasks/release-check",
            target_department_id="engineering",
            worker_id="release_worker",
            selection_result=selection,
            effective_tool_policy_snapshot=tool_policy,
            limits=DepartmentContextInjectionLimits(
                max_memory_items=2,
                max_skill_items=1,
                sensitivity_ceiling="internal",
            ),
            department_ancestry=("platform",),
            audit_trace_ref="traces/release-check/context.json",
            created_at="2026-05-23T00:00:00Z",
        )
    )
    rendered = render_department_context_bundle(bundle)
    config = _session_config(department_context=rendered)
    payload_text = str(department_context_bundle_to_dict(bundle)) + rendered.context_block

    assert config.department_context is rendered
    assert "release-memory" in rendered.context_block
    assert "pytest-guidance" in rendered.context_block
    assert {"freshness_not_allowed", "sensitivity_ceiling_exceeded", "unaccepted_proposal"} <= {
        item.reason for item in bundle.excluded_assets
    }
    for blocked in (
        "secret",
        "credential",
        "token",
        "cookie",
        "env",
        "full transcript",
        "private memory text",
        "private experience text",
        "unaccepted proposal body",
        "raw stdout",
        "raw stderr",
        "external raw output",
    ):
        assert blocked not in payload_text.lower()


def test_session_config_without_department_bundle_keeps_default_behavior():
    first = _session_config()
    second = _session_config()

    assert first.department_context is None
    assert first.context == second.context
    assert first.permissions == second.permissions

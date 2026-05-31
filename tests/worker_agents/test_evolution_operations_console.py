from worker_agents.management import (
    EvolutionWizardInput,
    build_evolution_execution_view,
    build_evolution_proposal_draft,
    build_evolution_proposal_workbench_item,
    evolution_execution_view_to_dict,
    evolution_proposal_draft_to_dict,
    evolution_proposal_workbench_item_to_dict,
    filter_evolution_workbench_items,
)


def test_evolution_workbench_execute_only_for_approved_unblocked_proposals():
    executable = build_evolution_proposal_workbench_item(
        {
            "proposal_kind": "create_child_agent",
            "proposal_id": "proposal-1",
            "status": "approved",
            "target_node_id": "engineering",
            "report_refs": ["reports/proposal-1"],
            "impact_summary": "Creates a worker.",
        }
    )
    blocked = build_evolution_proposal_workbench_item(
        {
            "proposal_kind": "merge_department",
            "proposal_id": "proposal-2",
            "status": "approved",
            "target_node_id": "engineering",
            "blockers": ["rollback plan missing"],
            "impact_summary": "raw secret merge report",
        }
    )

    assert evolution_proposal_workbench_item_to_dict(executable)["can_execute"] is True
    blocked_data = evolution_proposal_workbench_item_to_dict(blocked)
    assert blocked_data["can_execute"] is False
    assert blocked_data["disabled_reason"] == "rollback plan missing"
    assert blocked_data["impact_summary"] == "[redacted summary]"
    assert filter_evolution_workbench_items([executable, blocked], status="approved")


def test_evolution_wizard_drafts_validate_create_delete_merge_archive_inputs():
    create = build_evolution_proposal_draft(
        EvolutionWizardInput(
            proposal_kind="create_child_agent",
            actor_id="lead",
            target_node_id="engineering",
            requested_worker_id="worker-new",
        )
    )
    delete = build_evolution_proposal_draft(
        EvolutionWizardInput(
            proposal_kind="delete_child_agent",
            actor_id="lead",
            target_node_id="worker-node",
        )
    )
    merge = build_evolution_proposal_draft(
        EvolutionWizardInput(
            proposal_kind="merge_department",
            actor_id="lead",
            target_node_id="engineering",
            destination_node_id="platform",
        )
    )
    archive = build_evolution_proposal_draft(
        EvolutionWizardInput(
            proposal_kind="archive_node",
            actor_id="lead",
            target_node_id="legacy",
            active_task_refs=("task-1",),
        )
    )

    assert evolution_proposal_draft_to_dict(create)["proposal_type"] == "create_child_agent"
    assert "asset disposition" in delete.blockers[0]
    assert "rollback plan" in merge.blockers[0]
    assert "active tasks" in archive.blockers[0]


def test_evolution_execution_view_derives_action_availability():
    ready = build_evolution_execution_view(
        {
            "execution_id": "exec-1",
            "proposal_id": "proposal-1",
            "proposal_status": "approved",
            "execution_status": "ready",
            "steps": ["precheck", "apply"],
        }
    )
    running = build_evolution_execution_view(
        {
            "execution_id": "exec-2",
            "proposal_id": "proposal-2",
            "proposal_status": "approved",
            "execution_status": "running",
            "locks": ["organization_tree"],
            "current_step": "apply",
        }
    )
    failed = build_evolution_execution_view(
        {
            "execution_id": "exec-3",
            "proposal_id": "proposal-3",
            "proposal_status": "approved",
            "execution_status": "failed",
            "failed_step": "apply",
            "safe_retry": False,
            "manual_recovery_hint": "raw secret recovery detail",
        }
    )

    assert evolution_execution_view_to_dict(ready)["action_availability"]["execute"] is True
    assert evolution_execution_view_to_dict(running)["locks"] == ["organization_tree"]
    failed_data = evolution_execution_view_to_dict(failed)
    assert failed_data["failed_step"] == "apply"
    assert failed_data["manual_recovery_hint"] == "[redacted summary]"
    assert failed_data["action_availability"]["retry_safe_step"] is False

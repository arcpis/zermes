import pytest

from worker_agents.internal_runtime_context import (
    InternalWorkerRuntimeContextError,
    InternalWorkerRuntimeContextRequest,
    build_internal_worker_runtime_context,
)
from worker_agents.profile import (
    WorkerAgentProfile,
    WorkerBudgetPolicy,
    WorkerExecutionLimits,
    WorkerMemorySettings,
    WorkerModelSettings,
    WorkerSkillSettings,
    WorkerToolPolicy,
    WorkerWorkspacePolicy,
)
from worker_agents.registry import WorkerLifecycleStatus
from worker_agents.registry_service import WorkerRegistryService
from worker_agents.runtime_contract import runtime_request_context_to_dict
from worker_agents.storage import WorkerAgentProfileStore, WorkerAgentRuntimeDataStore
from worker_agents.task_service import WorkerTaskService


def _task_service(tmp_path):
    registry = WorkerRegistryService(
        WorkerAgentProfileStore(tmp_path / "profile" / "worker_agents"),
        now=lambda: "2026-05-21T00:00:00Z",
    )
    return WorkerTaskService.from_registry_service(
        registry,
        runtime_store=WorkerAgentRuntimeDataStore(
            tmp_path / "install" / "data" / "worker_agents"
        ),
    )


def _profile(worker_id="researcher"):
    return WorkerAgentProfile(
        worker_id=worker_id,
        display_name="Researcher",
        description="Research focused questions.",
        role="research",
        responsibilities=("Summarize evidence", "Flag uncertainty"),
        memory=WorkerMemorySettings(enabled=True),
        skills=WorkerSkillSettings(allowed_skill_ids=("research",)),
        tools=WorkerToolPolicy(
            allowed_tools=("read_file", "web_search"),
            approval_required_tools=("web_search",),
        ),
        workspace=WorkerWorkspacePolicy(
            read_roots=("workspace/project",),
            write_roots=("workspace/project/reports",),
        ),
        model=WorkerModelSettings(
            default_model="fast-model",
            context_window_tokens=4000,
        ),
        budgets=WorkerBudgetPolicy(
            max_task_tokens=1000,
            max_turn_tokens=200,
            max_task_cost_usd=0.5,
        ),
        limits=WorkerExecutionLimits(timeout_seconds=120),
    )


def _register_worker(service, *, worker_id="researcher", enable=True):
    service.registry_service.register_worker(profile=_profile(worker_id))
    if enable:
        service.registry_service.enable_worker(worker_id)


def _create_task(service, *, task_id="task-1", worker_id="researcher"):
    return service.create_task(
        task_id=task_id,
        worker_id=worker_id,
        title="Survey",
        objective="Summarize the current state.",
        input_summary="Summarize only the approved thread summary.",
        origin_thread_id="dept-research",
        report_to_thread_id="dept-research",
        budgets={"max_task_tokens": 500, "max_turn_tokens": 100},
        queue=True,
    )


def test_context_builder_returns_minimal_runtime_inputs(tmp_path):
    service = _task_service(tmp_path)
    _register_worker(service)
    _create_task(service)

    context = build_internal_worker_runtime_context(
        service,
        InternalWorkerRuntimeContextRequest(
            worker_id="researcher",
            task_id="task-1",
            thread_summary_refs=("threads/task-1/summary.md",),
            organization_summary_refs=("organization/research/summary.json",),
            artifact_manifest_refs=("manifests/input-brief.json",),
            relevant_excerpts=("Public task excerpt only.",),
        ),
    )

    assert context.worker_record.status == WorkerLifecycleStatus.ENABLED
    assert context.request_context.input_message == (
        "Summarize only the approved thread summary."
    )
    assert context.request_context.thread_summary_refs == (
        "threads/task-1/summary.md",
    )
    assert context.request_context.allowed_tool_descriptions == (
        "read_file: allowed by worker tool policy",
        "web_search: allowed by worker tool policy",
    )
    assert context.request_context.worker_prompt_summary["worker_id"] == "researcher"
    assert context.request_context.worker_prompt_summary["delegation"][
        "delegation_allowed"
    ] is False
    assert context.profile_summary.memory_summary_refs == (
        "workers/researcher/memory/summary.md",
    )
    assert context.permissions.allowed_tool_names == ("read_file", "web_search")
    assert context.session_budget.max_task_tokens == 500
    assert context.execution_budget.max_output_tokens == 100


@pytest.mark.parametrize(
    "status_change",
    ["none", "disable", "archive", "delete"],
)
def test_context_builder_rejects_workers_that_are_not_enabled(tmp_path, status_change):
    service = _task_service(tmp_path)
    _register_worker(service, enable=False)
    if status_change == "disable":
        service.registry_service.disable_worker("researcher")
    elif status_change == "archive":
        service.registry_service.archive_worker("researcher")
    elif status_change == "delete":
        service.registry_service.delete_worker("researcher")

    with pytest.raises(InternalWorkerRuntimeContextError, match="not enabled"):
        build_internal_worker_runtime_context(
            service,
            InternalWorkerRuntimeContextRequest(
                worker_id="researcher",
                task_id="task-1",
            ),
        )


def test_context_builder_rejects_task_for_different_worker(tmp_path):
    service = _task_service(tmp_path)
    _register_worker(service, worker_id="researcher")
    _register_worker(service, worker_id="writer")
    _create_task(service, worker_id="writer")

    with pytest.raises(InternalWorkerRuntimeContextError, match="does not match"):
        build_internal_worker_runtime_context(
            service,
            InternalWorkerRuntimeContextRequest(
                worker_id="researcher",
                task_id="task-1",
            ),
        )


def test_context_builder_omits_full_transcript_and_private_memory_text(tmp_path):
    service = _task_service(tmp_path)
    _register_worker(service)
    _create_task(service)

    context = build_internal_worker_runtime_context(
        service,
        InternalWorkerRuntimeContextRequest(
            worker_id="researcher",
            task_id="task-1",
            relevant_excerpts=("safe excerpt",),
            artifact_manifest_refs=("manifests/input.json",),
        )
    )

    context_data = runtime_request_context_to_dict(context.request_context)
    assert "raw_transcript" not in context_data
    assert "private_memory" not in context_data
    assert "worker_prompt_summary" in context_data
    assert context.session_context.includes_full_transcript is False
    assert context.session_context.includes_private_memory_text is False


def test_context_builder_recomputes_current_reply_thread_prompt_summary(tmp_path):
    service = _task_service(tmp_path)
    _register_worker(service)
    _create_task(service)

    context = build_internal_worker_runtime_context(
        service,
        InternalWorkerRuntimeContextRequest(
            worker_id="researcher",
            task_id="task-1",
            current_thread_id="direct-user-researcher",
            current_thread_summary="Current direct chat summary.",
        ),
    )

    prompt_summary = context.request_context.worker_prompt_summary
    assert prompt_summary["default_reply_thread_id"] == "direct-user-researcher"
    assert prompt_summary["current_thread_summary"] == "Current direct chat summary."


def test_context_builder_injects_worker_wide_active_task_memory(tmp_path):
    service = _task_service(tmp_path)
    _register_worker(service)
    _create_task(service, task_id="task-1")
    service.create_task(
        task_id="task-2",
        worker_id="researcher",
        title="Cross Chat Followup",
        objective="Report findings from another department chat.",
        input_summary="Prepare the followup.",
        origin_thread_id="dept-analysis",
        report_to_thread_id="dept-analysis",
        queue=True,
    )
    service.task_store.save_rolling_summary(
        "task-2",
        "- Found a dependency in the analysis thread.\n",
    )

    context = build_internal_worker_runtime_context(
        service,
        InternalWorkerRuntimeContextRequest(
            worker_id="researcher",
            task_id="task-1",
            current_thread_id="dept-research",
            relevant_excerpts=("Current message excerpt.",),
        ),
    )

    prompt_summary = context.request_context.worker_prompt_summary
    assert [task["task_id"] for task in prompt_summary["active_tasks"]] == [
        "task-1",
        "task-2",
    ]
    assert [task["task_id"] for task in prompt_summary["pending_reports"]] == [
        "task-2",
    ]
    assert any("dept-analysis" in item for item in context.request_context.relevant_excerpts)
    assert any("Found a dependency" in item for item in context.session_context.relevant_excerpts)

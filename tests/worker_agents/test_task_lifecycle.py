import pytest

from worker_agents.task_state import (
    WorkerTaskError,
    WorkerTaskState,
    WorkerTaskStatus,
    transition_task_status,
)


NOW = "2026-05-19T00:00:00Z"


def _state(status=WorkerTaskStatus.DRAFT):
    return WorkerTaskState(
        task_id="task-1",
        worker_id="researcher",
        title="Survey",
        objective="Summarize the current state.",
        created_by="user",
        created_at=NOW,
        updated_at=NOW,
        status=status,
    )


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (WorkerTaskStatus.DRAFT, WorkerTaskStatus.QUEUED),
        (WorkerTaskStatus.QUEUED, WorkerTaskStatus.RUNNING),
        (WorkerTaskStatus.RUNNING, WorkerTaskStatus.WAITING_FOR_INPUT),
        (WorkerTaskStatus.RUNNING, WorkerTaskStatus.WAITING_FOR_APPROVAL),
        (WorkerTaskStatus.WAITING_FOR_INPUT, WorkerTaskStatus.RUNNING),
        (WorkerTaskStatus.WAITING_FOR_APPROVAL, WorkerTaskStatus.QUEUED),
        (WorkerTaskStatus.RUNNING, WorkerTaskStatus.CANCELLING),
        (WorkerTaskStatus.CANCELLING, WorkerTaskStatus.CANCELLED),
        (WorkerTaskStatus.RUNNING, WorkerTaskStatus.FAILED),
        (WorkerTaskStatus.RUNNING, WorkerTaskStatus.SUCCEEDED),
        (WorkerTaskStatus.QUEUED, WorkerTaskStatus.EXPIRED),
    ],
)
def test_task_status_allows_core_transitions(source, target):
    updated = transition_task_status(
        _state(source),
        target,
        updated_by="system",
        status_reason="moving",
        now="2026-05-19T00:01:00Z",
    )

    assert updated.status == target
    assert updated.updated_by == "system"
    assert updated.updated_at == "2026-05-19T00:01:00Z"


@pytest.mark.parametrize(
    "terminal_status",
    [
        WorkerTaskStatus.CANCELLED,
        WorkerTaskStatus.FAILED,
        WorkerTaskStatus.SUCCEEDED,
        WorkerTaskStatus.EXPIRED,
    ],
)
def test_terminal_task_statuses_do_not_restart(terminal_status):
    with pytest.raises(WorkerTaskError, match="Cannot transition"):
        transition_task_status(
            _state(terminal_status),
            WorkerTaskStatus.RUNNING,
            updated_by="system",
            now="2026-05-19T00:01:00Z",
        )


def test_task_status_rejects_unknown_status():
    with pytest.raises(WorkerTaskError, match="Unknown worker task status"):
        _state("mystery")


def test_task_status_records_failure_cancel_and_result_metadata():
    failed = transition_task_status(
        _state(WorkerTaskStatus.RUNNING),
        WorkerTaskStatus.FAILED,
        updated_by="adapter",
        status_reason="runtime crashed",
        now="2026-05-19T00:01:00Z",
    )
    cancelling = transition_task_status(
        _state(WorkerTaskStatus.RUNNING),
        WorkerTaskStatus.CANCELLING,
        updated_by="user",
        status_reason="stop now",
        now="2026-05-19T00:02:00Z",
    )
    succeeded = transition_task_status(
        _state(WorkerTaskStatus.RUNNING),
        WorkerTaskStatus.SUCCEEDED,
        updated_by="adapter",
        status_reason="done",
        now="2026-05-19T00:03:00Z",
        result={"artifact_count": 1},
    )

    assert failed.failure["reason"] == "runtime crashed"
    assert failed.failure["failed_at"] == "2026-05-19T00:01:00Z"
    assert cancelling.cancellation["reason"] == "stop now"
    assert cancelling.cancellation["requested_at"] == "2026-05-19T00:02:00Z"
    assert succeeded.result["summary"] == "done"
    assert succeeded.result["artifact_count"] == 1


def test_task_status_idempotent_update_keeps_existing_fields():
    state = _state(WorkerTaskStatus.RUNNING)

    updated = transition_task_status(
        state,
        WorkerTaskStatus.RUNNING,
        updated_by="adapter",
        status_reason="heartbeat",
        now="2026-05-19T00:01:00Z",
    )

    assert updated.status == WorkerTaskStatus.RUNNING
    assert updated.title == "Survey"
    assert updated.updated_at == "2026-05-19T00:01:00Z"

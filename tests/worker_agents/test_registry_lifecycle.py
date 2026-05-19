import pytest

from worker_agents.registry import (
    WorkerLifecycleStatus,
    WorkerRegistryError,
    WorkerRegistryRecord,
    transition_worker_status,
)


def _record(status):
    return WorkerRegistryRecord(
        worker_id="researcher",
        display_name="Researcher",
        role="research",
        runtime_type="internal",
        status=status,
    )


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (WorkerLifecycleStatus.REGISTERED, WorkerLifecycleStatus.ENABLED),
        (WorkerLifecycleStatus.REGISTERED, WorkerLifecycleStatus.DISABLED),
        (WorkerLifecycleStatus.REGISTERED, WorkerLifecycleStatus.ARCHIVED),
        (WorkerLifecycleStatus.REGISTERED, WorkerLifecycleStatus.DELETED),
        (WorkerLifecycleStatus.ENABLED, WorkerLifecycleStatus.DISABLED),
        (WorkerLifecycleStatus.ENABLED, WorkerLifecycleStatus.ARCHIVED),
        (WorkerLifecycleStatus.ENABLED, WorkerLifecycleStatus.DELETED),
        (WorkerLifecycleStatus.DISABLED, WorkerLifecycleStatus.ENABLED),
        (WorkerLifecycleStatus.DISABLED, WorkerLifecycleStatus.ARCHIVED),
        (WorkerLifecycleStatus.DISABLED, WorkerLifecycleStatus.DELETED),
        (WorkerLifecycleStatus.ARCHIVED, WorkerLifecycleStatus.DISABLED),
    ],
)
def test_worker_lifecycle_allows_expected_transitions(source, target):
    updated = transition_worker_status(
        _record(source),
        target,
        updated_by="main-agent",
        status_reason="maintenance",
        now="2026-05-19T00:00:00Z",
    )

    assert updated.status == target
    assert updated.updated_at == "2026-05-19T00:00:00Z"
    assert updated.updated_by == "main-agent"
    assert updated.status_reason == "maintenance"


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (WorkerLifecycleStatus.ENABLED, WorkerLifecycleStatus.REGISTERED),
        (WorkerLifecycleStatus.DISABLED, WorkerLifecycleStatus.REGISTERED),
        (WorkerLifecycleStatus.ARCHIVED, WorkerLifecycleStatus.ENABLED),
        (WorkerLifecycleStatus.ARCHIVED, WorkerLifecycleStatus.DELETED),
        (WorkerLifecycleStatus.DELETED, WorkerLifecycleStatus.DISABLED),
    ],
)
def test_worker_lifecycle_rejects_disallowed_transitions(source, target):
    with pytest.raises(WorkerRegistryError, match="Cannot transition"):
        transition_worker_status(
            _record(source),
            target,
            updated_by="main-agent",
            now="2026-05-19T00:00:00Z",
        )


def test_worker_lifecycle_same_status_refreshes_audit_metadata():
    updated = transition_worker_status(
        _record(WorkerLifecycleStatus.REGISTERED),
        WorkerLifecycleStatus.REGISTERED,
        updated_by="main-agent",
        status_reason="reviewed",
        now="2026-05-19T00:00:00Z",
    )

    assert updated.status == WorkerLifecycleStatus.REGISTERED
    assert updated.updated_at == "2026-05-19T00:00:00Z"
    assert updated.status_reason == "reviewed"


def test_worker_lifecycle_records_archive_timestamp():
    updated = transition_worker_status(
        _record(WorkerLifecycleStatus.ENABLED),
        WorkerLifecycleStatus.ARCHIVED,
        updated_by="main-agent",
        now="2026-05-19T00:00:00Z",
    )

    assert updated.archived_at == "2026-05-19T00:00:00Z"
    assert updated.deleted_at is None


def test_worker_lifecycle_records_soft_delete_without_asset_path_changes():
    original = _record(WorkerLifecycleStatus.DISABLED)

    updated = transition_worker_status(
        original,
        WorkerLifecycleStatus.DELETED,
        updated_by="main-agent",
        status_reason="no longer needed",
        now="2026-05-19T00:00:00Z",
    )

    assert updated.deleted_at == "2026-05-19T00:00:00Z"
    assert updated.delete_mode == "soft_delete"
    assert updated.profile_path == original.profile_path


def test_worker_lifecycle_deleted_is_terminal():
    with pytest.raises(WorkerRegistryError, match="Cannot transition"):
        transition_worker_status(
            _record(WorkerLifecycleStatus.DELETED),
            WorkerLifecycleStatus.ENABLED,
            updated_by="main-agent",
            now="2026-05-19T00:00:00Z",
        )

import pytest

from worker_agents.private_assets import (
    PrivateAssetError,
    PrivateAssetSensitivity,
    PrivateAssetShareStatus,
    PrivateMemoryRecord,
    department_assets_dir,
    private_memory_to_dict,
    private_memory_to_proposal_input,
    proposal_input_to_dict,
    validate_private_asset_payload,
    worker_private_assets_dir,
)


def test_private_memory_defaults_to_private_only():
    memory = PrivateMemoryRecord(
        worker_id="frontend",
        asset_id="memory-1",
        summary="Prefers focused regression tests for routing changes.",
    )

    assert memory.share_status == PrivateAssetShareStatus.PRIVATE_ONLY
    assert memory.sensitivity == PrivateAssetSensitivity.REVIEW_REQUIRED

    with pytest.raises(PrivateAssetError, match="not eligible"):
        private_memory_to_proposal_input(
            memory,
            proposal_input_id="proposal-1",
            target_scope="department:platform",
        )


def test_shareable_private_memory_becomes_low_sensitivity_proposal_input():
    memory = PrivateMemoryRecord(
        worker_id="frontend",
        asset_id="memory-1",
        summary="Prefer focused tests around message routing changes.",
        source_refs=("tasks/task-123/summary.json",),
        sensitivity=PrivateAssetSensitivity.LOW,
        share_status=PrivateAssetShareStatus.PROPOSAL_ALLOWED,
        audit_summary="No raw transcript included.",
    )

    proposal = private_memory_to_proposal_input(
        memory,
        proposal_input_id="proposal-1",
        target_scope="department:platform",
        content_hash="sha256:abc",
    )

    assert proposal.source_worker_id == "frontend"
    assert proposal.source_asset_id == "memory-1"
    assert proposal.summary == memory.summary
    payload = proposal_input_to_dict(proposal)
    assert payload["content_hash"] == "sha256:abc"
    assert "raw_transcript" not in payload


def test_high_sensitivity_private_memory_cannot_become_proposal_input():
    memory = PrivateMemoryRecord(
        worker_id="frontend",
        asset_id="memory-1",
        summary="Sensitive project context.",
        sensitivity=PrivateAssetSensitivity.HIGH,
        share_status=PrivateAssetShareStatus.PROPOSAL_ALLOWED,
    )

    with pytest.raises(PrivateAssetError, match="high-sensitivity"):
        private_memory_to_proposal_input(
            memory,
            proposal_input_id="proposal-1",
            target_scope="department:platform",
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"raw_transcript": "full conversation"},
        {"nested": {"secret": "token"}},
        {"items": [{"credential": "abc"}]},
    ],
)
def test_private_asset_payload_rejects_explicit_sensitive_fields(payload):
    with pytest.raises(PrivateAssetError):
        validate_private_asset_payload(payload)


@pytest.mark.parametrize("value", ["../task.json", "/tmp/task.json", r"C:\tmp\task.json"])
def test_private_memory_rejects_unsafe_source_refs(value):
    with pytest.raises(PrivateAssetError, match="source_refs"):
        PrivateMemoryRecord(
            worker_id="frontend",
            asset_id="memory-1",
            summary="Summary.",
            source_refs=(value,),
        )


def test_private_memory_rejects_path_like_worker_or_asset_ids():
    with pytest.raises(ValueError):
        PrivateMemoryRecord(
            worker_id="team/frontend",
            asset_id="memory-1",
            summary="Summary.",
        )

    with pytest.raises(PrivateAssetError):
        PrivateMemoryRecord(
            worker_id="frontend",
            asset_id="../memory-1",
            summary="Summary.",
        )


def test_private_and_department_asset_paths_are_separate():
    private_path = worker_private_assets_dir("/profile/worker_agents", "frontend")
    department_path = department_assets_dir("/profile/worker_agents", "platform")

    assert private_path.parts[-3:] == ("workers", "frontend", "private_assets")
    assert department_path.parts[-3:] == ("organization", "departments", "platform")
    assert private_path != department_path


def test_private_memory_dict_is_stable_and_low_sensitivity():
    memory = PrivateMemoryRecord(
        worker_id="frontend",
        asset_id="memory-1",
        summary="Short summary.",
    )

    assert list(private_memory_to_dict(memory)) == [
        "worker_id",
        "asset_id",
        "schema_version",
        "kind",
        "summary",
        "source_refs",
        "sensitivity",
        "share_status",
        "created_at",
        "updated_at",
        "retention_hint",
        "audit_summary",
    ]

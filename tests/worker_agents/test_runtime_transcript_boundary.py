import pytest

from worker_agents.runtime_resources import (
    RuntimeResourceError,
    RuntimeTranscriptKind,
    RuntimeTranscriptPolicy,
    RuntimeTranscriptSink,
    runtime_transcript_audit_summary_to_dict,
    runtime_transcript_ref_to_dict,
    sanitize_runtime_text,
)
from worker_agents.storage import WorkerAgentRuntimeDataStore


def _sink(tmp_path, **policy_overrides):
    return RuntimeTranscriptSink(
        runtime_store=WorkerAgentRuntimeDataStore(tmp_path / "data" / "worker_agents"),
        task_id="task-1",
        runtime_session_id="runtime-1",
        policy=RuntimeTranscriptPolicy(**policy_overrides),
    )


def test_transcript_sink_writes_only_runtime_data_ref(tmp_path):
    sink = _sink(tmp_path)

    ref = sink.write(RuntimeTranscriptKind.RAW_LOG, "Started task.\ntoken=abc123")

    stored_path = tmp_path / "data" / "worker_agents" / ref.relative_path
    assert stored_path.exists()
    assert stored_path.read_text() == "Started task.\ntoken=[redacted]"
    assert runtime_transcript_ref_to_dict(ref)["storage_scope"] == "runtime_data"
    assert "profile" not in ref.relative_path


def test_transcript_sink_rejects_sensitive_labels(tmp_path):
    sink = _sink(tmp_path)

    with pytest.raises(RuntimeResourceError, match="private_memory"):
        sink.write(RuntimeTranscriptKind.RAW_LOG, "private_memory: do not store")


def test_transcript_sink_rejects_durable_asset_file_names(tmp_path):
    sink = _sink(tmp_path)

    with pytest.raises(RuntimeResourceError, match="durable assets"):
        sink.write(RuntimeTranscriptKind.RAW_LOG, "safe text", file_name="memory.txt")


def test_transcript_sink_enforces_raw_and_summary_size_limits(tmp_path):
    raw_sink = _sink(tmp_path, max_raw_bytes=5)
    summary_sink = _sink(tmp_path, max_summary_bytes=5)

    with pytest.raises(RuntimeResourceError, match="byte limit"):
        raw_sink.write(RuntimeTranscriptKind.EXTERNAL_OUTPUT, "too large")
    with pytest.raises(RuntimeResourceError, match="byte limit"):
        summary_sink.write(RuntimeTranscriptKind.COMPACT_SUMMARY, "too large")


def test_transcript_policy_can_disable_raw_transcript(tmp_path):
    sink = _sink(tmp_path, allow_raw_transcript=False)

    with pytest.raises(RuntimeResourceError, match="disabled"):
        sink.write(RuntimeTranscriptKind.RAW_LOG, "raw output")

    summary_ref = sink.write(RuntimeTranscriptKind.COMPACT_SUMMARY, "safe summary")
    assert summary_ref.kind == RuntimeTranscriptKind.COMPACT_SUMMARY


def test_transcript_audit_summary_is_reference_only(tmp_path):
    sink = _sink(tmp_path)
    ref = sink.write(RuntimeTranscriptKind.TOOL_LOG, "Tool call summary only.")

    summary = sink.audit_summary((ref,), safe_summary="Runtime transcript stored.")
    data = runtime_transcript_audit_summary_to_dict(summary)

    assert data["total_bytes"] == ref.byte_count
    assert data["omitted_reason"] == "raw transcript remains in runtime_data"
    assert "Tool call summary only." not in str(data)


def test_sanitizer_redacts_secret_assignments_but_rejects_raw_stdout():
    assert sanitize_runtime_text("secret=value") == "secret=[redacted]"

    with pytest.raises(RuntimeResourceError, match="raw_stdout"):
        sanitize_runtime_text("raw_stdout: full logs")

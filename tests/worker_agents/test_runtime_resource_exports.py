from worker_agents import (
    RuntimeBudgetPolicy,
    RuntimeBudgetSource,
    RuntimeCancellationReason,
    RuntimeCancellationToken,
    RuntimeConcurrencyDecisionKind,
    RuntimeConcurrencyDimension,
    RuntimeConcurrencyGate,
    RuntimeResourceUsage,
    RuntimeTranscriptKind,
    RuntimeTranscriptPolicy,
    RuntimeTranscriptSink,
    resolve_runtime_budget,
    sanitize_runtime_text,
)


def test_runtime_resource_controls_are_available_from_package():
    assert RuntimeBudgetPolicy.__name__ == "RuntimeBudgetPolicy"
    assert RuntimeBudgetSource.DEFAULT_LIMITS.value == "default_limits"
    assert RuntimeResourceUsage(input_tokens=1).total_tokens == 1
    assert RuntimeCancellationToken().cancel(
        RuntimeCancellationReason.USER_REQUESTED,
        requested_by="user",
        requested_at="2026-05-21T00:00:00Z",
        safe_summary="User cancelled.",
    ).cancelled
    assert RuntimeConcurrencyGate.__name__ == "RuntimeConcurrencyGate"
    assert RuntimeConcurrencyDimension.WORKER.value == "worker"
    assert RuntimeConcurrencyDecisionKind.ALLOWED.value == "allowed"
    assert RuntimeTranscriptPolicy.__name__ == "RuntimeTranscriptPolicy"
    assert RuntimeTranscriptSink.__name__ == "RuntimeTranscriptSink"
    assert RuntimeTranscriptKind.RAW_LOG.value == "raw_log"
    assert resolve_runtime_budget.__name__ == "resolve_runtime_budget"
    assert sanitize_runtime_text("token=value") == "token=[redacted]"

from worker_agents.runtime_contract import (
    RuntimeExecutionBudget,
    RuntimeRequest,
    RuntimeRequestContext,
    RuntimeState,
)
from worker_agents.runtime_resources import (
    RuntimeBudgetPolicy,
    RuntimeBudgetSource,
    RuntimeCancellationReason,
    RuntimeCancellationToken,
    RuntimeControlScope,
    RuntimeDeadline,
    RuntimeResourceUsage,
    resolve_runtime_budget,
    runtime_cancellation_error,
    runtime_cancellation_event,
)


class FakeClock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


def _budget():
    return resolve_runtime_budget(
        (),
        defaults=RuntimeBudgetPolicy(
            source=RuntimeBudgetSource.DEFAULT_LIMITS,
            source_ref="defaults",
            max_input_tokens=100,
            max_output_tokens=50,
            max_total_tokens=150,
            max_cost_units=1.0,
            max_wall_time_seconds=30,
            max_output_bytes=1000,
            max_transcript_bytes=2000,
            max_retry_attempts=1,
            max_concurrent_children=1,
        ),
    )


def _runtime_request():
    return RuntimeRequest(
        request_id="runtime-1",
        task_id="task-1",
        worker_id="researcher",
        runtime_type="internal_worker",
        requested_by="main-agent",
        created_at="2026-05-21T00:00:00Z",
        context=RuntimeRequestContext(input_message="Run a bounded task."),
        budget=RuntimeExecutionBudget(
            budget_source="worker-profile:researcher",
            timeout_seconds=30,
        ),
    )


def test_cancellation_token_preserves_first_reason():
    token = RuntimeCancellationToken()
    token = token.cancel(
        RuntimeCancellationReason.USER_REQUESTED,
        requested_by="user",
        requested_at="2026-05-21T00:00:00Z",
        safe_summary="User cancelled the task.",
    )
    token = token.cancel(
        RuntimeCancellationReason.SYSTEM_SHUTDOWN,
        requested_by="system",
        requested_at="2026-05-21T00:00:01Z",
        safe_summary="System is shutting down.",
    )

    assert token.cancelled
    assert token.request.reason == RuntimeCancellationReason.USER_REQUESTED
    assert token.audit_notes == ("System is shutting down.",)


def test_deadline_expiry_marks_scope_cancelled_by_timeout():
    clock = FakeClock(45.0)
    scope = RuntimeControlScope(
        budget=_budget(),
        cancellation_token=RuntimeCancellationToken(),
        deadline=RuntimeDeadline(started_at_seconds=10.0, timeout_seconds=30, now=clock),
    )

    expired_scope = scope.check_deadline()

    assert expired_scope.cancellation_token.request is not None
    assert (
        expired_scope.cancellation_token.request.reason
        == RuntimeCancellationReason.TIMEOUT
    )


def test_budget_exhaustion_marks_scope_cancelled():
    scope = RuntimeControlScope(
        budget=_budget(),
        cancellation_token=RuntimeCancellationToken(),
        usage=RuntimeResourceUsage(input_tokens=101),
    )

    exceeded_scope = scope.check_budget()

    assert exceeded_scope.cancellation_token.request is not None
    assert (
        exceeded_scope.cancellation_token.request.reason
        == RuntimeCancellationReason.BUDGET_EXHAUSTED
    )


def test_cancellation_error_maps_timeout_and_budget_codes():
    timeout = RuntimeCancellationToken().cancel(
        RuntimeCancellationReason.TIMEOUT,
        requested_by="runtime_deadline",
        requested_at="2026-05-21T00:00:00Z",
        safe_summary="Runtime deadline expired.",
    )
    budget = RuntimeCancellationToken().cancel(
        RuntimeCancellationReason.BUDGET_EXHAUSTED,
        requested_by="runtime_budget",
        requested_at="2026-05-21T00:00:00Z",
        safe_summary="Runtime budget exceeded.",
    )

    assert runtime_cancellation_error(timeout.request).code.value == "timed_out"
    assert runtime_cancellation_error(budget.request).code.value == "budget_exceeded"


def test_cancellation_event_is_low_sensitive_terminal_event():
    token = RuntimeCancellationToken().cancel(
        RuntimeCancellationReason.USER_REQUESTED,
        requested_by="user",
        requested_at="2026-05-21T00:00:00Z",
        safe_summary="User cancelled the task.",
    )

    event = runtime_cancellation_event(_runtime_request(), token.request, sequence=3)

    assert event.state == RuntimeState.CANCELLED
    assert event.payload == {
        "reason": "user_requested",
        "requested_by": "user",
        "requested_at": "2026-05-21T00:00:00Z",
        "safe_summary": "User cancelled the task.",
    }

from worker_agents.runtime_resources import (
    RuntimeConcurrencyDecisionKind,
    RuntimeConcurrencyDimension,
    RuntimeConcurrencyGate,
    RuntimeConcurrencyKey,
    RuntimeConcurrencyLimit,
    RuntimeConcurrencyRequest,
    runtime_concurrency_decision_to_dict,
)


def _request(**overrides):
    data = {
        "request_id": "runtime-1",
        "worker_id": "researcher",
        "runtime_type": "temporary_subagent",
        "user_id": "user-1",
        "organization_node_id": "org-research",
        "adapter_id": "delegate-task",
        "parent_runtime_session_id": "parent-session",
    }
    data.update(overrides)
    return RuntimeConcurrencyRequest(**data)


def test_concurrency_gate_acquires_and_releases_worker_lease():
    gate = RuntimeConcurrencyGate()
    limit = RuntimeConcurrencyLimit(
        key=RuntimeConcurrencyKey(RuntimeConcurrencyDimension.WORKER, "researcher"),
        max_active=1,
    )

    decision = gate.try_acquire(_request(), (limit,))

    assert decision.kind == RuntimeConcurrencyDecisionKind.ALLOWED
    assert decision.lease is not None
    assert gate.snapshot()[limit.key] == 1
    assert gate.release(decision.lease)
    assert not gate.release(decision.lease)
    assert gate.snapshot() == {}


def test_concurrency_gate_rejects_worker_over_limit_without_new_lease():
    gate = RuntimeConcurrencyGate()
    limit = RuntimeConcurrencyLimit(
        key=RuntimeConcurrencyKey(RuntimeConcurrencyDimension.WORKER, "researcher"),
        max_active=1,
    )

    first = gate.try_acquire(_request(request_id="runtime-1"), (limit,))
    second = gate.try_acquire(_request(request_id="runtime-2"), (limit,))

    assert first.kind == RuntimeConcurrencyDecisionKind.ALLOWED
    assert second.kind == RuntimeConcurrencyDecisionKind.REJECTED
    assert second.limit_key == limit.key
    assert len(gate.active_leases) == 1


def test_concurrency_gate_can_queue_adapter_over_limit():
    gate = RuntimeConcurrencyGate()
    limit = RuntimeConcurrencyLimit(
        key=RuntimeConcurrencyKey(RuntimeConcurrencyDimension.ADAPTER, "codex-lite"),
        max_active=1,
        decision_kind=RuntimeConcurrencyDecisionKind.QUEUED,
    )

    allowed = gate.try_acquire(
        _request(request_id="runtime-1", adapter_id="codex-lite"),
        (limit,),
    )
    queued = gate.try_acquire(
        _request(request_id="runtime-2", adapter_id="codex-lite"),
        (limit,),
    )

    assert allowed.kind == RuntimeConcurrencyDecisionKind.ALLOWED
    assert queued.kind == RuntimeConcurrencyDecisionKind.QUEUED
    assert runtime_concurrency_decision_to_dict(queued)["retry_after_seconds"] == 30


def test_parent_runtime_session_limit_blocks_extra_temporary_child():
    gate = RuntimeConcurrencyGate()
    limit = RuntimeConcurrencyLimit(
        key=RuntimeConcurrencyKey(
            RuntimeConcurrencyDimension.PARENT_RUNTIME_SESSION,
            "parent-session",
        ),
        max_active=1,
    )

    gate.try_acquire(_request(request_id="runtime-1"), (limit,))
    denied = gate.try_acquire(_request(request_id="runtime-2"), (limit,))

    assert denied.kind == RuntimeConcurrencyDecisionKind.REJECTED
    assert denied.safe_summary.endswith("parent_runtime_session:parent-session.")


def test_different_dimensions_are_counted_independently():
    gate = RuntimeConcurrencyGate()
    worker_limit = RuntimeConcurrencyLimit(
        key=RuntimeConcurrencyKey(RuntimeConcurrencyDimension.WORKER, "researcher"),
        max_active=2,
    )
    adapter_limit = RuntimeConcurrencyLimit(
        key=RuntimeConcurrencyKey(RuntimeConcurrencyDimension.ADAPTER, "codex-lite"),
        max_active=1,
    )

    gate.try_acquire(
        _request(request_id="runtime-1", adapter_id="codex-lite"),
        (worker_limit, adapter_limit),
    )
    denied = gate.try_acquire(
        _request(request_id="runtime-2", adapter_id="codex-lite"),
        (worker_limit, adapter_limit),
    )

    assert denied.limit_key == adapter_limit.key
    assert gate.snapshot()[worker_limit.key] == 1

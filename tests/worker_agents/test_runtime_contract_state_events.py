import pytest

from worker_agents.runtime_contract import (
    RUNTIME_CONTRACT_VERSION,
    RuntimeContractError,
    RuntimeEvent,
    RuntimeEventType,
    RuntimeState,
    RuntimeType,
    dump_runtime_event_json,
    load_runtime_event_json,
    runtime_event_from_dict,
    validate_runtime_event_sequence,
    validate_runtime_state_transition,
)


def _event(sequence=0, state=RuntimeState.RUNNING, event_type=RuntimeEventType.HEARTBEAT):
    return RuntimeEvent(
        event_id=f"runtime_event_{sequence}",
        request_id="runtime_req_123",
        task_id="task_123",
        worker_id="frontend",
        runtime_type=RuntimeType.INTERNAL_WORKER,
        state=state,
        event_type=event_type,
        created_at="2026-05-21T00:00:00Z",
        sequence=sequence,
        payload={"summary": "Still working."},
    )


def test_runtime_state_transition_accepts_allowed_edges():
    previous, next_ = validate_runtime_state_transition(
        RuntimeState.QUEUED, RuntimeState.STARTING
    )

    assert previous == RuntimeState.QUEUED
    assert next_ == RuntimeState.STARTING


def test_runtime_state_transition_rejects_terminal_edges():
    with pytest.raises(RuntimeContractError, match="succeeded to running"):
        validate_runtime_state_transition(RuntimeState.SUCCEEDED, RuntimeState.RUNNING)


def test_runtime_event_json_round_trip():
    event = RuntimeEvent(
        event_id="runtime_event_1",
        request_id="runtime_req_123",
        task_id="task_123",
        worker_id="frontend",
        runtime_type=RuntimeType.INTERNAL_WORKER,
        state=RuntimeState.RUNNING,
        event_type=RuntimeEventType.OUTPUT_CHUNK,
        created_at="2026-05-21T00:00:00Z",
        sequence=1,
        payload={"text": "A low-sensitive progress excerpt."},
    )

    loaded = load_runtime_event_json(dump_runtime_event_json(event))

    assert loaded == event
    assert loaded.contract_version == RUNTIME_CONTRACT_VERSION


def test_runtime_event_rejects_event_type_state_mismatch():
    with pytest.raises(RuntimeContractError, match="output_chunk"):
        RuntimeEvent(
            event_id="runtime_event_1",
            request_id="runtime_req_123",
            task_id="task_123",
            worker_id="frontend",
            runtime_type=RuntimeType.INTERNAL_WORKER,
            state=RuntimeState.SUCCEEDED,
            event_type=RuntimeEventType.OUTPUT_CHUNK,
            created_at="2026-05-21T00:00:00Z",
            sequence=1,
            payload={"text": "too late"},
        )


def test_runtime_event_sequence_rejects_events_after_terminal_state():
    events = (
        _event(sequence=0, state=RuntimeState.RUNNING),
        _event(
            sequence=1,
            state=RuntimeState.SUCCEEDED,
            event_type=RuntimeEventType.COMPLETED,
        ),
        _event(sequence=2, state=RuntimeState.RUNNING),
    )

    with pytest.raises(RuntimeContractError, match="terminal state"):
        validate_runtime_event_sequence(events)


def test_runtime_event_sequence_rejects_duplicate_sequence():
    events = (_event(sequence=0), _event(sequence=0))

    with pytest.raises(RuntimeContractError, match="duplicate"):
        validate_runtime_event_sequence(events)


def test_runtime_event_rejects_sensitive_payload():
    with pytest.raises(RuntimeContractError, match="raw_stdout"):
        runtime_event_from_dict(
            {
                "contract_version": RUNTIME_CONTRACT_VERSION,
                "event_id": "runtime_event_1",
                "request_id": "runtime_req_123",
                "task_id": "task_123",
                "worker_id": "frontend",
                "runtime_type": "internal_worker",
                "state": "running",
                "event_type": "output_chunk",
                "created_at": "2026-05-21T00:00:00Z",
                "sequence": 1,
                "payload": {"raw_stdout": "secret process log"},
            }
        )

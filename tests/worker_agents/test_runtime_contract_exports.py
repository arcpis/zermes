from worker_agents import (
    RUNTIME_CONTRACT_VERSION,
    RuntimeContractError,
    RuntimeEvent,
    RuntimeRequest,
    RuntimeResult,
    RuntimeState,
    RuntimeType,
    validate_runtime_state_transition,
)


def test_runtime_contract_is_available_from_worker_agents_package():
    assert RUNTIME_CONTRACT_VERSION == 1
    assert RuntimeContractError.__name__ == "RuntimeContractError"
    assert RuntimeRequest.__name__ == "RuntimeRequest"
    assert RuntimeEvent.__name__ == "RuntimeEvent"
    assert RuntimeResult.__name__ == "RuntimeResult"
    assert RuntimeType.INTERNAL_WORKER.value == "internal_worker"
    assert RuntimeState.QUEUED.value == "queued"

    previous, next_ = validate_runtime_state_transition("queued", "starting")

    assert previous == RuntimeState.QUEUED
    assert next_ == RuntimeState.STARTING

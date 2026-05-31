from worker_agents import (
    InternalWorkerRuntimeContextRequest,
    InternalWorkerRuntimeRunner,
    finalize_internal_runtime_result,
    RUNTIME_CONTRACT_VERSION,
    RuntimeContractError,
    RuntimeEvent,
    RuntimeRequest,
    RuntimeResult,
    RuntimeState,
    RuntimeType,
    TemporarySubagentProfileOverlay,
    TemporarySubagentRequest,
    TemporarySubagentRunner,
    evaluate_temporary_subagent_policy,
    run_temporary_subagent,
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


def test_internal_runtime_api_is_available_from_worker_agents_package():
    assert InternalWorkerRuntimeContextRequest.__name__ == (
        "InternalWorkerRuntimeContextRequest"
    )
    assert InternalWorkerRuntimeRunner.__name__ == "InternalWorkerRuntimeRunner"
    assert finalize_internal_runtime_result.__name__ == (
        "finalize_internal_runtime_result"
    )


def test_temporary_subagent_api_is_available_from_worker_agents_package():
    assert TemporarySubagentProfileOverlay.__name__ == (
        "TemporarySubagentProfileOverlay"
    )
    assert TemporarySubagentRequest.__name__ == "TemporarySubagentRequest"
    assert TemporarySubagentRunner.__name__ == "TemporarySubagentRunner"
    assert evaluate_temporary_subagent_policy.__name__ == (
        "evaluate_temporary_subagent_policy"
    )
    assert run_temporary_subagent.__name__ == "run_temporary_subagent"

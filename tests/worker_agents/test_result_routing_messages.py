import pytest

from worker_agents.message_router import MessageRouter
from worker_agents.result_routing import (
    ResultRoutingError,
    classify_runtime_result,
    message_router_result_route_to_dict,
    route_user_visible_result_messages,
)
from worker_agents.runtime_contract import (
    RuntimeErrorCode,
    RuntimeErrorInfo,
    RuntimeResult,
    RuntimeState,
    RuntimeType,
)


def _successful_result(runtime_type=RuntimeType.INTERNAL_WORKER):
    return RuntimeResult(
        request_id="runtime_req_123",
        task_id="task_123",
        worker_id="frontend",
        runtime_type=runtime_type,
        final_state=RuntimeState.SUCCEEDED,
        started_at="2026-05-21T00:00:00Z",
        completed_at="2026-05-21T00:10:00Z",
        public_message="Implementation is complete.",
        internal_summary="Keep this in task audit only.",
    )


def _failed_result():
    return RuntimeResult(
        request_id="runtime_req_123",
        task_id="task_123",
        worker_id="frontend",
        runtime_type=RuntimeType.EXTERNAL_ADAPTER,
        final_state=RuntimeState.FAILED,
        started_at="2026-05-21T00:00:00Z",
        completed_at="2026-05-21T00:10:00Z",
        internal_summary="External adapter failed.",
        error=RuntimeErrorInfo(
            code=RuntimeErrorCode.OUTPUT_PARSE_ERROR,
            message="Adapter output could not be parsed.",
            safe_summary="The adapter returned malformed structured output.",
            retryable=False,
            source="external_adapter",
            created_at="2026-05-21T00:10:00Z",
            raw_error_ref="tasks/task_123/runtime-error.log",
        ),
    )


def test_routes_public_message_through_direct_thread():
    router = MessageRouter()
    router.create_direct_thread(
        thread_id="thread_123",
        user_id="user_123",
        worker_id="frontend",
    )
    classification = classify_runtime_result(_successful_result())

    routed = route_user_visible_result_messages(
        router=router,
        classification=classification,
        thread_id="thread_123",
        created_at="2026-05-21T00:11:00Z",
    )

    assert len(routed.delivered_messages) == 1
    assert routed.delivered_messages[0].body_preview == "Implementation is complete."
    assert len(router.get_thread_messages("thread_123")) == 1
    assert message_router_result_route_to_dict(routed)["delivered_message_ids"] == [
        "runtime_req_123-public_message-1-message"
    ]


def test_routes_failure_report_as_user_visible_summary():
    router = MessageRouter()
    router.create_direct_thread(
        thread_id="thread_123",
        user_id="user_123",
        worker_id="frontend",
    )
    classification = classify_runtime_result(_failed_result())

    routed = route_user_visible_result_messages(
        router=router,
        classification=classification,
        thread_id="thread_123",
        created_at="2026-05-21T00:11:00Z",
    )

    assert len(routed.delivered_messages) == 1
    assert routed.delivered_messages[0].body_preview == (
        "The adapter returned malformed structured output."
    )


def test_group_message_requires_main_agent_thread_policy():
    router = MessageRouter()
    router.create_group_thread(
        thread_id="thread_123",
        user_id="user_123",
        worker_ids=("frontend",),
    )
    classification = classify_runtime_result(_successful_result())

    routed = route_user_visible_result_messages(
        router=router,
        classification=classification,
        thread_id="thread_123",
        created_at="2026-05-21T00:11:00Z",
    )

    assert routed.delivered_messages[0].thread_id == "thread_123"


def test_temporary_runtime_result_uses_parent_worker_sender():
    router = MessageRouter()
    router.create_direct_thread(
        thread_id="thread_123",
        user_id="user_123",
        worker_id="frontend",
    )
    result = _successful_result(runtime_type=RuntimeType.TEMPORARY_SUBAGENT)
    classification = classify_runtime_result(result)

    routed = route_user_visible_result_messages(
        router=router,
        classification=classification,
        thread_id="thread_123",
        created_at="2026-05-21T00:11:00Z",
        parent_worker_id="frontend",
    )

    assert routed.delivered_messages[0].sender.participant_id == "frontend"


def test_message_router_rejection_becomes_result_routing_error():
    router = MessageRouter()
    router.create_direct_thread(
        thread_id="thread_123",
        user_id="user_123",
        worker_id="backend",
    )
    classification = classify_runtime_result(_successful_result())

    with pytest.raises(ResultRoutingError, match="sender must be a thread participant"):
        route_user_visible_result_messages(
            router=router,
            classification=classification,
            thread_id="thread_123",
            created_at="2026-05-21T00:11:00Z",
        )

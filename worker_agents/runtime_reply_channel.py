"""Bridge user-present chat messages to worker runtime replies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from .message_router import (
    ChatParticipantKind,
    MessageRouter,
    WorkerChatThread,
    WorkerMessageEnvelope,
    chat_participant_to_dict,
)
from .result_routing import (
    MessageRouterResultRoute,
    classify_runtime_result,
    route_user_visible_result_messages,
)
from .runtime_contract import (
    RuntimeErrorCode,
    RuntimeErrorInfo,
    RuntimeExecutionBudget,
    RuntimeRequest,
    RuntimeRequestContext,
    RuntimeResult,
    RuntimeState,
    RuntimeType,
    utc_timestamp,
)


class RuntimeReplyChannelError(ValueError):
    """Raised when a chat message cannot be bridged to a worker runtime reply."""


RuntimeReplyHandler = Callable[[RuntimeRequest], RuntimeResult | None]


@dataclass(frozen=True)
class RuntimeReplyDispatch:
    """Low-sensitive record of one chat-triggered runtime dispatch."""

    runtime_request: RuntimeRequest
    source_thread_id: str
    source_message_id: str
    target_worker_id: str
    delivered_messages: tuple[WorkerMessageEnvelope, ...] = ()
    skipped_route_item_ids: tuple[str, ...] = ()


def build_runtime_request_from_chat_message(
    *,
    thread: WorkerChatThread,
    source_message: WorkerMessageEnvelope,
    target_worker_id: str,
    created_at: str,
    request_id: str | None = None,
) -> RuntimeRequest:
    """Build a runtime request from only low-sensitive managed chat fields."""

    if source_message.thread_id != thread.thread_id:
        raise RuntimeReplyChannelError("source message must belong to the source thread")
    if target_worker_id not in _worker_ids_in_thread(thread):
        raise RuntimeReplyChannelError("target worker must belong to the source thread")
    target_summary = _target_context_summary(thread, target_worker_id)
    source_ref = f"worker_agents/threads/{thread.thread_id}/messages/{source_message.message_id}"
    return RuntimeRequest(
        request_id=request_id or f"runtime-{source_message.message_id}-{target_worker_id}",
        task_id=f"chat-{source_message.message_id}",
        worker_id=target_worker_id,
        runtime_type=RuntimeType.INTERNAL_WORKER,
        requested_by=_participant_ref_text(source_message.sender),
        created_at=created_at,
        context=RuntimeRequestContext(
            input_message=source_message.body_preview,
            source_thread_id=thread.thread_id,
            source_message_refs=(source_ref,),
            source_sender_ref=_participant_ref_text(source_message.sender),
            target_context_summary=target_summary,
            thread_summary_refs=(f"worker_agents/threads/{thread.thread_id}/summary",),
            relevant_excerpts=(_source_message_excerpt(source_message),),
            redaction_policy_ref="worker-chat-runtime:message-preview-only",
        ),
        budget=RuntimeExecutionBudget(
            budget_source=f"worker-chat:{thread.thread_id}:{target_worker_id}",
            max_output_tokens=1000,
            max_output_bytes=8000,
            timeout_seconds=120,
        ),
        session_ref=f"worker_agents/threads/{thread.thread_id}/runtime/{source_message.message_id}/{target_worker_id}",
    )


def route_runtime_reply_to_source_thread(
    *,
    router: MessageRouter,
    runtime_result: RuntimeResult,
    source_thread_id: str,
    created_at: str,
    parent_worker_id: str | None = None,
) -> MessageRouterResultRoute:
    """Route public runtime output back through the managed source thread."""

    classification = classify_runtime_result(runtime_result)
    return route_user_visible_result_messages(
        router=router,
        classification=classification,
        thread_id=source_thread_id,
        created_at=created_at,
        parent_worker_id=parent_worker_id,
    )


def dispatch_chat_message_to_worker_runtime(
    *,
    router: MessageRouter,
    thread: WorkerChatThread,
    source_message: WorkerMessageEnvelope,
    target_worker_id: str,
    reply_handler: RuntimeReplyHandler,
    created_at: str | None = None,
) -> RuntimeReplyDispatch:
    """Run a chat-triggered runtime reply handler and route its public result."""

    timestamp = created_at or utc_timestamp()
    runtime_request = build_runtime_request_from_chat_message(
        thread=thread,
        source_message=source_message,
        target_worker_id=target_worker_id,
        created_at=timestamp,
    )
    try:
        runtime_result = reply_handler(runtime_request)
    except Exception as exc:  # noqa: BLE001 - failures must be user-visible here.
        runtime_result = _failure_result_from_exception(runtime_request, exc, timestamp)
    if runtime_result is None:
        return RuntimeReplyDispatch(
            runtime_request=runtime_request,
            source_thread_id=thread.thread_id,
            source_message_id=source_message.message_id,
            target_worker_id=target_worker_id,
        )

    routed = route_runtime_reply_to_source_thread(
        router=router,
        runtime_result=runtime_result,
        source_thread_id=thread.thread_id,
        created_at=timestamp,
        parent_worker_id=target_worker_id
        if runtime_result.runtime_type == RuntimeType.TEMPORARY_SUBAGENT
        else None,
    )
    return RuntimeReplyDispatch(
        runtime_request=runtime_request,
        source_thread_id=thread.thread_id,
        source_message_id=source_message.message_id,
        target_worker_id=target_worker_id,
        delivered_messages=routed.delivered_messages,
        skipped_route_item_ids=routed.skipped_route_item_ids,
    )


def runtime_reply_dispatch_to_dict(dispatch: RuntimeReplyDispatch) -> dict[str, object]:
    """Return a low-sensitive dispatch summary for product action responses."""

    return {
        "request_id": dispatch.runtime_request.request_id,
        "task_id": dispatch.runtime_request.task_id,
        "source_thread_id": dispatch.source_thread_id,
        "source_message_id": dispatch.source_message_id,
        "target_worker_id": dispatch.target_worker_id,
        "source_message_refs": list(dispatch.runtime_request.context.source_message_refs),
        "delivered_message_ids": [
            message.message_id for message in dispatch.delivered_messages
        ],
        "skipped_route_item_ids": list(dispatch.skipped_route_item_ids),
    }


def target_worker_ids_for_chat_message(
    thread: WorkerChatThread, message: WorkerMessageEnvelope
) -> tuple[str, ...]:
    """Return workers that can consume a message without leaving its thread."""

    explicit_workers = tuple(
        ref.participant_id
        for ref in message.recipient_scope.participant_refs
        if ref.kind == ChatParticipantKind.WORKER
    )
    if explicit_workers:
        return explicit_workers
    thread_workers = tuple(
        ref.participant_id
        for ref in thread.participants
        if ref.kind == ChatParticipantKind.WORKER
    )
    if len(thread_workers) == 1:
        return thread_workers
    return ()


def _worker_ids_in_thread(thread: WorkerChatThread) -> tuple[str, ...]:
    return tuple(
        ref.participant_id
        for ref in thread.participants
        if ref.kind == ChatParticipantKind.WORKER
    )


def _failure_result_from_exception(
    request: RuntimeRequest, exc: Exception, timestamp: str
) -> RuntimeResult:
    safe_summary = "Worker runtime could not produce a reply for this message."
    return RuntimeResult(
        request_id=request.request_id,
        task_id=request.task_id,
        worker_id=request.worker_id,
        runtime_type=request.runtime_type,
        final_state=RuntimeState.FAILED,
        started_at=request.created_at,
        completed_at=timestamp,
        internal_summary=f"Runtime reply handler failed: {type(exc).__name__}",
        error=RuntimeErrorInfo(
            code=RuntimeErrorCode.NON_RETRYABLE,
            message=type(exc).__name__,
            safe_summary=safe_summary,
            retryable=False,
            source="worker_chat_runtime_reply",
            created_at=timestamp,
        ),
    )


def _target_context_summary(thread: WorkerChatThread, target_worker_id: str) -> str:
    participant_counts: dict[str, int] = {}
    for participant in thread.participants:
        participant_counts[participant.kind.value] = (
            participant_counts.get(participant.kind.value, 0) + 1
        )
    return (
        f"Reply as worker {target_worker_id} in {thread.thread_type.value} "
        f"thread {thread.thread_id}. Participant counts: {participant_counts}."
    )


def _source_message_excerpt(message: WorkerMessageEnvelope) -> str:
    return (
        f"Message {message.message_id} from {_participant_ref_text(message.sender)}: "
        f"{message.body_preview}"
    )


def _participant_ref_text(participant: object) -> str:
    if hasattr(participant, "kind") and hasattr(participant, "participant_id"):
        data = chat_participant_to_dict(participant)  # type: ignore[arg-type]
        return f"{data['kind']}:{data['participant_id']}"
    if isinstance(participant, Mapping):
        return f"{participant.get('kind')}:{participant.get('participant_id')}"
    raise RuntimeReplyChannelError("participant reference is invalid")

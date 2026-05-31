#!/usr/bin/env python3
"""Worker Agent messaging tools for the main agent.

Provides three tools that let the main agent dispatch tasks to Worker Agents
through the default group chat thread and check for replies:

- ``send_worker_message``  — post a task to the group chat, @mention workers
- ``check_worker_replies`` — scan for new Worker replies since last check
- ``wait_for_worker_reply`` — block until a Worker responds (or timeout)

These tools write and read the same ``messages.jsonl`` files used by the
existing Worker Agents product layer, so chat history is shared across
interfaces.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

from hermes_constants import get_hermes_home
from worker_agents.message_router import (
    ChatMessageType,
    ChatParticipantKind,
    ChatParticipantRef,
    ChatRecipientScope,
    MessageDeliveryStatus,
    MessageVisibility,
    WorkerMessageEnvelope,
    message_envelope_from_dict,
    message_envelope_to_dict,
)
from worker_agents.organization import MAIN_AGENT_ID
from worker_agents.storage.safe_paths import validate_single_path_segment

from tools.worker_task_state import (
    add_pending_task,
    get_pending_task_summaries,
    load_read_cursor,
    mark_task_completed,
    save_read_cursor,
)

logger = logging.getLogger(__name__)

DEFAULT_GROUP_THREAD_ID = "thread-default-group"
_WAIT_POLL_INTERVAL_SECONDS = 3.0


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _generate_message_id() -> str:
    return f"msg-{uuid.uuid4().hex[:16]}"


def _generate_task_id() -> str:
    return f"task-{uuid.uuid4().hex[:12]}"


def _thread_messages_path(thread_id: str) -> Path:
    """Return the path to the messages.jsonl file for a thread."""
    validate_single_path_segment(thread_id, "thread_id")
    return get_hermes_home() / "worker_agents" / "threads" / thread_id / "messages.jsonl"


def _read_thread_messages(thread_id: str) -> list[WorkerMessageEnvelope]:
    """Read all messages from a thread's messages.jsonl file."""
    path = _thread_messages_path(thread_id)
    if not path.exists():
        return []
    messages: list[WorkerMessageEnvelope] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            messages.append(message_envelope_from_dict(json.loads(stripped)))
        except Exception:
            logger.debug("Skipping unparseable message line in %s", path)
    return messages


def _append_thread_message(message: WorkerMessageEnvelope) -> None:
    """Append a message envelope to a thread's messages.jsonl file."""
    path = _thread_messages_path(message.thread_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(message_envelope_to_dict(message), sort_keys=True) + "\n")


def _filter_new_messages(
    all_messages: list[WorkerMessageEnvelope],
    last_read_id: Optional[str],
) -> list[WorkerMessageEnvelope]:
    """Return messages that arrived after *last_read_id*.

    If *last_read_id* is None, all messages are considered new (first-read).
    """
    if last_read_id is None:
        return list(all_messages)
    new_messages: list[WorkerMessageEnvelope] = []
    found_last = False
    for msg in all_messages:
        if not found_last:
            if msg.message_id == last_read_id:
                found_last = True
            continue
        new_messages.append(msg)
    return new_messages


def _find_worker_responses(
    messages: list[WorkerMessageEnvelope],
    require_mention: bool = False,
) -> list[WorkerMessageEnvelope]:
    """Filter messages to only those sent by Worker participants."""
    result: list[WorkerMessageEnvelope] = []
    for msg in messages:
        if msg.sender.kind != ChatParticipantKind.WORKER:
            continue
        if require_mention and msg.message_type != ChatMessageType.MENTION:
            continue
        result.append(msg)
    return result


def _messages_to_response_list(
    messages: list[WorkerMessageEnvelope],
) -> list[dict[str, Any]]:
    """Convert message envelopes to a compact JSON-serializable list."""
    return [
        {
            "message_id": msg.message_id,
            "sender": f"worker:{msg.sender.participant_id}",
            "type": msg.message_type.value,
            "body_preview": msg.body_preview,
            "created_at": msg.created_at,
        }
        for msg in messages
    ]


def _auto_complete_tasks(
    thread_id: str,
    new_replies: list[WorkerMessageEnvelope],
) -> list[str]:
    """Mark any pending tasks as completed when a Worker reply is detected.

    Matches tasks by thread_id: any pending task in this thread is considered
    completed when any Worker reply arrives.

    Returns the list of task_ids that were completed.
    """
    if not new_replies:
        return []
    from tools.worker_task_state import load_task_state, save_task_state

    state = load_task_state()
    completed_ids: list[str] = []
    reply_message_ids = tuple(msg.message_id for msg in new_replies)
    updated_tasks: list = []
    for task in state.pending_tasks:
        if task.status == "pending" and task.thread_id == thread_id:
            updated_tasks.append(
                task.__class__(
                    task_id=task.task_id,
                    thread_id=task.thread_id,
                    dispatched_to=task.dispatched_to,
                    task_summary=task.task_summary,
                    dispatched_at=task.dispatched_at,
                    status="completed",
                    result_message_ids=reply_message_ids,
                )
            )
            completed_ids.append(task.task_id)
        else:
            updated_tasks.append(task)
    state.pending_tasks = tuple(updated_tasks)
    save_task_state(state)
    return completed_ids


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


def _handle_send_worker_message(args: dict[str, Any]) -> str:
    """Post a task message to the default group chat, @mentioning target workers.

    This is the primary dispatch mechanism.  The main agent writes a message
    to the group chat thread and records a pending task in the structured
    task state store.  Worker Agents pick up the message via their own
    message-read loop.
    """
    thread_id = args.get("thread_id", DEFAULT_GROUP_THREAD_ID)
    text = args.get("text", "")
    mention_worker_ids = tuple(args.get("mention_worker_ids", ()))

    if not text.strip():
        return json.dumps({"error": "text must not be empty"}, ensure_ascii=False)

    message_id = _generate_message_id()
    sender = ChatParticipantRef(ChatParticipantKind.MAIN_AGENT, MAIN_AGENT_ID)
    participant_refs = tuple(
        ChatParticipantRef(ChatParticipantKind.WORKER, wid)
        for wid in mention_worker_ids
    )
    message_type = ChatMessageType.MENTION if mention_worker_ids else ChatMessageType.NORMAL

    envelope = WorkerMessageEnvelope(
        message_id=message_id,
        thread_id=thread_id,
        sender=sender,
        recipient_scope=ChatRecipientScope(
            participant_refs=participant_refs,
            include_entire_thread=True,
        ),
        message_type=message_type,
        created_at=_now_iso(),
        delivery_status=MessageDeliveryStatus.CREATED,
        visibility=MessageVisibility.THREAD,
        body_preview=text[:500],
        audit_summary=f"Main agent dispatched task to {', '.join(mention_worker_ids) if mention_worker_ids else 'all workers'}.",
    )

    _append_thread_message(envelope)

    task_id = _generate_task_id()
    dispatched_to = ",".join(mention_worker_ids) if mention_worker_ids else "all"
    add_pending_task(
        task_id=task_id,
        thread_id=thread_id,
        dispatched_to=dispatched_to,
        task_summary=text[:200],
    )

    return json.dumps(
        {
            "status": "dispatched",
            "message_id": message_id,
            "task_id": task_id,
            "dispatched_to": list(mention_worker_ids) if mention_worker_ids else ["all"],
            "task_summary": text[:200],
        },
        ensure_ascii=False,
    )


def _handle_check_worker_replies(args: dict[str, Any]) -> str:
    """Check for new Worker Agent replies in the group chat thread.

    Reads the thread's messages.jsonl, compares against the stored read
    cursor, and returns any new messages sent by Worker participants.
    Pending tasks in the same thread are automatically marked completed
    when Worker replies are detected.
    """
    thread_id = args.get("thread_id", DEFAULT_GROUP_THREAD_ID)

    cursor = load_read_cursor(thread_id)
    all_messages = _read_thread_messages(thread_id)
    new_messages = _filter_new_messages(all_messages, cursor.last_read_message_id)
    worker_replies = _find_worker_responses(new_messages)

    completed_ids = _auto_complete_tasks(thread_id, worker_replies)

    if all_messages:
        save_read_cursor(thread_id, all_messages[-1].message_id)

    pending = get_pending_task_summaries()

    return json.dumps(
        {
            "new_replies": _messages_to_response_list(worker_replies),
            "completed_tasks": completed_ids,
            "pending_tasks": pending,
        },
        ensure_ascii=False,
    )


def _handle_wait_for_worker_reply(args: dict[str, Any]) -> str:
    """Block until a Worker Agent replies in the group chat, or timeout.

    Polls the thread's messages.jsonl at a fixed interval.  Returns as soon
    as any Worker message is found, or an empty result when the timeout
    expires.
    """
    thread_id = args.get("thread_id", DEFAULT_GROUP_THREAD_ID)
    timeout_seconds = max(1, min(args.get("timeout_seconds", 300), 600))
    worker_ids = tuple(args.get("worker_ids", ()))

    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        cursor = load_read_cursor(thread_id)
        all_messages = _read_thread_messages(thread_id)
        new_messages = _filter_new_messages(all_messages, cursor.last_read_message_id)
        worker_replies = _find_worker_responses(new_messages)

        if worker_ids:
            worker_replies = [
                msg
                for msg in worker_replies
                if msg.sender.participant_id in worker_ids
            ]

        if worker_replies:
            completed_ids = _auto_complete_tasks(thread_id, worker_replies)
            if all_messages:
                save_read_cursor(thread_id, all_messages[-1].message_id)
            pending = get_pending_task_summaries()
            return json.dumps(
                {
                    "new_replies": _messages_to_response_list(worker_replies),
                    "completed_tasks": completed_ids,
                    "pending_tasks": pending,
                },
                ensure_ascii=False,
            )

        time.sleep(_WAIT_POLL_INTERVAL_SECONDS)

    return json.dumps(
        {
            "new_replies": [],
            "completed_tasks": [],
            "pending_tasks": get_pending_task_summaries(),
            "note": f"No Worker reply received within {timeout_seconds}s timeout.",
        },
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

from tools.registry import registry

SEND_WORKER_MESSAGE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "send_worker_message",
        "description": (
            "向Worker Agent群聊发送任务消息，并@mention目标Worker以触发其处理。"
            "适用于将专项任务（如编码、设计）分发给对应的Worker Agent。"
            "分发后无需等待，可继续处理其他对话。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "thread_id": {
                    "type": "string",
                    "description": "目标群聊ID，默认使用 'thread-default-group'",
                },
                "text": {
                    "type": "string",
                    "description": "要发送的任务消息正文，应包含清晰的任务描述和上下文",
                },
                "mention_worker_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要@提及的Worker ID列表，例如 ['coder-agent']。如果未指定，消息将发送给所有参与者",
                },
            },
            "required": ["text"],
        },
    },
}

CHECK_WORKER_REPLIES_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "check_worker_replies",
        "description": (
            "检查Worker Agent群聊中是否有新的回复消息。"
            "读取上次检查位置之后的所有新消息，并自动标记已完成的任务。"
            "应在回复用户之前调用，以确保用户获得最新的任务状态。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "thread_id": {
                    "type": "string",
                    "description": "目标群聊ID，默认使用 'thread-default-group'",
                },
            },
            "required": [],
        },
    },
}

WAIT_FOR_WORKER_REPLY_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "wait_for_worker_reply",
        "description": (
            "阻塞等待Worker Agent的回复，直到收到回复或超时。"
            "适用于需要立即获取Worker处理结果的关键任务场景。"
            "非关键任务应使用 send_worker_message + check_worker_replies 的异步模式。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "thread_id": {
                    "type": "string",
                    "description": "目标群聊ID，默认使用 'thread-default-group'",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "最大等待秒数，默认300秒，最大600秒",
                },
                "worker_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "等待特定Worker的回复。如果未指定，等待任意Worker的回复",
                },
            },
            "required": [],
        },
    },
}

registry.register(
    name="send_worker_message",
    toolset="worker_messaging",
    schema=SEND_WORKER_MESSAGE_SCHEMA,
    handler=lambda args, **kw: _handle_send_worker_message(args),
    emoji="📨",
)

registry.register(
    name="check_worker_replies",
    toolset="worker_messaging",
    schema=CHECK_WORKER_REPLIES_SCHEMA,
    handler=lambda args, **kw: _handle_check_worker_replies(args),
    emoji="📬",
)

registry.register(
    name="wait_for_worker_reply",
    toolset="worker_messaging",
    schema=WAIT_FOR_WORKER_REPLY_SCHEMA,
    handler=lambda args, **kw: _handle_wait_for_worker_reply(args),
    emoji="⏳",
)
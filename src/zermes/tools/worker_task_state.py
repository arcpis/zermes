#!/usr/bin/env python3
"""Structured task state storage for Worker Agent task dispatch.

Stores dispatched-but-not-yet-completed tasks and per-thread read cursors
as JSON files under ``{hermes_home}/worker_agents/state/``.  This storage is
fully independent of the semantic memory system so that context compression
never loses precise task-ownership information.

This module is a plain data layer — it has no side effects beyond disk I/O.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from zermes.hermes_constants import get_hermes_home
from zermes.utils import atomic_json_write

TASK_DISPATCH_STATE_SCHEMA_VERSION = 1
_STATE_DIR_NAME = "state"
_TASK_STATE_FILE = "task_dispatch_state.json"
_CURSOR_FILE = "last_read_cursors.json"


@dataclass
class PendingTask:
    """A task dispatched to a Worker Agent that has not yet been marked completed."""

    task_id: str
    thread_id: str
    dispatched_to: tuple[str, ...]
    task_summary: str
    dispatched_at: str
    status: str = "pending"
    result_message_ids: tuple[str, ...] = ()
    dispatch_message_id: str | None = None
    completed_by: str | None = None
    completed_at: str | None = None
    completion_message_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "thread_id": self.thread_id,
            "dispatched_to": list(self.dispatched_to),
            "task_summary": self.task_summary,
            "dispatched_at": self.dispatched_at,
            "status": self.status,
            "result_message_ids": list(self.result_message_ids),
            "dispatch_message_id": self.dispatch_message_id,
            "completed_by": self.completed_by,
            "completed_at": self.completed_at,
            "completion_message_id": self.completion_message_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> PendingTask:
        raw_dispatched_to = data["dispatched_to"]
        if isinstance(raw_dispatched_to, str):
            dispatched_to = tuple(
                item.strip() for item in raw_dispatched_to.split(",") if item.strip()
            )
        else:
            dispatched_to = tuple(str(item) for item in raw_dispatched_to)
        return cls(
            task_id=data["task_id"],
            thread_id=data["thread_id"],
            dispatched_to=dispatched_to,
            task_summary=data["task_summary"],
            dispatched_at=data["dispatched_at"],
            status=data.get("status", "pending"),
            result_message_ids=tuple(data.get("result_message_ids", ())),
            dispatch_message_id=data.get("dispatch_message_id"),
            completed_by=data.get("completed_by"),
            completed_at=data.get("completed_at"),
            completion_message_id=data.get("completion_message_id"),
        )


@dataclass
class TaskDispatchState:
    """Container for all pending dispatch tasks."""

    pending_tasks: tuple[PendingTask, ...] = ()

    def to_dict(self) -> dict:
        return {
            "schema_version": TASK_DISPATCH_STATE_SCHEMA_VERSION,
            "pending_tasks": [t.to_dict() for t in self.pending_tasks],
        }

    @classmethod
    def from_dict(cls, data: dict) -> TaskDispatchState:
        tasks = data.get("pending_tasks", [])
        return cls(pending_tasks=tuple(PendingTask.from_dict(t) for t in tasks))


@dataclass
class ReadCursor:
    """Tracks the last-read message_id for a given thread."""

    thread_id: str
    last_read_message_id: Optional[str] = None


def _state_dir() -> Path:
    return get_hermes_home() / "worker_agents" / _STATE_DIR_NAME


def _ensure_state_dir() -> None:
    _state_dir().mkdir(parents=True, exist_ok=True)


def _task_state_path() -> Path:
    return _state_dir() / _TASK_STATE_FILE


def _cursor_path() -> Path:
    return _state_dir() / _CURSOR_FILE


def load_task_state() -> TaskDispatchState:
    """Load the current task dispatch state from disk."""
    path = _task_state_path()
    if not path.exists():
        return TaskDispatchState()
    try:
        return TaskDispatchState.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, KeyError):
        return TaskDispatchState()


def save_task_state(state: TaskDispatchState) -> None:
    """Persist the task dispatch state to disk."""
    _ensure_state_dir()
    atomic_json_write(_task_state_path(), state.to_dict())


def add_pending_task(
    task_id: str,
    thread_id: str,
    dispatched_to: tuple[str, ...] | list[str],
    task_summary: str,
    dispatch_message_id: str | None = None,
) -> None:
    """Add a new pending task to the dispatch state."""
    state = load_task_state()
    task = PendingTask(
        task_id=task_id,
        thread_id=thread_id,
        dispatched_to=tuple(dispatched_to),
        task_summary=task_summary,
        dispatched_at=datetime.now(UTC).isoformat(),
        dispatch_message_id=dispatch_message_id,
    )
    state.pending_tasks = state.pending_tasks + (task,)
    save_task_state(state)


def mark_task_completed(
    task_id: str,
    result_message_ids: tuple[str, ...] = (),
    completed_by: str | None = None,
    completion_message_id: str | None = None,
) -> None:
    """Mark a pending task as completed."""
    state = load_task_state()
    completed_at = datetime.now(UTC).isoformat()
    updated = tuple(
        PendingTask(
            task_id=t.task_id,
            thread_id=t.thread_id,
            dispatched_to=t.dispatched_to,
            task_summary=t.task_summary,
            dispatched_at=t.dispatched_at,
            status="completed" if t.task_id == task_id else t.status,
            result_message_ids=result_message_ids if t.task_id == task_id else t.result_message_ids,
            dispatch_message_id=t.dispatch_message_id,
            completed_by=completed_by if t.task_id == task_id else t.completed_by,
            completed_at=completed_at if t.task_id == task_id else t.completed_at,
            completion_message_id=completion_message_id
            if t.task_id == task_id
            else t.completion_message_id,
        )
        for t in state.pending_tasks
    )
    state.pending_tasks = updated
    save_task_state(state)


def get_pending_tasks() -> tuple[PendingTask, ...]:
    """Return the tuple of currently-pending tasks."""
    return load_task_state().pending_tasks


def get_pending_task_summaries() -> list[str]:
    """Return a list of human-readable pending task summaries."""
    return [t.task_summary for t in get_pending_tasks() if t.status == "pending"]


def load_read_cursors() -> dict[str, ReadCursor]:
    """Load all thread read cursors from disk. Returns {thread_id: ReadCursor}."""
    path = _cursor_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        # Versioned files store cursor data under "cursors"; older files used
        # the thread-id mapping directly.  Accept both to avoid losing state
        # from already-running worker deployments.
        cursor_map = raw.get("cursors", raw) if isinstance(raw, dict) else {}
        return {
            thread_id: ReadCursor(
                thread_id=thread_id,
                last_read_message_id=cursor.get("last_read_message_id"),
            )
            for thread_id, cursor in cursor_map.items()
            if isinstance(cursor, dict)
        }
    except (json.JSONDecodeError, KeyError):
        return {}


def save_read_cursors(cursors: dict[str, ReadCursor]) -> None:
    """Persist all thread read cursors to disk."""
    _ensure_state_dir()
    atomic_json_write(
        _cursor_path(),
        {
            "schema_version": TASK_DISPATCH_STATE_SCHEMA_VERSION,
            "cursors": {
                thread_id: {
                    "thread_id": c.thread_id,
                    "last_read_message_id": c.last_read_message_id,
                }
                for thread_id, c in cursors.items()
            },
        },
    )


def load_read_cursor(thread_id: str) -> ReadCursor:
    """Load the read cursor for a single thread."""
    cursors = load_read_cursors()
    return cursors.get(thread_id, ReadCursor(thread_id=thread_id))


def save_read_cursor(thread_id: str, last_read_message_id: Optional[str]) -> None:
    """Update the read cursor for a single thread."""
    cursors = load_read_cursors()
    cursors[thread_id] = ReadCursor(
        thread_id=thread_id,
        last_read_message_id=last_read_message_id,
    )
    save_read_cursors(cursors)

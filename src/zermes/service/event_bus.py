"""Unified event bus for decoupling AIAgent callbacks from interface consumers.

All interfaces (CLI, TUI, Gateway, Web) can subscribe to the same event types
and receive structured events regardless of the underlying callback mechanism.
"""

from __future__ import annotations

import logging
import threading
from enum import Enum, auto
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# Callback signature: (event_type: EventType, payload: Any) -> None
Subscriber = Callable[["EventType", Any], None]


class EventType(Enum):
    """Standardized event types across all interfaces."""

    STREAM_DELTA = auto()          # payload: str — streaming text delta
    TOOL_CALL_START = auto()       # payload: dict — {tc_id, name, args}
    TOOL_CALL_COMPLETE = auto()    # payload: dict — {tc_id, name, args, result}
    TOOL_PROGRESS = auto()         # payload: dict — {event_type, name, preview, args}
    TOOL_GENERATING = auto()       # payload: dict — {name}
    THINKING = auto()              # payload: str — thinking text delta
    REASONING = auto()             # payload: str — reasoning text delta
    CLARIFY = auto()               # payload: dict — {question, choices}
    STATUS = auto()                # payload: dict — {kind, text}
    STEP = auto()                  # payload: dict — {iteration, tool_names}
    ERROR = auto()                 # payload: dict — {message, exception}
    CONVERSATION_END = auto()      # payload: dict — {final_response, completed}


class EventBus:
    """Thread-safe publish/subscribe event bus.

    Subscribers can filter by event type or use None as a wildcard to receive
    all events. Exceptions raised by subscribers are caught and logged — they
    never propagate to the emitter.

    Usage::

        bus = EventBus("my-session")

        # Subscribe to specific events
        unsub = bus.subscribe(lambda et, p: print(f"{et}: {p}"), EventType.STREAM_DELTA)

        # Subscribe to all events
        bus.subscribe(lambda et, p: print(f"ALL: {et}"), event_type=None)

        # Emit
        bus.emit(EventType.STREAM_DELTA, "Hello ")

        # Bridge to AIAgent
        agent = AIAgent(**bus.make_callback_dict(), ...)
    """

    def __init__(self, name: str = "default"):
        self._name = name
        self._subscribers: dict[EventType | None, list[Subscriber]] = {}
        self._lock = threading.RLock()

    def subscribe(
        self, callback: Subscriber, event_type: Optional[EventType] = None
    ) -> Callable[[], None]:
        """Subscribe to events. Returns an unsubscribe function.

        Args:
            callback: Called as callback(event_type, payload) for each matching event.
            event_type: Filter to this event type, or None for all events.
        """
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            self._subscribers[event_type].append(callback)

        def _unsubscribe():
            with self._lock:
                subs = self._subscribers.get(event_type, [])
                if callback in subs:
                    subs.remove(callback)
                    if not subs:
                        self._subscribers.pop(event_type, None)

        return _unsubscribe

    def emit(self, event_type: EventType, payload: Any = None) -> None:
        """Emit an event to all matching subscribers."""
        with self._lock:
            # Snapshot subscribers to avoid holding lock during callbacks
            specific = list(self._subscribers.get(event_type, ()))
            wildcard = list(self._subscribers.get(None, ()))

        for sub in specific:
            try:
                sub(event_type, payload)
            except Exception:
                logger.debug(
                    "EventBus[%s] subscriber error for %s",
                    self._name,
                    event_type.name,
                    exc_info=True,
                )

        for sub in wildcard:
            try:
                sub(event_type, payload)
            except Exception:
                logger.debug(
                    "EventBus[%s] wildcard subscriber error for %s",
                    self._name,
                    event_type.name,
                    exc_info=True,
                )

    def clear(self) -> None:
        """Remove all subscribers."""
        with self._lock:
            self._subscribers.clear()

    # ------------------------------------------------------------------
    # AIAgent callback bridge
    # ------------------------------------------------------------------

    def make_callback_dict(self) -> dict[str, Callable]:
        """Return a dict of callbacks suitable for AIAgent(**kwargs).

        Each callback bridges the corresponding AIAgent callback to this
        EventBus, emitting the appropriate EventType.

        Usage::

            agent = AIAgent(**bus.make_callback_dict(), model="...", ...)
        """
        return {
            "stream_delta_callback": self._make_stream_delta_cb(),
            "tool_progress_callback": self._make_tool_progress_cb(),
            "tool_start_callback": self._make_tool_start_cb(),
            "tool_complete_callback": self._make_tool_complete_cb(),
            "tool_gen_callback": self._make_tool_gen_cb(),
            "thinking_callback": self._make_thinking_cb(),
            "reasoning_callback": self._make_reasoning_cb(),
            "clarify_callback": self._make_clarify_cb(),
            "status_callback": self._make_status_cb(),
            "step_callback": self._make_step_cb(),
        }

    def _make_stream_delta_cb(self) -> Callable:
        def _cb(text):
            self.emit(EventType.STREAM_DELTA, text)

        return _cb

    def _make_tool_progress_cb(self) -> Callable:
        def _cb(event_type, name, preview, args):
            self.emit(
                EventType.TOOL_PROGRESS,
                {"event_type": event_type, "name": name, "preview": preview, "args": args},
            )

        return _cb

    def _make_tool_start_cb(self) -> Callable:
        def _cb(tc_id, name, args):
            self.emit(
                EventType.TOOL_CALL_START, {"tc_id": tc_id, "name": name, "args": args}
            )

        return _cb

    def _make_tool_complete_cb(self) -> Callable:
        def _cb(tc_id, name, args, result):
            self.emit(
                EventType.TOOL_CALL_COMPLETE,
                {"tc_id": tc_id, "name": name, "args": args, "result": result},
            )

        return _cb

    def _make_tool_gen_cb(self) -> Callable:
        def _cb(name):
            self.emit(EventType.TOOL_GENERATING, {"name": name})

        return _cb

    def _make_thinking_cb(self) -> Callable:
        def _cb(text):
            self.emit(EventType.THINKING, text)

        return _cb

    def _make_reasoning_cb(self) -> Callable:
        def _cb(text):
            self.emit(EventType.REASONING, text)

        return _cb

    def _make_clarify_cb(self) -> Callable:
        def _cb(question, choices):
            self.emit(EventType.CLARIFY, {"question": question, "choices": choices})

        return _cb

    def _make_status_cb(self) -> Callable:
        def _cb(kind, text):
            self.emit(EventType.STATUS, {"kind": kind, "text": text})

        return _cb

    def _make_step_cb(self) -> Callable:
        def _cb(iteration, tool_names):
            self.emit(
                EventType.STEP, {"iteration": iteration, "tool_names": tool_names}
            )

        return _cb
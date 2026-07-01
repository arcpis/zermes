"""Tests for EventBus."""

import threading
import time

import pytest

from zermes.service.event_bus import EventBus, EventType


class TestEventBus:
    def test_subscribe_and_emit(self):
        bus = EventBus("test")
        received = []

        bus.subscribe(lambda et, p: received.append((et, p)), EventType.STREAM_DELTA)
        bus.emit(EventType.STREAM_DELTA, "hello")

        assert len(received) == 1
        assert received[0] == (EventType.STREAM_DELTA, "hello")

    def test_unsubscribe(self):
        bus = EventBus("test")
        received = []

        unsub = bus.subscribe(lambda et, p: received.append(p), EventType.STREAM_DELTA)
        bus.emit(EventType.STREAM_DELTA, "first")
        unsub()
        bus.emit(EventType.STREAM_DELTA, "second")

        assert received == ["first"]

    def test_event_type_filtering(self):
        bus = EventBus("test")
        deltas = []
        errors = []

        bus.subscribe(lambda et, p: deltas.append(p), EventType.STREAM_DELTA)
        bus.subscribe(lambda et, p: errors.append(p), EventType.ERROR)

        bus.emit(EventType.STREAM_DELTA, "text")
        bus.emit(EventType.ERROR, "oops")

        assert deltas == ["text"]
        assert errors == ["oops"]

    def test_wildcard_subscriber(self):
        bus = EventBus("test")
        all_events = []

        bus.subscribe(lambda et, p: all_events.append(et), event_type=None)
        bus.emit(EventType.STREAM_DELTA, "a")
        bus.emit(EventType.ERROR, "b")

        assert len(all_events) == 2
        assert all_events == [EventType.STREAM_DELTA, EventType.ERROR]

    def test_subscriber_exception_isolation(self):
        bus = EventBus("test")
        good = []

        def bad_callback(et, p):
            raise RuntimeError("boom")

        bus.subscribe(bad_callback, EventType.ERROR)
        bus.subscribe(lambda et, p: good.append(p), EventType.ERROR)

        # Should not raise
        bus.emit(EventType.ERROR, "data")

        assert good == ["data"]

    def test_clear(self):
        bus = EventBus("test")
        received = []

        bus.subscribe(lambda et, p: received.append(p), EventType.STREAM_DELTA)
        bus.emit(EventType.STREAM_DELTA, "before")
        bus.clear()
        bus.emit(EventType.STREAM_DELTA, "after")

        assert received == ["before"]

    def test_thread_safety(self):
        bus = EventBus("test")
        received = []
        lock = threading.Lock()

        def collector(et, p):
            with lock:
                received.append(p)

        bus.subscribe(collector, EventType.STREAM_DELTA)

        def emitter():
            for i in range(100):
                bus.emit(EventType.STREAM_DELTA, f"t{i}")

        threads = [threading.Thread(target=emitter) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(received) == 500

    def test_make_callback_dict(self):
        bus = EventBus("test")
        received = []

        bus.subscribe(lambda et, p: received.append((et, p)), event_type=None)

        cbs = bus.make_callback_dict()

        # stream_delta_callback
        cbs["stream_delta_callback"]("hello")
        assert (EventType.STREAM_DELTA, "hello") in received

        # thinking_callback
        cbs["thinking_callback"]("thinking...")
        assert (EventType.THINKING, "thinking...") in received

        # reasoning_callback
        cbs["reasoning_callback"]("reasoning...")
        assert (EventType.REASONING, "reasoning...") in received

        # tool_progress_callback
        cbs["tool_progress_callback"]("progress", "tool1", "preview", {"arg": 1})
        last = received[-1]
        assert last[0] == EventType.TOOL_PROGRESS
        assert last[1]["name"] == "tool1"

        # tool_start_callback
        cbs["tool_start_callback"]("tc1", "read_file", {"path": "/x"})
        last = received[-1]
        assert last[0] == EventType.TOOL_CALL_START
        assert last[1]["name"] == "read_file"

        # tool_complete_callback
        cbs["tool_complete_callback"]("tc1", "read_file", {"path": "/x"}, "content")
        last = received[-1]
        assert last[0] == EventType.TOOL_CALL_COMPLETE
        assert last[1]["result"] == "content"

        # status_callback
        cbs["status_callback"]("info", "done")
        last = received[-1]
        assert last[0] == EventType.STATUS
        assert last[1]["kind"] == "info"

        # clarify_callback
        cbs["clarify_callback"]("What?", ["a", "b"])
        last = received[-1]
        assert last[0] == EventType.CLARIFY
        assert last[1]["choices"] == ["a", "b"]

        # step_callback
        cbs["step_callback"](3, ["tool_a", "tool_b"])
        last = received[-1]
        assert last[0] == EventType.STEP
        assert last[1]["iteration"] == 3

        # tool_gen_callback
        cbs["tool_gen_callback"]("code_exec")
        last = received[-1]
        assert last[0] == EventType.TOOL_GENERATING
        assert last[1]["name"] == "code_exec"
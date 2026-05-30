"""LLM execution engine for managed worker runtime sessions.

Reuses HermesAgentLoop from environments.agent_loop as the multi-turn
tool-calling engine.  The executor bridges the synchronous worker runtime
to the async agent loop, builds filtered tool schemas from the worker's
allowed_tool_names, and returns a structured WorkerLLMResult.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Any

from .runtime_facade import AgentRuntimeInvocation

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkerLLMResult:
    """Structured result of a worker LLM execution."""

    content: str
    turns_used: int
    tool_calls_made: int
    finished_naturally: bool
    model_used: str | None = None
    error: str | None = None


class WorkerLLMExecutorError(RuntimeError):
    """Raised when a worker LLM execution fails."""


class _WorkerAsyncServer:
    """Lightweight async server wrapper that HermesAgentLoop expects.

    Wraps an ``openai.AsyncOpenAI`` client so that ``chat_completion()``
    returns an awaitable — matching the interface used by
    ``environments.agent_loop.HermesAgentLoop``.
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        from openai import AsyncOpenAI

        self.model = model
        self.client = AsyncOpenAI(
            api_key=api_key or os.environ.get("OPENAI_API_KEY"),
            base_url=base_url or os.environ.get("OPENAI_BASE_URL"),
        )

    async def chat_completion(self, **kwargs: Any):
        kwargs.setdefault("model", self.model)
        return await self.client.chat.completions.create(**kwargs)


def _build_chat_reply_guidance(
    chat_message_type: str | None,
    thread_participants: tuple[str, ...],
) -> str:
    if not chat_message_type:
        return ""
    if chat_message_type == "normal":
        return "This is a direct (private) chat message. Reply normally with your response."
    if chat_message_type in ("mention", "broadcast") and thread_participants:
        worker_refs = ", ".join(
            f"@{ref.removeprefix('worker:')}"
            for ref in thread_participants
        )
        message_label = "BROADCAST" if chat_message_type == "broadcast" else "MENTION"
        return (
            f"This is a group chat {message_label} message. "
            f"Other participants in this thread: {worker_refs}. "
            "You may choose one of these reply options:\n"
            "1. Reply normally (visible to everyone in the thread).\n"
            "2. Mention a specific worker by starting your reply with @worker-id.\n"
            "3. Do not reply — output [NO_REPLY] as your entire response."
        )
    return ""


def _build_system_message(invocation: AgentRuntimeInvocation) -> str:
    parts: list[str] = [f"You are {invocation.display_name}."]
    if invocation.responsibility_summary:
        parts.append(f"Your responsibilities: {invocation.responsibility_summary}")
    if invocation.task_summary:
        parts.append(f"Current task: {invocation.task_summary}")
    if invocation.allowed_tool_names:
        parts.append(f"Available tools: {', '.join(invocation.allowed_tool_names)}")
    if invocation.workspace_read_roots:
        parts.append(f"Readable paths: {', '.join(invocation.workspace_read_roots)}")
    if invocation.workspace_write_roots:
        parts.append(f"Writable paths: {', '.join(invocation.workspace_write_roots)}")
    guidance = _build_chat_reply_guidance(
        invocation.chat_message_type,
        invocation.thread_participants,
    )
    if guidance:
        parts.append(guidance)
    return "\n\n".join(parts)


def _extract_final_content(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "assistant" and msg.get("content"):
            content = msg["content"]
            if isinstance(content, str) and content.strip():
                return content.strip()
    return ""


class WorkerLLMExecutor:
    """Execute LLM calls for managed worker runtime sessions.

    Uses ``HermesAgentLoop`` from ``environments.agent_loop`` as the
    multi-turn tool-calling engine.  The executor:

    1. Builds a lightweight async server from the invocation's model config.
    2. Filters tool schemas to only those the worker is allowed to call.
    3. Runs the agent loop (sync bridge over the async loop).
    4. Returns a ``WorkerLLMResult`` with the final assistant content.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        max_turns: int = 10,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._max_turns = max_turns

    @classmethod
    def from_main_agent_runtime(
        cls,
        *,
        target_model: str | None = None,
        max_turns: int = 10,
    ) -> WorkerLLMExecutor:
        try:
            from hermes_cli.runtime_provider import resolve_runtime_provider

            runtime = resolve_runtime_provider(target_model=target_model)
            return cls(
                api_key=runtime.get("api_key") or None,
                base_url=runtime.get("base_url") or None,
                max_turns=max_turns,
            )
        except Exception as exc:
            logger.warning(
                "WorkerLLMExecutor.from_main_agent_runtime failed, "
                "falling back to no-key executor: %s: %s",
                type(exc).__name__, exc,
            )
            return cls(max_turns=max_turns)

    def _resolve_main_agent_model(self) -> str:
        try:
            from hermes_cli.runtime_provider import _get_model_config

            model_cfg = _get_model_config()
            return model_cfg.get("default") or "gpt-4o"
        except Exception:
            return "gpt-4o"

    def execute(self, invocation: AgentRuntimeInvocation) -> WorkerLLMResult:
        """Run the LLM execution synchronously, bridging to the async loop."""
        try:
            return asyncio.run(self._execute_async(invocation))
        except RuntimeError as exc:
            if "asyncio.run() cannot be called from a running event loop" in str(exc):
                return self._execute_in_thread(invocation)
            raise

    def _execute_in_thread(self, invocation: AgentRuntimeInvocation) -> WorkerLLMResult:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, self._execute_async(invocation))
            timeout = (invocation.max_task_tokens or 120000) / 1000 or 120
            return future.result(timeout=timeout)

    async def _execute_async(self, invocation: AgentRuntimeInvocation) -> WorkerLLMResult:
        from environments.agent_loop import HermesAgentLoop
        from model_tools import get_tool_definitions

        model_name = invocation.model_name or self._resolve_main_agent_model()
        server = _WorkerAsyncServer(
            model=model_name,
            api_key=self._api_key,
            base_url=self._base_url,
        )

        allowed = set(invocation.allowed_tool_names)
        if allowed:
            all_tools = get_tool_definitions(quiet_mode=True)
            worker_tools = [
                t for t in all_tools if t["function"]["name"] in allowed
            ]
        else:
            worker_tools = []
        valid_names = {t["function"]["name"] for t in worker_tools}

        system_msg = _build_system_message(invocation)
        user_msg = invocation.user_instruction
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ]

        logger.info(
            "Worker LLM executing: worker_id=%s, model=%s",
            invocation.worker_id,
            model_name,
        )

        loop = HermesAgentLoop(
            server=server,
            tool_schemas=worker_tools,
            valid_tool_names=valid_names,
            max_turns=self._max_turns,
            max_tokens=invocation.max_task_tokens,
        )

        try:
            result = await loop.run(messages)
        except Exception as exc:
            logger.error("Worker LLM execution failed: %s", exc)
            return WorkerLLMResult(
                content="",
                turns_used=0,
                tool_calls_made=0,
                finished_naturally=False,
                model_used=model_name,
                error=f"{type(exc).__name__}: {exc}",
            )

        final_content = _extract_final_content(result.messages)
        tool_calls_made = sum(
            1 for m in result.messages if m.get("role") == "tool"
        )

        logger.info(
            "Worker LLM replied: worker_id=%s, model=%s, turns_used=%d, tool_calls_made=%d, finished_naturally=%s",
            invocation.worker_id,
            model_name,
            result.turns_used,
            tool_calls_made,
            result.finished_naturally,
        )

        return WorkerLLMResult(
            content=final_content,
            turns_used=result.turns_used,
            tool_calls_made=tool_calls_made,
            finished_naturally=result.finished_naturally,
            model_used=model_name,
        )

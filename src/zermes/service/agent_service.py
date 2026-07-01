"""AgentService — thin wrapper around AIAgent creation.

Design principles:
- Accepts an AgentConfig and produces an AIAgent instance.
- If an EventBus is provided, automatically bridges callbacks via
  make_callback_dict().
- Returns the raw AIAgent instance — no proxy, no hidden state.
- Existing code that directly instantiates AIAgent continues to work.
"""

from __future__ import annotations

import logging
from typing import Optional

from zermes.run_agent import AIAgent
from zermes.service.config_types import AgentConfig
from zermes.service.event_bus import EventBus

logger = logging.getLogger(__name__)


class AgentService:
    """Unified AIAgent lifecycle management.

    All interfaces should use this service instead of directly instantiating
    AIAgent. This ensures consistent parameter mapping and callback wiring.

    Usage::

        service = AgentService(event_bus=EventBus("my-session"))
        config = AgentConfig(
            runtime=RuntimeConfig(base_url="...", api_key="..."),
            model="claude-sonnet-4-20250514",
            platform="cli",
        )
        agent = service.create_agent(config)
        agent.run_conversation("Hello!")
    """

    def __init__(self, event_bus: Optional[EventBus] = None):
        self._event_bus = event_bus

    def create_agent(self, config: AgentConfig) -> AIAgent:
        """Create an AIAgent from an AgentConfig.

        If an EventBus was provided at construction time, callback kwargs
        from make_callback_dict() are merged into the constructor call.
        Config-level callbacks take precedence over EventBus callbacks.
        """
        kwargs = config.to_agent_kwargs()

        if self._event_bus:
            bus_callbacks = self._event_bus.make_callback_dict()
            for key, cb in bus_callbacks.items():
                if key not in kwargs or kwargs[key] is None:
                    kwargs[key] = cb

        return AIAgent(**kwargs)
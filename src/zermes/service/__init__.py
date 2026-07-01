"""Service layer — unified API for agent lifecycle, events, and commands.

Provides:
- AgentService: Create AIAgent instances from structured config.
- EventBus: Publish/subscribe event system for decoupling callbacks.
- EventType: Standardized event types across all interfaces.
- CommandService: Centralized command resolution and execution.
- AgentConfig, RuntimeConfig, ProviderRoutingConfig: Typed config dataclasses.
- CommandContext, CommandResult: Command execution types.
"""

from zermes.service.agent_service import AgentService
from zermes.service.command_service import CommandContext, CommandResult, CommandService
from zermes.service.config_types import (
    AgentConfig,
    ProviderRoutingConfig,
    RuntimeConfig,
)
from zermes.service.event_bus import EventBus, EventType

__all__ = [
    "AgentConfig",
    "AgentService",
    "CommandContext",
    "CommandResult",
    "CommandService",
    "EventBus",
    "EventType",
    "ProviderRoutingConfig",
    "RuntimeConfig",
]
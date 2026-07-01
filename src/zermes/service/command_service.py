"""CommandService — centralized command resolution and execution.

Uses the existing COMMAND_REGISTRY from hermes_cli/commands.py for command
lookup. Handlers are registered per interface (cli, gateway, etc.) and
executed through a unified dispatch method.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from zermes.hermes_cli.commands import CommandDef, resolve_command

logger = logging.getLogger(__name__)


@dataclass
class CommandContext:
    """Resolved command context passed to handlers."""

    canonical: str
    raw_command: str
    args: str
    command_def: Optional[CommandDef] = None


@dataclass
class CommandResult:
    """Result of command execution."""

    ok: bool
    output: str = ""
    error: str = ""

    @staticmethod
    def success(output: str = "") -> "CommandResult":
        return CommandResult(ok=True, output=output)

    @staticmethod
    def failure(error: str) -> "CommandResult":
        return CommandResult(ok=False, error=error)


# Handler types: sync or async
CommandHandler = Callable[[CommandContext], Any]


class CommandService:
    """Centralized command resolution and handler registration.

    Uses the existing COMMAND_REGISTRY for command lookup. Handlers are
    registered per interface name, allowing CLI and Gateway to share
    resolution logic while keeping their own execution paths.

    Usage::

        svc = CommandService()
        svc.register("help", cli_help_handler, interface="cli")
        svc.register("help", gateway_help_handler, interface="gateway")

        ctx = svc.resolve("/help model")
        result = svc.execute(ctx, interface="cli")
    """

    def __init__(self):
        self._handlers: dict[str, CommandHandler] = {}
        self._interface_handlers: dict[str, dict[str, CommandHandler]] = {}

    def resolve(self, text: str) -> CommandContext:
        """Parse raw text into a CommandContext.

        Args:
            text: Raw input like "/new my title" or "new"

        Returns:
            CommandContext with canonical name, args, and optional CommandDef.
        """
        raw = text.strip()
        if not raw:
            return CommandContext(canonical="", raw_command="", args="")

        # Extract the command word (with or without leading slash)
        parts = raw.split(maxsplit=1)
        first_word = parts[0].lstrip("/")
        args = parts[1] if len(parts) > 1 else ""

        cmd_def = resolve_command(first_word)
        canonical = cmd_def.name if cmd_def else first_word.lower()

        return CommandContext(
            canonical=canonical,
            raw_command=raw,
            args=args,
            command_def=cmd_def,
        )

    def register(
        self,
        canonical: str,
        handler: CommandHandler,
        interface: str = "cli",
    ) -> None:
        """Register a handler for a canonical command name.

        Args:
            canonical: Canonical command name (e.g. "help", "new").
            handler: Callable that accepts CommandContext and returns any value.
            interface: Interface name ("cli", "gateway", "tui", etc.).
        """
        if interface not in self._interface_handlers:
            self._interface_handlers[interface] = {}
        self._interface_handlers[interface][canonical] = handler

    def execute(
        self, ctx: CommandContext, interface: str = "cli"
    ) -> CommandResult:
        """Execute a resolved command for the given interface.

        Args:
            ctx: Resolved CommandContext from resolve().
            interface: Interface name to look up handlers for.

        Returns:
            CommandResult indicating success or failure.
        """
        handlers = self._interface_handlers.get(interface, {})
        handler = handlers.get(ctx.canonical)

        if handler is None:
            return CommandResult.failure(
                f"Unknown command '/{ctx.canonical}'. Type /help for available commands."
            )

        try:
            result = handler(ctx)
            if isinstance(result, CommandResult):
                return result
            if isinstance(result, str):
                return CommandResult.success(result)
            return CommandResult.success(str(result) if result is not None else "")
        except Exception as e:
            logger.debug(
                "CommandService[%s] handler error for /%s",
                interface,
                ctx.canonical,
                exc_info=True,
            )
            return CommandResult.failure(str(e))

    def is_known(self, canonical: str, interface: str = "cli") -> bool:
        """Check if a canonical command name has a registered handler."""
        handlers = self._interface_handlers.get(interface, {})
        return canonical in handlers

    def list_commands(self, interface: str = "cli") -> list[CommandDef]:
        """List all registered commands for an interface, with their CommandDef metadata."""
        from zermes.hermes_cli.commands import COMMAND_REGISTRY

        handlers = self._interface_handlers.get(interface, {})
        result = []
        for cmd_def in COMMAND_REGISTRY:
            if cmd_def.name in handlers:
                result.append(cmd_def)
        return result

    def get_interface(self) -> str:
        """Return the default interface name (for backwards compat)."""
        return "cli"
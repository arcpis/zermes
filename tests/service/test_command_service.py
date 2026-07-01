"""Tests for CommandService."""

import pytest

from zermes.hermes_cli.commands import CommandDef, resolve_command
from zermes.service.command_service import (
    CommandContext,
    CommandResult,
    CommandService,
)


class TestCommandService:
    def test_resolve_simple_command(self):
        svc = CommandService()
        ctx = svc.resolve("/help")

        assert ctx.canonical == "help"
        assert ctx.args == ""
        assert ctx.command_def is not None
        assert ctx.command_def.name == "help"

    def test_resolve_command_with_args(self):
        svc = CommandService()
        ctx = svc.resolve("/model gpt-4")

        assert ctx.canonical == "model"
        assert ctx.args == "gpt-4"

    def test_resolve_alias(self):
        svc = CommandService()
        ctx = svc.resolve("/reset")

        assert ctx.canonical == "new"  # "reset" is an alias for "new"
        assert ctx.command_def.name == "new"

    def test_resolve_no_slash(self):
        svc = CommandService()
        ctx = svc.resolve("help")

        assert ctx.canonical == "help"

    def test_resolve_unknown_command(self):
        svc = CommandService()
        ctx = svc.resolve("/nonexistent_cmd_xyz")

        assert ctx.canonical == "nonexistent_cmd_xyz"
        assert ctx.command_def is None

    def test_resolve_empty(self):
        svc = CommandService()
        ctx = svc.resolve("")

        assert ctx.canonical == ""
        assert ctx.raw_command == ""

    def test_register_and_execute(self):
        svc = CommandService()

        def help_handler(ctx):
            return CommandResult.success(f"Help for: {ctx.args or 'all'}")

        svc.register("help", help_handler)

        ctx = svc.resolve("/help model")
        result = svc.execute(ctx)

        assert result.ok is True
        assert result.output == "Help for: model"

    def test_register_and_execute_str_return(self):
        svc = CommandService()

        svc.register("status", lambda ctx: "All good")

        ctx = svc.resolve("/status")
        result = svc.execute(ctx)

        assert result.ok is True
        assert result.output == "All good"

    def test_execute_unknown_command(self):
        svc = CommandService()
        ctx = svc.resolve("/nonexistent_cmd_xyz")
        result = svc.execute(ctx)

        assert result.ok is False
        assert "Unknown command" in result.error

    def test_execute_handler_exception(self):
        svc = CommandService()

        def bad_handler(ctx):
            raise ValueError("test error")

        svc.register("crash", bad_handler)

        ctx = svc.resolve("/crash")
        result = svc.execute(ctx)

        assert result.ok is False
        assert "test error" in result.error

    def test_interface_isolation(self):
        svc = CommandService()

        svc.register("help", lambda ctx: "cli help", interface="cli")
        svc.register("help", lambda ctx: "gateway help", interface="gateway")

        ctx = svc.resolve("/help")

        assert svc.execute(ctx, interface="cli").output == "cli help"
        assert svc.execute(ctx, interface="gateway").output == "gateway help"

    def test_is_known(self):
        svc = CommandService()
        svc.register("help", lambda ctx: "ok")

        assert svc.is_known("help") is True
        assert svc.is_known("nonexistent") is False

    def test_is_known_interface_specific(self):
        svc = CommandService()
        svc.register("help", lambda ctx: "ok", interface="cli")

        assert svc.is_known("help", interface="cli") is True
        assert svc.is_known("help", interface="gateway") is False

    def test_list_commands(self):
        svc = CommandService()
        svc.register("help", lambda ctx: "ok")
        svc.register("new", lambda ctx: "ok")

        cmds = svc.list_commands()
        names = {c.name for c in cmds}
        assert "help" in names
        assert "new" in names

    def test_command_result_success(self):
        r = CommandResult.success("done")
        assert r.ok is True
        assert r.output == "done"
        assert r.error == ""

    def test_command_result_failure(self):
        r = CommandResult.failure("bad")
        assert r.ok is False
        assert r.error == "bad"
        assert r.output == ""


class TestCommandContext:
    def test_fields(self):
        cmd_def = CommandDef("test", "desc", "Test")
        ctx = CommandContext(
            canonical="test",
            raw_command="/test arg1",
            args="arg1",
            command_def=cmd_def,
        )
        assert ctx.canonical == "test"
        assert ctx.raw_command == "/test arg1"
        assert ctx.args == "arg1"
        assert ctx.command_def is cmd_def
"""Tests for AgentService."""

from unittest.mock import MagicMock, patch

import pytest

from zermes.service.agent_service import AgentService
from zermes.service.config_types import (
    AgentConfig,
    ProviderRoutingConfig,
    RuntimeConfig,
)
from zermes.service.event_bus import EventBus, EventType


class TestAgentService:
    def test_create_agent_basic(self):
        """AgentService creates an AIAgent with correct kwargs."""
        config = AgentConfig(
            runtime=RuntimeConfig(
                base_url="http://test:8000/v1",
                api_key="sk-test",
                provider="openai",
            ),
            model="gpt-4",
            max_iterations=5,
            platform="cli",
            quiet_mode=True,
        )

        with patch("zermes.service.agent_service.AIAgent") as mock_agent:
            service = AgentService()
            agent = service.create_agent(config)

            mock_agent.assert_called_once()
            kwargs = mock_agent.call_args.kwargs
            assert kwargs["base_url"] == "http://test:8000/v1"
            assert kwargs["api_key"] == "sk-test"
            assert kwargs["provider"] == "openai"
            assert kwargs["model"] == "gpt-4"
            assert kwargs["max_iterations"] == 5
            assert kwargs["platform"] == "cli"
            assert kwargs["quiet_mode"] is True

    def test_create_agent_with_event_bus(self):
        """AgentService merges EventBus callbacks into AIAgent kwargs."""
        config = AgentConfig(
            runtime=RuntimeConfig(base_url="http://test:8000/v1"),
            model="claude",
        )

        bus = EventBus("test-session")
        received = []
        bus.subscribe(lambda et, p: received.append(et), event_type=None)

        with patch("zermes.service.agent_service.AIAgent") as mock_agent:
            service = AgentService(event_bus=bus)
            agent = service.create_agent(config)

            kwargs = mock_agent.call_args.kwargs
            assert "stream_delta_callback" in kwargs
            assert "thinking_callback" in kwargs
            assert "tool_progress_callback" in kwargs
            assert kwargs["stream_delta_callback"] is not None
            assert kwargs["thinking_callback"] is not None

    def test_create_agent_config_callbacks_take_precedence(self):
        """Config-level callbacks take precedence over EventBus callbacks."""
        custom_cb = lambda text: None

        config = AgentConfig(
            runtime=RuntimeConfig(base_url="http://test:8000/v1"),
            model="claude",
            stream_delta_callback=custom_cb,
        )

        bus = EventBus("test")

        with patch("zermes.service.agent_service.AIAgent") as mock_agent:
            service = AgentService(event_bus=bus)
            service.create_agent(config)

            kwargs = mock_agent.call_args.kwargs
            # Config callback should win over EventBus callback
            assert kwargs["stream_delta_callback"] is custom_cb

    def test_create_agent_with_provider_routing(self):
        """Provider routing config is passed through."""
        config = AgentConfig(
            runtime=RuntimeConfig(base_url="http://test:8000/v1"),
            model="claude",
            provider_routing=ProviderRoutingConfig(
                providers_allowed=["openai"],
                providers_ignored=["anthropic"],
                provider_sort="cost",
                provider_require_parameters=True,
            ),
        )

        with patch("zermes.service.agent_service.AIAgent") as mock_agent:
            service = AgentService()
            service.create_agent(config)

            kwargs = mock_agent.call_args.kwargs
            assert kwargs["providers_allowed"] == ["openai"]
            assert kwargs["providers_ignored"] == ["anthropic"]
            assert kwargs["provider_sort"] == "cost"
            assert kwargs["provider_require_parameters"] is True

    def test_create_agent_with_gateway_fields(self):
        """Gateway-specific fields (user_id, chat_id, etc.) are passed through."""
        config = AgentConfig(
            runtime=RuntimeConfig(base_url="http://test:8000/v1"),
            model="claude",
            platform="telegram",
            user_id="user123",
            chat_id="chat456",
            gateway_session_key="gw:session:1",
        )

        with patch("zermes.service.agent_service.AIAgent") as mock_agent:
            service = AgentService()
            service.create_agent(config)

            kwargs = mock_agent.call_args.kwargs
            assert kwargs["platform"] == "telegram"
            assert kwargs["user_id"] == "user123"
            assert kwargs["chat_id"] == "chat456"
            assert kwargs["gateway_session_key"] == "gw:session:1"

    def test_create_agent_skips_default_values(self):
        """Default values that match AIAgent defaults are not passed."""
        config = AgentConfig(
            runtime=RuntimeConfig(base_url="http://test:8000/v1"),
            model="claude",
        )

        with patch("zermes.service.agent_service.AIAgent") as mock_agent:
            service = AgentService()
            service.create_agent(config)

            kwargs = mock_agent.call_args.kwargs
            # quiet_mode defaults to False, so it should NOT be in kwargs
            assert "quiet_mode" not in kwargs
            assert "verbose_logging" not in kwargs
            assert "skip_context_files" not in kwargs
            assert "skip_memory" not in kwargs


class TestRuntimeConfig:
    def test_from_dict(self):
        d = {
            "base_url": "http://test:8000",
            "api_key": "sk-123",
            "provider": "openai",
            "api_mode": "chat_completions",
            "command": "echo",
            "args": ["hello"],
            "credential_pool": None,
        }
        rc = RuntimeConfig.from_dict(d)
        assert rc.base_url == "http://test:8000"
        assert rc.api_key == "sk-123"
        assert rc.provider == "openai"
        assert rc.api_mode == "chat_completions"
        assert rc.acp_command == "echo"
        assert rc.acp_args == ["hello"]

    def test_from_dict_empty(self):
        rc = RuntimeConfig.from_dict({})
        assert rc.base_url is None
        assert rc.api_key is None

    def test_to_agent_kwargs_only_non_none(self):
        rc = RuntimeConfig(base_url="http://test:8000")
        kwargs = rc.to_agent_kwargs()
        assert kwargs == {"base_url": "http://test:8000"}

    def test_to_agent_kwargs_full(self):
        rc = RuntimeConfig(
            base_url="http://test:8000",
            api_key="sk-123",
            provider="openai",
            api_mode="chat_completions",
        )
        kwargs = rc.to_agent_kwargs()
        assert kwargs["base_url"] == "http://test:8000"
        assert kwargs["api_key"] == "sk-123"
        assert kwargs["provider"] == "openai"
        assert kwargs["api_mode"] == "chat_completions"


class TestAgentConfig:
    def test_to_agent_kwargs_minimal(self):
        config = AgentConfig(
            runtime=RuntimeConfig(base_url="http://test:8000"),
            model="gpt-4",
        )
        kwargs = config.to_agent_kwargs()
        assert kwargs["base_url"] == "http://test:8000"
        assert kwargs["model"] == "gpt-4"
        assert kwargs["max_iterations"] == 90

    def test_to_agent_kwargs_with_callbacks(self):
        cb = lambda text: None
        config = AgentConfig(
            runtime=RuntimeConfig(base_url="http://test:8000"),
            model="gpt-4",
            stream_delta_callback=cb,
            thinking_callback=cb,
        )
        kwargs = config.to_agent_kwargs()
        assert kwargs["stream_delta_callback"] is cb
        assert kwargs["thinking_callback"] is cb
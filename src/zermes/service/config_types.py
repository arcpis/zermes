"""Configuration types for AgentService.

Defines structured dataclasses that map to AIAgent.__init__ parameters,
grouping the repeated parameter blocks across call sites.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class RuntimeConfig:
    """API endpoint / credential configuration block.

    These 7 parameters appear together in 5 of 7 AIAgent call sites.
    """

    base_url: Optional[str] = None
    api_key: Optional[str] = None
    provider: Optional[str] = None
    api_mode: Optional[str] = None
    acp_command: Optional[str] = None
    acp_args: Optional[list[str]] = None
    credential_pool: Any = None

    @classmethod
    def from_dict(cls, d: dict) -> "RuntimeConfig":
        """Build from a typical 'runtime' dict (cli.py, gateway/run.py, etc.)."""
        if not d:
            return cls()
        return cls(
            base_url=d.get("base_url"),
            api_key=d.get("api_key"),
            provider=d.get("provider"),
            api_mode=d.get("api_mode"),
            acp_command=d.get("command"),
            acp_args=d.get("args"),
            credential_pool=d.get("credential_pool"),
        )

    def to_agent_kwargs(self) -> dict:
        """Expand to AIAgent constructor kwargs."""
        result: dict[str, Any] = {}
        if self.base_url is not None:
            result["base_url"] = self.base_url
        if self.api_key is not None:
            result["api_key"] = self.api_key
        if self.provider is not None:
            result["provider"] = self.provider
        if self.api_mode is not None:
            result["api_mode"] = self.api_mode
        if self.acp_command is not None:
            result["acp_command"] = self.acp_command
        if self.acp_args is not None:
            result["acp_args"] = self.acp_args
        if self.credential_pool is not None:
            result["credential_pool"] = self.credential_pool
        return result


@dataclass
class ProviderRoutingConfig:
    """Provider selection / filtering parameters.

    These 6 parameters appear together in 3 of 7 AIAgent call sites.
    """

    providers_allowed: Optional[list[str]] = None
    providers_ignored: Optional[list[str]] = None
    providers_order: Optional[list[str]] = None
    provider_sort: Optional[str] = None
    provider_require_parameters: bool = False
    provider_data_collection: Optional[str] = None

    def to_agent_kwargs(self) -> dict:
        """Expand to AIAgent constructor kwargs."""
        result: dict[str, Any] = {}
        if self.providers_allowed is not None:
            result["providers_allowed"] = self.providers_allowed
        if self.providers_ignored is not None:
            result["providers_ignored"] = self.providers_ignored
        if self.providers_order is not None:
            result["providers_order"] = self.providers_order
        if self.provider_sort is not None:
            result["provider_sort"] = self.provider_sort
        if self.provider_require_parameters:
            result["provider_require_parameters"] = True
        if self.provider_data_collection is not None:
            result["provider_data_collection"] = self.provider_data_collection
        return result


@dataclass
class AgentConfig:
    """Complete configuration for AIAgent creation.

    Every field maps directly to an AIAgent.__init__ parameter.
    Call to_agent_kwargs() to produce the dict for AIAgent(**kwargs).
    """

    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    provider_routing: ProviderRoutingConfig = field(default_factory=ProviderRoutingConfig)

    model: str = ""
    max_iterations: int = 90
    enabled_toolsets: Optional[list[str]] = None
    disabled_toolsets: Optional[list[str]] = None
    quiet_mode: bool = False
    verbose_logging: bool = False
    ephemeral_system_prompt: Optional[str] = None
    prefill_messages: Optional[list[dict]] = None
    reasoning_config: Optional[dict] = None
    service_tier: Optional[str] = None
    request_overrides: Optional[dict] = None
    session_id: Optional[str] = None
    platform: Optional[str] = None
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    chat_id: Optional[str] = None
    chat_name: Optional[str] = None
    chat_type: Optional[str] = None
    thread_id: Optional[str] = None
    gateway_session_key: Optional[str] = None
    session_db: Any = None
    fallback_model: Optional[dict] = None
    skip_context_files: bool = False
    skip_memory: bool = False
    load_soul_identity: bool = False
    checkpoints_enabled: bool = False
    checkpoint_max_snapshots: int = 20
    checkpoint_max_total_size_mb: int = 500
    checkpoint_max_file_size_mb: int = 10
    pass_session_id: bool = False
    log_prefix: str = ""
    log_prefix_chars: int = 100
    save_trajectories: bool = False
    max_tokens: Optional[int] = None

    # Callbacks — set by EventBus.make_callback_dict() when EventBus is connected
    tool_progress_callback: Optional[Callable] = None
    tool_start_callback: Optional[Callable] = None
    tool_complete_callback: Optional[Callable] = None
    thinking_callback: Optional[Callable] = None
    reasoning_callback: Optional[Callable] = None
    clarify_callback: Optional[Callable] = None
    step_callback: Optional[Callable] = None
    stream_delta_callback: Optional[Callable] = None
    interim_assistant_callback: Optional[Callable] = None
    tool_gen_callback: Optional[Callable] = None
    status_callback: Optional[Callable] = None

    def to_agent_kwargs(self) -> dict[str, Any]:
        """Convert to a dict suitable for AIAgent(**kwargs)."""
        result: dict[str, Any] = {}

        # Runtime block
        result.update(self.runtime.to_agent_kwargs())

        # Provider routing block
        result.update(self.provider_routing.to_agent_kwargs())

        # Core parameters
        if self.model:
            result["model"] = self.model
        if self.max_iterations != 90:
            result["max_iterations"] = self.max_iterations
        else:
            result["max_iterations"] = 90
        if self.enabled_toolsets is not None:
            result["enabled_toolsets"] = self.enabled_toolsets
        if self.disabled_toolsets is not None:
            result["disabled_toolsets"] = self.disabled_toolsets
        if self.quiet_mode:
            result["quiet_mode"] = True
        if self.verbose_logging:
            result["verbose_logging"] = True
        if self.ephemeral_system_prompt is not None:
            result["ephemeral_system_prompt"] = self.ephemeral_system_prompt
        if self.prefill_messages is not None:
            result["prefill_messages"] = self.prefill_messages
        if self.reasoning_config is not None:
            result["reasoning_config"] = self.reasoning_config
        if self.service_tier is not None:
            result["service_tier"] = self.service_tier
        if self.request_overrides is not None:
            result["request_overrides"] = self.request_overrides
        if self.session_id is not None:
            result["session_id"] = self.session_id
        if self.platform is not None:
            result["platform"] = self.platform
        if self.user_id is not None:
            result["user_id"] = self.user_id
        if self.user_name is not None:
            result["user_name"] = self.user_name
        if self.chat_id is not None:
            result["chat_id"] = self.chat_id
        if self.chat_name is not None:
            result["chat_name"] = self.chat_name
        if self.chat_type is not None:
            result["chat_type"] = self.chat_type
        if self.thread_id is not None:
            result["thread_id"] = self.thread_id
        if self.gateway_session_key is not None:
            result["gateway_session_key"] = self.gateway_session_key
        if self.session_db is not None:
            result["session_db"] = self.session_db
        if self.fallback_model is not None:
            result["fallback_model"] = self.fallback_model
        if self.skip_context_files:
            result["skip_context_files"] = True
        if self.skip_memory:
            result["skip_memory"] = True
        if self.load_soul_identity:
            result["load_soul_identity"] = True
        if self.checkpoints_enabled:
            result["checkpoints_enabled"] = True
        if self.checkpoint_max_snapshots != 20:
            result["checkpoint_max_snapshots"] = self.checkpoint_max_snapshots
        if self.checkpoint_max_total_size_mb != 500:
            result["checkpoint_max_total_size_mb"] = self.checkpoint_max_total_size_mb
        if self.checkpoint_max_file_size_mb != 10:
            result["checkpoint_max_file_size_mb"] = self.checkpoint_max_file_size_mb
        if self.pass_session_id:
            result["pass_session_id"] = True
        if self.log_prefix:
            result["log_prefix"] = self.log_prefix
        if self.log_prefix_chars != 100:
            result["log_prefix_chars"] = self.log_prefix_chars
        if self.save_trajectories:
            result["save_trajectories"] = True
        if self.max_tokens is not None:
            result["max_tokens"] = self.max_tokens

        # Callbacks
        if self.tool_progress_callback is not None:
            result["tool_progress_callback"] = self.tool_progress_callback
        if self.tool_start_callback is not None:
            result["tool_start_callback"] = self.tool_start_callback
        if self.tool_complete_callback is not None:
            result["tool_complete_callback"] = self.tool_complete_callback
        if self.thinking_callback is not None:
            result["thinking_callback"] = self.thinking_callback
        if self.reasoning_callback is not None:
            result["reasoning_callback"] = self.reasoning_callback
        if self.clarify_callback is not None:
            result["clarify_callback"] = self.clarify_callback
        if self.step_callback is not None:
            result["step_callback"] = self.step_callback
        if self.stream_delta_callback is not None:
            result["stream_delta_callback"] = self.stream_delta_callback
        if self.interim_assistant_callback is not None:
            result["interim_assistant_callback"] = self.interim_assistant_callback
        if self.tool_gen_callback is not None:
            result["tool_gen_callback"] = self.tool_gen_callback
        if self.status_callback is not None:
            result["status_callback"] = self.status_callback

        return result
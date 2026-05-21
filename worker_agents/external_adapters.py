"""Contracts for managed external agent adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from .runtime_contract import (
    RuntimeContractError,
    RuntimeRequest,
    RuntimeType,
    runtime_request_to_dict,
)


class ExternalAdapterError(ValueError):
    """Raised when an external adapter boundary is invalid."""


class ExternalAdapterCapability(StrEnum):
    """High-level work families an external adapter can perform."""

    CODE = "code"
    DOCUMENT = "document"
    GENERIC = "generic"
    IMAGE = "image"
    RESEARCH = "research"
    VIDEO = "video"


class ExternalAdapterInputType(StrEnum):
    """Low-sensitive input bundle shapes accepted by external adapters."""

    ARTIFACT_REFS = "artifact_refs"
    MANIFEST_REFS = "manifest_refs"
    TASK_SUMMARY = "task_summary"
    TEXT_PROMPT = "text_prompt"


class ExternalAdapterOutputType(StrEnum):
    """Normalized output families external adapters may return."""

    ARTIFACT_MANIFEST = "artifact_manifest"
    MEMORY_PROPOSAL = "memory_proposal"
    PUBLIC_MESSAGE = "public_message"
    SAFETY_REQUEST = "safety_request"
    STRUCTURED_RESULT = "structured_result"


class ExternalAdapterSecurityLevel(StrEnum):
    """Declared risk band for a managed external adapter."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ExternalAdapterHealthCheckKind(StrEnum):
    """Supported health check mechanisms for external adapters."""

    CONFIGURED = "configured"
    PROCESS = "process"
    SERVICE = "service"


_SENSITIVE_FIELD_NAMES = frozenset(
    {
        "api_key",
        "complete_transcript",
        "credential",
        "credentials",
        "environment",
        "env",
        "full_transcript",
        "private_memory",
        "private_memory_text",
        "raw_output",
        "raw_stderr",
        "raw_stdout",
        "raw_transcript",
        "refresh_token",
        "secret",
        "stderr",
        "stdout",
        "token",
    }
)


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ExternalAdapterError(f"{field_name} must be a non-empty string")
    return value


def _string_tuple(value: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple) or not value:
        raise ExternalAdapterError(f"{field_name} must be a non-empty tuple")
    if any(not isinstance(item, str) or not item for item in value):
        raise ExternalAdapterError(f"{field_name} must contain non-empty strings")
    return value


def _positive_int(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ExternalAdapterError(f"{field_name} must be a positive integer")
    return value


def _reject_sensitive_fields(value: Any, field_name: str) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if isinstance(key, str) and key.lower() in _SENSITIVE_FIELD_NAMES:
                raise ExternalAdapterError(
                    f"{field_name} must not include sensitive field: {key}"
                )
            _reject_sensitive_fields(nested, f"{field_name}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _reject_sensitive_fields(nested, f"{field_name}[{index}]")


def _reject_wildcard_permissions(values: tuple[str, ...], field_name: str) -> None:
    for value in values:
        if value in {"*", "all", "admin", "root"} or value.endswith(":*"):
            raise ExternalAdapterError(f"{field_name} must not include wildcard access")


def _coerce_tuple_enum(
    values: tuple[StrEnum | str, ...],
    enum_type: type[StrEnum],
    field_name: str,
) -> tuple[StrEnum, ...]:
    _string_tuple(tuple(value.value if isinstance(value, StrEnum) else value for value in values), field_name)
    coerced: list[StrEnum] = []
    for value in values:
        raw_value = value.value if isinstance(value, StrEnum) else value
        try:
            coerced.append(enum_type(raw_value))
        except ValueError as exc:
            raise ExternalAdapterError(f"Unknown {field_name}: {raw_value!r}") from exc
    return tuple(coerced)


def _coerce_enum(
    value: StrEnum | str,
    enum_type: type[StrEnum],
    field_name: str,
) -> StrEnum:
    raw_value = value.value if isinstance(value, StrEnum) else value
    _require_string(raw_value, field_name)
    try:
        return enum_type(raw_value)
    except ValueError as exc:
        raise ExternalAdapterError(f"Unknown {field_name}: {raw_value!r}") from exc


@dataclass(frozen=True)
class ExternalAdapterHealthCheck:
    """Health check declaration for an external adapter."""

    kind: ExternalAdapterHealthCheckKind | str
    description: str
    timeout_seconds: int = 10
    requires_network: bool = False
    requires_process: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "kind",
            _coerce_enum(
                self.kind, ExternalAdapterHealthCheckKind, "health_check.kind"
            ),
        )
        _require_string(self.description, "health_check.description")
        _positive_int(self.timeout_seconds, "health_check.timeout_seconds")
        if not isinstance(self.requires_network, bool):
            raise ExternalAdapterError("health_check.requires_network must be boolean")
        if not isinstance(self.requires_process, bool):
            raise ExternalAdapterError("health_check.requires_process must be boolean")


@dataclass(frozen=True)
class ExternalAdapterDefinition:
    """Static capability and safety declaration for one external adapter."""

    adapter_id: str
    display_name: str
    provider: str
    capabilities: tuple[ExternalAdapterCapability | str, ...]
    supported_input_types: tuple[ExternalAdapterInputType | str, ...]
    supported_output_types: tuple[ExternalAdapterOutputType | str, ...]
    health_check: ExternalAdapterHealthCheck
    security_level: ExternalAdapterSecurityLevel | str
    permission_requirements: tuple[str, ...] = ()
    transcript_policy: str = "middle_data_only"
    runtime_type: RuntimeType | str = RuntimeType.EXTERNAL_ADAPTER

    def __post_init__(self) -> None:
        _require_string(self.adapter_id, "adapter_id")
        if not self.adapter_id.replace("-", "_").replace("_", "").isalnum():
            raise ExternalAdapterError("adapter_id must be a stable identifier")
        _require_string(self.display_name, "display_name")
        _require_string(self.provider, "provider")
        object.__setattr__(
            self,
            "capabilities",
            _coerce_tuple_enum(
                self.capabilities, ExternalAdapterCapability, "capabilities"
            ),
        )
        object.__setattr__(
            self,
            "supported_input_types",
            _coerce_tuple_enum(
                self.supported_input_types,
                ExternalAdapterInputType,
                "supported_input_types",
            ),
        )
        object.__setattr__(
            self,
            "supported_output_types",
            _coerce_tuple_enum(
                self.supported_output_types,
                ExternalAdapterOutputType,
                "supported_output_types",
            ),
        )
        if not isinstance(self.health_check, ExternalAdapterHealthCheck):
            raise ExternalAdapterError(
                "health_check must be an ExternalAdapterHealthCheck"
            )
        object.__setattr__(
            self,
            "security_level",
            _coerce_enum(
                self.security_level,
                ExternalAdapterSecurityLevel,
                "security_level",
            ),
        )
        _string_tuple(tuple(self.permission_requirements or ("no_external_access",)), "permission_requirements")
        object.__setattr__(
            self, "permission_requirements", tuple(self.permission_requirements)
        )
        _reject_wildcard_permissions(
            self.permission_requirements, "permission_requirements"
        )
        _require_string(self.transcript_policy, "transcript_policy")
        runtime_type = (
            self.runtime_type.value
            if isinstance(self.runtime_type, RuntimeType)
            else self.runtime_type
        )
        if runtime_type != RuntimeType.EXTERNAL_ADAPTER.value:
            raise ExternalAdapterError("external adapter runtime_type is required")
        object.__setattr__(self, "runtime_type", RuntimeType.EXTERNAL_ADAPTER)


@dataclass
class ExternalAdapterRegistry:
    """In-memory registry for declared external adapter definitions."""

    _definitions: dict[str, ExternalAdapterDefinition] = field(default_factory=dict)

    def register(self, definition: ExternalAdapterDefinition) -> None:
        """Register one adapter definition, rejecting duplicate ids."""

        if definition.adapter_id in self._definitions:
            raise ExternalAdapterError(
                f"external adapter already registered: {definition.adapter_id}"
            )
        self._definitions[definition.adapter_id] = definition

    def get(self, adapter_id: str) -> ExternalAdapterDefinition:
        """Return a registered adapter definition by id."""

        _require_string(adapter_id, "adapter_id")
        try:
            return self._definitions[adapter_id]
        except KeyError as exc:
            raise ExternalAdapterError(
                f"external adapter is not registered: {adapter_id}"
            ) from exc

    def list(self) -> tuple[ExternalAdapterDefinition, ...]:
        """List registered adapters in stable id order."""

        return tuple(self._definitions[key] for key in sorted(self._definitions))

    def find_by_capability(
        self, capability: ExternalAdapterCapability | str
    ) -> tuple[ExternalAdapterDefinition, ...]:
        """List adapters that declare the requested capability."""

        wanted = _coerce_enum(capability, ExternalAdapterCapability, "capability")
        return tuple(
            definition
            for definition in self.list()
            if wanted in definition.capabilities
        )


def validate_external_adapter_request(
    definition: ExternalAdapterDefinition, request: RuntimeRequest
) -> None:
    """Reject a runtime request that cannot be handled by an adapter."""

    if not isinstance(definition, ExternalAdapterDefinition):
        raise ExternalAdapterError("definition must be an ExternalAdapterDefinition")
    if not isinstance(request, RuntimeRequest):
        raise ExternalAdapterError("request must be a RuntimeRequest")
    if request.runtime_type != RuntimeType.EXTERNAL_ADAPTER:
        raise ExternalAdapterError("request runtime_type must be external_adapter")
    _reject_sensitive_fields(runtime_request_to_dict(request), "runtime_request")
    if (
        ExternalAdapterInputType.TEXT_PROMPT not in definition.supported_input_types
        and request.context.input_message
    ):
        raise ExternalAdapterError("adapter does not support text prompt input")
    if (
        request.context.artifact_manifest_refs
        and ExternalAdapterInputType.MANIFEST_REFS
        not in definition.supported_input_types
    ):
        raise ExternalAdapterError("adapter does not support manifest references")
    if (
        request.context.allowed_tool_descriptions
        and "tool_access"
        not in definition.permission_requirements
    ):
        raise ExternalAdapterError("adapter does not declare tool access permission")


def external_adapter_definition_to_dict(
    definition: ExternalAdapterDefinition,
) -> dict[str, Any]:
    """Return a JSON-safe adapter definition for audit and UI display."""

    return {
        "adapter_id": definition.adapter_id,
        "display_name": definition.display_name,
        "provider": definition.provider,
        "capabilities": [capability.value for capability in definition.capabilities],
        "supported_input_types": [
            input_type.value for input_type in definition.supported_input_types
        ],
        "supported_output_types": [
            output_type.value for output_type in definition.supported_output_types
        ],
        "health_check": {
            "kind": definition.health_check.kind.value,
            "description": definition.health_check.description,
            "timeout_seconds": definition.health_check.timeout_seconds,
            "requires_network": definition.health_check.requires_network,
            "requires_process": definition.health_check.requires_process,
        },
        "security_level": definition.security_level.value,
        "permission_requirements": list(definition.permission_requirements),
        "transcript_policy": definition.transcript_policy,
        "runtime_type": definition.runtime_type.value,
    }


def build_fake_external_adapter_definition(
    *,
    adapter_id: str = "fake-external-adapter",
    capabilities: tuple[ExternalAdapterCapability | str, ...] = (
        ExternalAdapterCapability.GENERIC,
    ),
) -> ExternalAdapterDefinition:
    """Build a safe fake adapter definition for tests and examples."""

    return ExternalAdapterDefinition(
        adapter_id=adapter_id,
        display_name="Fake External Adapter",
        provider="zermes-test",
        capabilities=capabilities,
        supported_input_types=(
            ExternalAdapterInputType.TEXT_PROMPT,
            ExternalAdapterInputType.MANIFEST_REFS,
        ),
        supported_output_types=(
            ExternalAdapterOutputType.PUBLIC_MESSAGE,
            ExternalAdapterOutputType.STRUCTURED_RESULT,
        ),
        health_check=ExternalAdapterHealthCheck(
            kind=ExternalAdapterHealthCheckKind.CONFIGURED,
            description="Fake adapter is available when registered.",
        ),
        security_level=ExternalAdapterSecurityLevel.LOW,
        permission_requirements=("tool_access",),
    )

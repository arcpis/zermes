import pytest

from worker_agents.external_adapters import (
    ExternalAdapterCapability,
    ExternalAdapterDefinition,
    ExternalAdapterError,
    ExternalAdapterHealthCheck,
    ExternalAdapterHealthCheckKind,
    ExternalAdapterInputType,
    ExternalAdapterOutputType,
    ExternalAdapterRegistry,
    ExternalAdapterSecurityLevel,
    build_fake_external_adapter_definition,
    external_adapter_definition_to_dict,
    validate_external_adapter_request,
)
from worker_agents.runtime_contract import (
    RuntimeExecutionBudget,
    RuntimeRequest,
    RuntimeRequestContext,
    RuntimeType,
)


def _runtime_request(**context_overrides):
    context = {
        "input_message": "Summarize the approved task.",
        "artifact_manifest_refs": ("manifests/task-1.json",),
    }
    context.update(context_overrides)
    return RuntimeRequest(
        request_id="runtime-request-1",
        task_id="task-1",
        worker_id="researcher",
        runtime_type=RuntimeType.EXTERNAL_ADAPTER,
        requested_by="zermes_main_agent",
        created_at="2026-05-21T00:00:00Z",
        context=RuntimeRequestContext(**context),
        budget=RuntimeExecutionBudget(
            budget_source="worker-profile:researcher",
            timeout_seconds=30,
            max_output_bytes=10000,
        ),
    )


def test_adapter_definition_serializes_for_audit():
    definition = build_fake_external_adapter_definition()

    data = external_adapter_definition_to_dict(definition)

    assert data["adapter_id"] == "fake-external-adapter"
    assert data["runtime_type"] == "external_adapter"
    assert data["health_check"]["kind"] == "configured"


def test_registry_rejects_duplicate_adapter_id():
    registry = ExternalAdapterRegistry()
    definition = build_fake_external_adapter_definition()

    registry.register(definition)

    with pytest.raises(ExternalAdapterError, match="already registered"):
        registry.register(definition)


def test_registry_lists_and_filters_by_capability():
    registry = ExternalAdapterRegistry()
    code_adapter = build_fake_external_adapter_definition(
        adapter_id="code-adapter",
        capabilities=(ExternalAdapterCapability.CODE,),
    )
    research_adapter = build_fake_external_adapter_definition(
        adapter_id="research-adapter",
        capabilities=(ExternalAdapterCapability.RESEARCH,),
    )

    registry.register(research_adapter)
    registry.register(code_adapter)

    assert [item.adapter_id for item in registry.list()] == [
        "code-adapter",
        "research-adapter",
    ]
    assert registry.find_by_capability("code") == (code_adapter,)


def test_definition_rejects_wildcard_permissions():
    with pytest.raises(ExternalAdapterError, match="wildcard"):
        ExternalAdapterDefinition(
            adapter_id="bad-adapter",
            display_name="Bad Adapter",
            provider="test",
            capabilities=(ExternalAdapterCapability.GENERIC,),
            supported_input_types=(ExternalAdapterInputType.TEXT_PROMPT,),
            supported_output_types=(ExternalAdapterOutputType.PUBLIC_MESSAGE,),
            health_check=ExternalAdapterHealthCheck(
                kind=ExternalAdapterHealthCheckKind.CONFIGURED,
                description="Configured.",
            ),
            security_level=ExternalAdapterSecurityLevel.LOW,
            permission_requirements=("tools:*",),
        )


def test_validate_adapter_runtime_request_accepts_compatible_request():
    validate_external_adapter_request(
        build_fake_external_adapter_definition(),
        _runtime_request(),
    )


def test_validate_adapter_runtime_request_rejects_wrong_runtime_type():
    request = RuntimeRequest(
        request_id="runtime-request-1",
        task_id="task-1",
        worker_id="researcher",
        runtime_type=RuntimeType.INTERNAL_WORKER,
        requested_by="zermes_main_agent",
        created_at="2026-05-21T00:00:00Z",
        context=RuntimeRequestContext(input_message="Run it."),
        budget=RuntimeExecutionBudget(
            budget_source="worker-profile:researcher",
            timeout_seconds=30,
        ),
    )

    with pytest.raises(ExternalAdapterError, match="external_adapter"):
        validate_external_adapter_request(
            build_fake_external_adapter_definition(),
            request,
        )

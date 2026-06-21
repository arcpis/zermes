"""Render department context bundles into runtime-safe summary blocks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .department_context_bundle import (
    DepartmentAssetContextBundle,
    DepartmentContextBundleError,
    department_context_bundle_to_dict,
    validate_context_bundle_payload,
)


class DepartmentContextRenderingError(ValueError):
    """Raised when department context cannot be rendered for runtime safely."""


@dataclass(frozen=True)
class RenderedDepartmentContext:
    """Runtime-safe text and references derived from a validated bundle."""

    context_block: str
    sections: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    sensitivity_summary: str = "none"
    audit_trace_ref: str = ""
    no_op: bool = False

    def __post_init__(self) -> None:
        _string_value(self.context_block, "context_block")
        _coerce_string_tuple(self, "sections")
        _coerce_string_tuple(self, "source_refs")
        _require_string(self.sensitivity_summary, "sensitivity_summary")
        _string_value(self.audit_trace_ref, "audit_trace_ref")
        if not isinstance(self.no_op, bool):
            raise DepartmentContextRenderingError("no_op must be a boolean")
        validate_context_bundle_payload(rendered_department_context_to_dict(self))


def render_department_context_bundle(
    bundle: DepartmentAssetContextBundle,
) -> RenderedDepartmentContext:
    """Render a safe bundle into stable runtime context sections."""

    if not isinstance(bundle, DepartmentAssetContextBundle):
        raise DepartmentContextRenderingError(
            "bundle must be a DepartmentAssetContextBundle"
        )
    try:
        validate_context_bundle_payload(department_context_bundle_to_dict(bundle))
    except DepartmentContextBundleError as exc:
        raise DepartmentContextRenderingError(str(exc)) from exc

    sections: list[str] = []
    source_refs: list[str] = []
    if bundle.selected_memories:
        lines = ["Department memory notes:"]
        for view in bundle.selected_memories:
            lines.append(
                f"- {view.memory_id}: {view.summary} "
                f"(sources: {_join(view.source_refs)})"
            )
            source_refs.extend(view.source_refs)
        sections.append("\n".join(lines))

    if bundle.selected_skill_guidance:
        lines = ["Department skill guidance:"]
        for view in bundle.selected_skill_guidance:
            constraint_text = f"; constraints: {_join(view.constraints)}" if view.constraints else ""
            lines.append(
                f"- {view.display_title}: {view.guidance_summary}"
                f"{constraint_text} (sources: {_join(view.source_refs)})"
            )
            source_refs.extend(view.source_refs)
            source_refs.extend(view.guardrail_refs)
            source_refs.extend(view.audit_refs)
        sections.append("\n".join(lines))

    if bundle.selected_tool_policy_snapshot is not None:
        policy = bundle.selected_tool_policy_snapshot
        lines = ["Effective tool policy summary:"]
        if policy.allowed_tool_summaries:
            lines.append(f"- Allowed: {_join(policy.allowed_tool_summaries)}")
        if policy.denied_tool_summaries:
            lines.append(f"- Denied: {_join(policy.denied_tool_summaries)}")
        if policy.approval_required_tool_summaries:
            lines.append(
                "- Approval required: "
                f"{_join(policy.approval_required_tool_summaries)}"
            )
        if policy.denial_reasons:
            lines.append(f"- Denial reasons: {_join(policy.denial_reasons)}")
        if policy.approval_status_refs:
            lines.append(f"- Approval refs: {_join(policy.approval_status_refs)}")
        source_refs.extend(policy.policy_refs)
        source_refs.extend(policy.approval_status_refs)
        source_refs.extend(policy.audit_refs)
        sections.append("\n".join(lines))

    if bundle.excluded_assets:
        lines = ["Excluded or approval notes:"]
        for item in bundle.excluded_assets:
            lines.append(f"- {item.asset_kind}:{item.asset_id} excluded: {item.reason}")
            source_refs.extend(item.source_refs)
        sections.append("\n".join(lines))

    if bundle.selection_reasons:
        lines = ["Selection reasons:"]
        for reason in bundle.selection_reasons:
            lines.append(
                f"- {reason.asset_kind}:{reason.asset_id}: {_join(reason.reasons)}"
            )
            source_refs.extend(reason.source_refs)
        sections.append("\n".join(lines))

    if not sections:
        return RenderedDepartmentContext(
            context_block="",
            sections=(),
            source_refs=(),
            sensitivity_summary="none",
            audit_trace_ref=bundle.task_ref,
            no_op=True,
        )

    sensitivity_summary = (
        f"highest={bundle.sensitivity_summary.highest_included_sensitivity}; "
        f"included={_join(bundle.sensitivity_summary.included_sensitivities) or 'none'}"
    )
    context_block = "\n\n".join(sections)
    rendered = RenderedDepartmentContext(
        context_block=context_block,
        sections=tuple(sections),
        source_refs=tuple(dict.fromkeys(source_refs)),
        sensitivity_summary=sensitivity_summary,
        audit_trace_ref=bundle.task_ref,
        no_op=False,
    )
    validate_context_bundle_payload(rendered_department_context_to_dict(rendered))
    return rendered


def rendered_department_context_to_dict(
    rendered: RenderedDepartmentContext,
) -> dict[str, Any]:
    return {
        "context_block": rendered.context_block,
        "sections": list(rendered.sections),
        "source_refs": list(rendered.source_refs),
        "sensitivity_summary": rendered.sensitivity_summary,
        "audit_trace_ref": rendered.audit_trace_ref,
        "no_op": rendered.no_op,
    }


def _join(values: tuple[str, ...]) -> str:
    return ", ".join(values)


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise DepartmentContextRenderingError(
            f"{field_name} must be a non-empty string"
        )
    return value


def _string_value(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise DepartmentContextRenderingError(f"{field_name} must be a string")
    return value


def _coerce_string_tuple(instance: object, field_name: str) -> None:
    values = getattr(instance, field_name)
    if not isinstance(values, tuple) or any(
        not isinstance(value, str) or not value for value in values
    ):
        raise DepartmentContextRenderingError(
            f"{field_name} must be a tuple of non-empty strings"
        )

"""Safe department asset context bundle contracts for worker runtime injection."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Mapping

from .organization import validate_org_node_id
from .profile import validate_worker_id


DEPARTMENT_CONTEXT_BUNDLE_SCHEMA_VERSION = 1

_SENSITIVE_FIELD_NAMES = frozenset(
    {
        "api_key",
        "complete_transcript",
        "cookie",
        "credential",
        "credentials",
        "env",
        "environment",
        "external_raw_output",
        "full_transcript",
        "private_experience_text",
        "private_memory_text",
        "raw_stderr",
        "raw_stdout",
        "raw_transcript",
        "secret",
        "token",
        "tool_call_history",
        "unaccepted_proposal_body",
    }
)


class DepartmentContextBundleError(ValueError):
    """Raised when a department context bundle crosses a safety boundary."""


@dataclass(frozen=True)
class DepartmentMemoryContextView:
    """Accepted department memory summary allowed into runtime context."""

    department_id: str
    memory_id: str
    kind: str
    summary: str
    tags: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    freshness: str = ""
    sensitivity: str = "low"
    accepted_state: str = "accepted"
    schema_version: int = DEPARTMENT_CONTEXT_BUNDLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        validate_org_node_id(self.department_id)
        _validate_path_segment(self.memory_id, "memory_id")
        _require_string(self.kind, "kind")
        _require_string(self.summary, "summary")
        _require_accepted_state(self.accepted_state)
        _coerce_string_tuple(self, "tags")
        object.__setattr__(
            self,
            "source_refs",
            tuple(_validate_relative_ref(value, "source_refs") for value in self.source_refs),
        )
        if not self.source_refs:
            raise DepartmentContextBundleError("memory source_refs must not be empty")
        _string_value(self.freshness, "freshness")
        _require_string(self.sensitivity, "sensitivity")


@dataclass(frozen=True)
class DepartmentSkillGuidanceContextView:
    """Accepted department skill guidance summary allowed into runtime context."""

    department_id: str
    binding_id: str
    skill_id: str
    display_title: str
    guidance_summary: str
    constraints: tuple[str, ...] = ()
    guardrail_refs: tuple[str, ...] = ()
    audit_refs: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    sensitivity: str = "low"
    accepted_state: str = "accepted"
    schema_version: int = DEPARTMENT_CONTEXT_BUNDLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        validate_org_node_id(self.department_id)
        _validate_path_segment(self.binding_id, "binding_id")
        _validate_path_segment(self.skill_id, "skill_id")
        _require_string(self.display_title, "display_title")
        _require_string(self.guidance_summary, "guidance_summary")
        _require_accepted_state(self.accepted_state)
        for field_name in ("constraints", "guardrail_refs", "audit_refs"):
            object.__setattr__(
                self,
                field_name,
                tuple(_validate_relative_or_text(value, field_name) for value in getattr(self, field_name)),
            )
        object.__setattr__(
            self,
            "source_refs",
            tuple(_validate_relative_ref(value, "source_refs") for value in self.source_refs),
        )
        if not self.source_refs:
            raise DepartmentContextBundleError("skill source_refs must not be empty")
        _require_string(self.sensitivity, "sensitivity")


@dataclass(frozen=True)
class DepartmentToolPolicyContextSnapshot:
    """Credential-free effective tool policy summary for context injection."""

    department_id: str
    allowed_tool_summaries: tuple[str, ...] = ()
    denied_tool_summaries: tuple[str, ...] = ()
    approval_required_tool_summaries: tuple[str, ...] = ()
    denial_reasons: tuple[str, ...] = ()
    approval_status_refs: tuple[str, ...] = ()
    policy_refs: tuple[str, ...] = ()
    audit_refs: tuple[str, ...] = ()
    schema_version: int = DEPARTMENT_CONTEXT_BUNDLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        validate_org_node_id(self.department_id)
        for field_name in (
            "allowed_tool_summaries",
            "denied_tool_summaries",
            "approval_required_tool_summaries",
            "denial_reasons",
        ):
            _coerce_string_tuple(self, field_name)
        for field_name in ("approval_status_refs", "policy_refs", "audit_refs"):
            object.__setattr__(
                self,
                field_name,
                tuple(_validate_relative_ref(value, field_name) for value in getattr(self, field_name)),
            )
        if (
            self.allowed_tool_summaries
            or self.denied_tool_summaries
            or self.approval_required_tool_summaries
        ) and not self.policy_refs:
            raise DepartmentContextBundleError("tool policy_refs must not be empty")


@dataclass(frozen=True)
class DepartmentContextSelectionReason:
    """Explains why one selected asset was allowed into the bundle."""

    asset_kind: str
    asset_id: str
    reasons: tuple[str, ...]
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_string(self.asset_kind, "asset_kind")
        _validate_path_segment(self.asset_id, "asset_id")
        object.__setattr__(
            self,
            "reasons",
            tuple(_require_string(value, "reasons") for value in self.reasons),
        )
        if not self.reasons:
            raise DepartmentContextBundleError("selection reasons must not be empty")
        object.__setattr__(
            self,
            "source_refs",
            tuple(_validate_relative_ref(value, "source_refs") for value in self.source_refs),
        )


@dataclass(frozen=True)
class DepartmentContextExcludedAsset:
    """Audit-safe summary of an asset that was not injected."""

    asset_kind: str
    asset_id: str
    reason: str
    sensitivity: str = "unknown"
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_string(self.asset_kind, "asset_kind")
        _validate_path_segment(self.asset_id, "asset_id")
        _require_string(self.reason, "reason")
        _require_string(self.sensitivity, "sensitivity")
        object.__setattr__(
            self,
            "source_refs",
            tuple(_validate_relative_ref(value, "source_refs") for value in self.source_refs),
        )


@dataclass(frozen=True)
class DepartmentContextSensitivitySummary:
    """Low-cardinality sensitivity summary without raw sensitive values."""

    highest_included_sensitivity: str = "none"
    included_sensitivities: tuple[str, ...] = ()
    excluded_sensitive_count: int = 0

    def __post_init__(self) -> None:
        _require_string(self.highest_included_sensitivity, "highest_included_sensitivity")
        _coerce_string_tuple(self, "included_sensitivities")
        _non_negative_int(self.excluded_sensitive_count, "excluded_sensitive_count")


@dataclass(frozen=True)
class DepartmentContextLimitSummary:
    """Summarizes bundle limits and whether they affected selection."""

    memory_items: int = 0
    skill_items: int = 0
    total_items: int = 0
    max_memory_items: int = 0
    max_skill_items: int = 0
    max_total_items: int = 0
    max_total_summary_chars: int = 0
    limit_reached: bool = False
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "memory_items",
            "skill_items",
            "total_items",
            "max_memory_items",
            "max_skill_items",
            "max_total_items",
            "max_total_summary_chars",
        ):
            _non_negative_int(getattr(self, field_name), field_name)
        if not isinstance(self.limit_reached, bool):
            raise DepartmentContextBundleError("limit_reached must be a boolean")
        _coerce_string_tuple(self, "reasons")


@dataclass(frozen=True)
class DepartmentAssetContextBundle:
    """Validated department asset summaries that may enter worker runtime context."""

    department_id: str
    worker_id: str
    task_ref: str
    selected_memories: tuple[DepartmentMemoryContextView, ...] = ()
    selected_skill_guidance: tuple[DepartmentSkillGuidanceContextView, ...] = ()
    selected_tool_policy_snapshot: DepartmentToolPolicyContextSnapshot | None = None
    selection_reasons: tuple[DepartmentContextSelectionReason, ...] = ()
    excluded_assets: tuple[DepartmentContextExcludedAsset, ...] = ()
    sensitivity_summary: DepartmentContextSensitivitySummary = field(
        default_factory=DepartmentContextSensitivitySummary
    )
    limit_summary: DepartmentContextLimitSummary = field(
        default_factory=DepartmentContextLimitSummary
    )
    audit_summary: str = ""
    created_at: str = ""
    schema_version: int = DEPARTMENT_CONTEXT_BUNDLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        validate_org_node_id(self.department_id)
        validate_worker_id(self.worker_id)
        _validate_relative_ref(self.task_ref, "task_ref")
        _coerce_typed_tuple(self, "selected_memories", DepartmentMemoryContextView)
        _coerce_typed_tuple(
            self, "selected_skill_guidance", DepartmentSkillGuidanceContextView
        )
        if self.selected_tool_policy_snapshot is not None and not isinstance(
            self.selected_tool_policy_snapshot, DepartmentToolPolicyContextSnapshot
        ):
            raise DepartmentContextBundleError(
                "selected_tool_policy_snapshot must be a DepartmentToolPolicyContextSnapshot"
            )
        _coerce_typed_tuple(self, "selection_reasons", DepartmentContextSelectionReason)
        _coerce_typed_tuple(self, "excluded_assets", DepartmentContextExcludedAsset)
        if not isinstance(self.sensitivity_summary, DepartmentContextSensitivitySummary):
            raise DepartmentContextBundleError(
                "sensitivity_summary must be a DepartmentContextSensitivitySummary"
            )
        if not isinstance(self.limit_summary, DepartmentContextLimitSummary):
            raise DepartmentContextBundleError(
                "limit_summary must be a DepartmentContextLimitSummary"
            )
        if _selected_asset_ids(self) and not self.selection_reasons:
            raise DepartmentContextBundleError(
                "selection_reasons must explain selected assets"
            )
        _string_value(self.audit_summary, "audit_summary")
        _require_string(self.created_at, "created_at")
        validate_context_bundle_payload(department_context_bundle_to_dict(self))


def validate_context_bundle_payload(payload: Mapping[str, Any]) -> None:
    """Reject raw, private, or credential-bearing fields from context bundles."""

    if not isinstance(payload, Mapping):
        raise DepartmentContextBundleError("context bundle payload must be an object")
    _reject_sensitive_payload(payload, "payload")


def department_memory_context_view_to_dict(
    view: DepartmentMemoryContextView,
) -> dict[str, Any]:
    return {
        "department_id": view.department_id,
        "memory_id": view.memory_id,
        "kind": view.kind,
        "summary": view.summary,
        "tags": list(view.tags),
        "source_refs": list(view.source_refs),
        "freshness": view.freshness,
        "sensitivity": view.sensitivity,
        "accepted_state": view.accepted_state,
        "schema_version": view.schema_version,
    }


def department_memory_context_view_from_dict(
    data: Mapping[str, Any],
) -> DepartmentMemoryContextView:
    data = _require_mapping(data, "memory context view")
    _reject_unknown_fields(data, _MEMORY_VIEW_FIELDS, "memory context view")
    return DepartmentMemoryContextView(
        department_id=_require_string(data.get("department_id"), "department_id"),
        memory_id=_require_string(data.get("memory_id"), "memory_id"),
        kind=_require_string(data.get("kind"), "kind"),
        summary=_require_string(data.get("summary"), "summary"),
        tags=_string_tuple(data.get("tags", ()), "tags"),
        source_refs=_string_tuple(data.get("source_refs", ()), "source_refs"),
        freshness=_string_value(data.get("freshness", ""), "freshness"),
        sensitivity=_require_string(data.get("sensitivity"), "sensitivity"),
        accepted_state=_string_value(data.get("accepted_state", "accepted"), "accepted_state"),
        schema_version=data.get(
            "schema_version", DEPARTMENT_CONTEXT_BUNDLE_SCHEMA_VERSION
        ),
    )


def department_skill_guidance_context_view_to_dict(
    view: DepartmentSkillGuidanceContextView,
) -> dict[str, Any]:
    return {
        "department_id": view.department_id,
        "binding_id": view.binding_id,
        "skill_id": view.skill_id,
        "display_title": view.display_title,
        "guidance_summary": view.guidance_summary,
        "constraints": list(view.constraints),
        "guardrail_refs": list(view.guardrail_refs),
        "audit_refs": list(view.audit_refs),
        "source_refs": list(view.source_refs),
        "sensitivity": view.sensitivity,
        "accepted_state": view.accepted_state,
        "schema_version": view.schema_version,
    }


def department_skill_guidance_context_view_from_dict(
    data: Mapping[str, Any],
) -> DepartmentSkillGuidanceContextView:
    data = _require_mapping(data, "skill guidance context view")
    _reject_unknown_fields(data, _SKILL_VIEW_FIELDS, "skill guidance context view")
    return DepartmentSkillGuidanceContextView(
        department_id=_require_string(data.get("department_id"), "department_id"),
        binding_id=_require_string(data.get("binding_id"), "binding_id"),
        skill_id=_require_string(data.get("skill_id"), "skill_id"),
        display_title=_require_string(data.get("display_title"), "display_title"),
        guidance_summary=_require_string(data.get("guidance_summary"), "guidance_summary"),
        constraints=_string_tuple(data.get("constraints", ()), "constraints"),
        guardrail_refs=_string_tuple(data.get("guardrail_refs", ()), "guardrail_refs"),
        audit_refs=_string_tuple(data.get("audit_refs", ()), "audit_refs"),
        source_refs=_string_tuple(data.get("source_refs", ()), "source_refs"),
        sensitivity=_require_string(data.get("sensitivity"), "sensitivity"),
        accepted_state=_string_value(data.get("accepted_state", "accepted"), "accepted_state"),
        schema_version=data.get(
            "schema_version", DEPARTMENT_CONTEXT_BUNDLE_SCHEMA_VERSION
        ),
    )


def department_tool_policy_context_snapshot_to_dict(
    snapshot: DepartmentToolPolicyContextSnapshot,
) -> dict[str, Any]:
    return {
        "department_id": snapshot.department_id,
        "allowed_tool_summaries": list(snapshot.allowed_tool_summaries),
        "denied_tool_summaries": list(snapshot.denied_tool_summaries),
        "approval_required_tool_summaries": list(
            snapshot.approval_required_tool_summaries
        ),
        "denial_reasons": list(snapshot.denial_reasons),
        "approval_status_refs": list(snapshot.approval_status_refs),
        "policy_refs": list(snapshot.policy_refs),
        "audit_refs": list(snapshot.audit_refs),
        "schema_version": snapshot.schema_version,
    }


def department_tool_policy_context_snapshot_from_dict(
    data: Mapping[str, Any],
) -> DepartmentToolPolicyContextSnapshot:
    data = _require_mapping(data, "tool policy context snapshot")
    _reject_unknown_fields(data, _TOOL_POLICY_FIELDS, "tool policy context snapshot")
    return DepartmentToolPolicyContextSnapshot(
        department_id=_require_string(data.get("department_id"), "department_id"),
        allowed_tool_summaries=_string_tuple(
            data.get("allowed_tool_summaries", ()), "allowed_tool_summaries"
        ),
        denied_tool_summaries=_string_tuple(
            data.get("denied_tool_summaries", ()), "denied_tool_summaries"
        ),
        approval_required_tool_summaries=_string_tuple(
            data.get("approval_required_tool_summaries", ()),
            "approval_required_tool_summaries",
        ),
        denial_reasons=_string_tuple(data.get("denial_reasons", ()), "denial_reasons"),
        approval_status_refs=_string_tuple(
            data.get("approval_status_refs", ()), "approval_status_refs"
        ),
        policy_refs=_string_tuple(data.get("policy_refs", ()), "policy_refs"),
        audit_refs=_string_tuple(data.get("audit_refs", ()), "audit_refs"),
        schema_version=data.get(
            "schema_version", DEPARTMENT_CONTEXT_BUNDLE_SCHEMA_VERSION
        ),
    )


def department_context_bundle_to_dict(
    bundle: DepartmentAssetContextBundle,
) -> dict[str, Any]:
    return {
        "department_id": bundle.department_id,
        "worker_id": bundle.worker_id,
        "task_ref": bundle.task_ref,
        "selected_memories": [
            department_memory_context_view_to_dict(view)
            for view in bundle.selected_memories
        ],
        "selected_skill_guidance": [
            department_skill_guidance_context_view_to_dict(view)
            for view in bundle.selected_skill_guidance
        ],
        "selected_tool_policy_snapshot": (
            department_tool_policy_context_snapshot_to_dict(
                bundle.selected_tool_policy_snapshot
            )
            if bundle.selected_tool_policy_snapshot is not None
            else None
        ),
        "selection_reasons": [
            _selection_reason_to_dict(reason) for reason in bundle.selection_reasons
        ],
        "excluded_assets": [
            _excluded_asset_to_dict(excluded) for excluded in bundle.excluded_assets
        ],
        "sensitivity_summary": _sensitivity_summary_to_dict(
            bundle.sensitivity_summary
        ),
        "limit_summary": _limit_summary_to_dict(bundle.limit_summary),
        "audit_summary": bundle.audit_summary,
        "created_at": bundle.created_at,
        "schema_version": bundle.schema_version,
    }


def department_context_bundle_from_dict(
    data: Mapping[str, Any],
) -> DepartmentAssetContextBundle:
    data = _require_mapping(data, "department context bundle")
    _reject_unknown_fields(data, _BUNDLE_FIELDS, "department context bundle")
    return DepartmentAssetContextBundle(
        department_id=_require_string(data.get("department_id"), "department_id"),
        worker_id=_require_string(data.get("worker_id"), "worker_id"),
        task_ref=_require_string(data.get("task_ref"), "task_ref"),
        selected_memories=tuple(
            department_memory_context_view_from_dict(item)
            for item in _sequence(data.get("selected_memories", ()), "selected_memories")
        ),
        selected_skill_guidance=tuple(
            department_skill_guidance_context_view_from_dict(item)
            for item in _sequence(
                data.get("selected_skill_guidance", ()), "selected_skill_guidance"
            )
        ),
        selected_tool_policy_snapshot=(
            department_tool_policy_context_snapshot_from_dict(
                data["selected_tool_policy_snapshot"]
            )
            if data.get("selected_tool_policy_snapshot") is not None
            else None
        ),
        selection_reasons=tuple(
            _selection_reason_from_dict(item)
            for item in _sequence(data.get("selection_reasons", ()), "selection_reasons")
        ),
        excluded_assets=tuple(
            _excluded_asset_from_dict(item)
            for item in _sequence(data.get("excluded_assets", ()), "excluded_assets")
        ),
        sensitivity_summary=_sensitivity_summary_from_dict(
            data.get("sensitivity_summary", {})
        ),
        limit_summary=_limit_summary_from_dict(data.get("limit_summary", {})),
        audit_summary=_string_value(data.get("audit_summary", ""), "audit_summary"),
        created_at=_require_string(data.get("created_at"), "created_at"),
        schema_version=data.get(
            "schema_version", DEPARTMENT_CONTEXT_BUNDLE_SCHEMA_VERSION
        ),
    )


def _selection_reason_to_dict(
    reason: DepartmentContextSelectionReason,
) -> dict[str, Any]:
    return {
        "asset_kind": reason.asset_kind,
        "asset_id": reason.asset_id,
        "reasons": list(reason.reasons),
        "source_refs": list(reason.source_refs),
    }


def _selection_reason_from_dict(
    data: Mapping[str, Any],
) -> DepartmentContextSelectionReason:
    data = _require_mapping(data, "selection reason")
    _reject_unknown_fields(data, _SELECTION_REASON_FIELDS, "selection reason")
    return DepartmentContextSelectionReason(
        asset_kind=_require_string(data.get("asset_kind"), "asset_kind"),
        asset_id=_require_string(data.get("asset_id"), "asset_id"),
        reasons=_string_tuple(data.get("reasons", ()), "reasons"),
        source_refs=_string_tuple(data.get("source_refs", ()), "source_refs"),
    )


def _excluded_asset_to_dict(asset: DepartmentContextExcludedAsset) -> dict[str, Any]:
    return {
        "asset_kind": asset.asset_kind,
        "asset_id": asset.asset_id,
        "reason": asset.reason,
        "sensitivity": asset.sensitivity,
        "source_refs": list(asset.source_refs),
    }


def _excluded_asset_from_dict(
    data: Mapping[str, Any],
) -> DepartmentContextExcludedAsset:
    data = _require_mapping(data, "excluded asset")
    _reject_unknown_fields(data, _EXCLUDED_ASSET_FIELDS, "excluded asset")
    return DepartmentContextExcludedAsset(
        asset_kind=_require_string(data.get("asset_kind"), "asset_kind"),
        asset_id=_require_string(data.get("asset_id"), "asset_id"),
        reason=_require_string(data.get("reason"), "reason"),
        sensitivity=_require_string(data.get("sensitivity"), "sensitivity"),
        source_refs=_string_tuple(data.get("source_refs", ()), "source_refs"),
    )


def _sensitivity_summary_to_dict(
    summary: DepartmentContextSensitivitySummary,
) -> dict[str, Any]:
    return {
        "highest_included_sensitivity": summary.highest_included_sensitivity,
        "included_sensitivities": list(summary.included_sensitivities),
        "excluded_sensitive_count": summary.excluded_sensitive_count,
    }


def _sensitivity_summary_from_dict(
    data: Mapping[str, Any],
) -> DepartmentContextSensitivitySummary:
    data = _require_mapping(data, "sensitivity summary")
    _reject_unknown_fields(data, _SENSITIVITY_SUMMARY_FIELDS, "sensitivity summary")
    return DepartmentContextSensitivitySummary(
        highest_included_sensitivity=_string_value(
            data.get("highest_included_sensitivity", "none"),
            "highest_included_sensitivity",
        ),
        included_sensitivities=_string_tuple(
            data.get("included_sensitivities", ()), "included_sensitivities"
        ),
        excluded_sensitive_count=data.get("excluded_sensitive_count", 0),
    )


def _limit_summary_to_dict(summary: DepartmentContextLimitSummary) -> dict[str, Any]:
    return {
        "memory_items": summary.memory_items,
        "skill_items": summary.skill_items,
        "total_items": summary.total_items,
        "max_memory_items": summary.max_memory_items,
        "max_skill_items": summary.max_skill_items,
        "max_total_items": summary.max_total_items,
        "max_total_summary_chars": summary.max_total_summary_chars,
        "limit_reached": summary.limit_reached,
        "reasons": list(summary.reasons),
    }


def _limit_summary_from_dict(data: Mapping[str, Any]) -> DepartmentContextLimitSummary:
    data = _require_mapping(data, "limit summary")
    _reject_unknown_fields(data, _LIMIT_SUMMARY_FIELDS, "limit summary")
    return DepartmentContextLimitSummary(
        memory_items=data.get("memory_items", 0),
        skill_items=data.get("skill_items", 0),
        total_items=data.get("total_items", 0),
        max_memory_items=data.get("max_memory_items", 0),
        max_skill_items=data.get("max_skill_items", 0),
        max_total_items=data.get("max_total_items", 0),
        max_total_summary_chars=data.get("max_total_summary_chars", 0),
        limit_reached=data.get("limit_reached", False),
        reasons=_string_tuple(data.get("reasons", ()), "reasons"),
    )


_MEMORY_VIEW_FIELDS = {
    "department_id",
    "memory_id",
    "kind",
    "summary",
    "tags",
    "source_refs",
    "freshness",
    "sensitivity",
    "accepted_state",
    "schema_version",
}
_SKILL_VIEW_FIELDS = {
    "department_id",
    "binding_id",
    "skill_id",
    "display_title",
    "guidance_summary",
    "constraints",
    "guardrail_refs",
    "audit_refs",
    "source_refs",
    "sensitivity",
    "accepted_state",
    "schema_version",
}
_TOOL_POLICY_FIELDS = {
    "department_id",
    "allowed_tool_summaries",
    "denied_tool_summaries",
    "approval_required_tool_summaries",
    "denial_reasons",
    "approval_status_refs",
    "policy_refs",
    "audit_refs",
    "schema_version",
}
_SELECTION_REASON_FIELDS = {"asset_kind", "asset_id", "reasons", "source_refs"}
_EXCLUDED_ASSET_FIELDS = {
    "asset_kind",
    "asset_id",
    "reason",
    "sensitivity",
    "source_refs",
}
_SENSITIVITY_SUMMARY_FIELDS = {
    "highest_included_sensitivity",
    "included_sensitivities",
    "excluded_sensitive_count",
}
_LIMIT_SUMMARY_FIELDS = {
    "memory_items",
    "skill_items",
    "total_items",
    "max_memory_items",
    "max_skill_items",
    "max_total_items",
    "max_total_summary_chars",
    "limit_reached",
    "reasons",
}
_BUNDLE_FIELDS = {
    "department_id",
    "worker_id",
    "task_ref",
    "selected_memories",
    "selected_skill_guidance",
    "selected_tool_policy_snapshot",
    "selection_reasons",
    "excluded_assets",
    "sensitivity_summary",
    "limit_summary",
    "audit_summary",
    "created_at",
    "schema_version",
}


def _selected_asset_ids(bundle: DepartmentAssetContextBundle) -> set[tuple[str, str]]:
    selected = {
        ("memory", view.memory_id)
        for view in bundle.selected_memories
    }
    selected.update(
        ("skill_guidance", view.binding_id)
        for view in bundle.selected_skill_guidance
    )
    if bundle.selected_tool_policy_snapshot is not None:
        selected.add(("tool_policy", bundle.selected_tool_policy_snapshot.department_id))
    return selected


def _require_schema_version(schema_version: Any) -> None:
    if schema_version != DEPARTMENT_CONTEXT_BUNDLE_SCHEMA_VERSION:
        raise DepartmentContextBundleError(
            f"Unsupported department context schema_version: {schema_version!r}"
        )


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise DepartmentContextBundleError(f"{field_name} must be a non-empty string")
    return value


def _string_value(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise DepartmentContextBundleError(f"{field_name} must be a string")
    return value


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise DepartmentContextBundleError(f"{field_name} must be a list of strings")
    return tuple(_require_string(item, field_name) for item in value)


def _coerce_string_tuple(instance: object, field_name: str) -> None:
    object.__setattr__(
        instance,
        field_name,
        tuple(_require_string(item, field_name) for item in getattr(instance, field_name)),
    )


def _coerce_typed_tuple(instance: object, field_name: str, item_type: type) -> None:
    values = getattr(instance, field_name)
    if not isinstance(values, tuple) or any(
        not isinstance(value, item_type) for value in values
    ):
        raise DepartmentContextBundleError(
            f"{field_name} must be a tuple of {item_type.__name__}"
        )


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DepartmentContextBundleError(f"{field_name} must be an object")
    validate_context_bundle_payload(value)
    return value


def _sequence(value: Any, field_name: str) -> tuple[Any, ...]:
    if not isinstance(value, (list, tuple)):
        raise DepartmentContextBundleError(f"{field_name} must be a list")
    return tuple(value)


def _non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DepartmentContextBundleError(
            f"{field_name} must be a non-negative integer"
        )
    return value


def _validate_path_segment(value: str, field_name: str) -> str:
    _require_string(value, field_name)
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise DepartmentContextBundleError(f"{field_name} must be a single path segment")
    return value


def _validate_relative_ref(value: str, field_name: str) -> str:
    _require_string(value, field_name)
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or ".." in posix.parts
        or ".." in windows.parts
    ):
        raise DepartmentContextBundleError(
            f"{field_name} must stay within allowed storage"
        )
    return value


def _validate_relative_or_text(value: str, field_name: str) -> str:
    _require_string(value, field_name)
    if "/" in value or "\\" in value:
        return _validate_relative_ref(value, field_name)
    return value


def _require_accepted_state(value: str) -> None:
    if value != "accepted":
        raise DepartmentContextBundleError(
            "context bundle views must come from accepted assets"
        )


def _reject_unknown_fields(
    data: Mapping[str, Any], allowed_fields: set[str], field_name: str
) -> None:
    unknown_fields = sorted(set(data) - allowed_fields)
    if unknown_fields:
        joined = ", ".join(unknown_fields)
        raise DepartmentContextBundleError(f"{field_name} has unknown fields: {joined}")


def _reject_sensitive_payload(value: Any, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in _SENSITIVE_FIELD_NAMES:
                raise DepartmentContextBundleError(
                    f"{path}.{key_text} contains sensitive data"
                )
            _reject_sensitive_payload(item, f"{path}.{key_text}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_sensitive_payload(item, f"{path}[{index}]")

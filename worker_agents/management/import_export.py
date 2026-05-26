"""Import/export and retention planning models for worker agent management."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable, Mapping

from .read_models import ManagementRiskSeverity, ManagementSourceRef, source_ref_to_dict


EXPORT_SCHEMA_VERSION = 1
SECRET_MARKERS = ("secret", "token", "credential", "api_key", "password")
RAW_TRANSCRIPT_MARKERS = ("raw_transcript", "transcript_body", "stdout", "stderr")


class ExportSectionKind(StrEnum):
    REGISTRY = "registry"
    ORGANIZATION = "organization"
    DEPARTMENTS = "departments"
    ASSETS = "assets"
    HISTORY = "history"
    MANIFESTS = "manifests"


class CleanupCandidateKind(StrEnum):
    RUNTIME_CACHE = "runtime_cache"
    TRANSCRIPT_SUMMARY = "transcript_summary"
    TEMPORARY_ARTIFACT = "temporary_artifact"
    TASK_DATA = "task_data"
    ACCEPTED_ASSET = "accepted_asset"
    AUDIT_SUMMARY = "audit_summary"


@dataclass(frozen=True)
class ImportValidationIssue:
    code: str
    message: str
    severity: ManagementRiskSeverity | str = ManagementRiskSeverity.WARNING
    source_ref: ManagementSourceRef | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "severity", ManagementRiskSeverity(self.severity))


@dataclass(frozen=True)
class ImportDryRunReport:
    profile_id: str
    blockers: tuple[ImportValidationIssue, ...] = ()
    warnings: tuple[ImportValidationIssue, ...] = ()
    user_confirmations: tuple[str, ...] = ()
    proposed_steps: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "blockers", tuple(self.blockers))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        object.__setattr__(self, "user_confirmations", tuple(self.user_confirmations))
        object.__setattr__(self, "proposed_steps", tuple(self.proposed_steps))


@dataclass(frozen=True)
class RetentionCleanupItem:
    item_id: str
    item_kind: CleanupCandidateKind | str
    estimated_size_bytes: int = 0
    reason: str = ""
    protected: bool = False
    blocked: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "item_kind", CleanupCandidateKind(self.item_kind))


@dataclass(frozen=True)
class RetentionCleanupPlan:
    candidates: tuple[RetentionCleanupItem, ...] = ()
    protected_items: tuple[RetentionCleanupItem, ...] = ()
    blocked_items: tuple[RetentionCleanupItem, ...] = ()
    estimated_size_bytes: int = 0
    request_action: str = "request_retention_cleanup"

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidates", tuple(self.candidates))
        object.__setattr__(self, "protected_items", tuple(self.protected_items))
        object.__setattr__(self, "blocked_items", tuple(self.blocked_items))


@dataclass(frozen=True)
class ExportPackageSection:
    section_kind: ExportSectionKind | str
    count: int
    checksum: str
    source_ref: ManagementSourceRef
    sensitivity_summary: str = "low"

    def __post_init__(self) -> None:
        object.__setattr__(self, "section_kind", ExportSectionKind(self.section_kind))


@dataclass(frozen=True)
class WorkerAgentsExportPackageManifest:
    profile_id: str
    created_at: str
    schema_version: int = EXPORT_SCHEMA_VERSION
    sections: tuple[ExportPackageSection, ...] = ()
    excluded_sections: tuple[str, ...] = (
        "transcripts",
        "runtime_cache",
        "stdout_stderr",
        "secrets",
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "sections", tuple(self.sections))
        object.__setattr__(self, "excluded_sections", tuple(self.excluded_sections))


def export_package_manifest_to_dict(
    manifest: WorkerAgentsExportPackageManifest,
) -> dict[str, Any]:
    return {
        "schema_version": manifest.schema_version,
        "profile_id": manifest.profile_id,
        "created_at": manifest.created_at,
        "sections": [export_section_to_dict(section) for section in manifest.sections],
        "excluded_sections": list(manifest.excluded_sections),
    }


def export_section_to_dict(section: ExportPackageSection) -> dict[str, Any]:
    return {
        "section_kind": section.section_kind.value,
        "count": section.count,
        "checksum": section.checksum,
        "source_ref": source_ref_to_dict(section.source_ref),
        "sensitivity_summary": section.sensitivity_summary,
    }


def validate_export_payload(payload: Mapping[str, Any]) -> None:
    """Reject payloads that contain secrets, credentials, or raw transcript data."""

    bad_path = _find_forbidden_payload_path(payload)
    if bad_path:
        raise ValueError(f"export payload contains forbidden sensitive field: {bad_path}")


def build_import_dry_run_report(
    manifest: WorkerAgentsExportPackageManifest,
    current_profile_summary: Mapping[str, Any],
) -> ImportDryRunReport:
    """Validate an import package without writing profile-home data."""

    blockers: list[ImportValidationIssue] = []
    warnings: list[ImportValidationIssue] = []
    confirmations: list[str] = []
    if manifest.schema_version != EXPORT_SCHEMA_VERSION:
        blockers.append(_import_issue("schema_mismatch", "export schema version is not supported"))
    current_ids = set(_string_iter(current_profile_summary.get("known_ids", ())))
    incoming_ids = set(
        _string_iter(current_profile_summary.get("incoming_ids", ()))
    )
    conflicts = sorted(current_ids & incoming_ids)
    if conflicts:
        blockers.append(
            _import_issue(
                "id_conflict",
                "incoming ids conflict with current profile: " + ", ".join(conflicts),
            )
        )
    missing_skills = tuple(_string_iter(current_profile_summary.get("missing_skills", ())))
    if missing_skills:
        warnings.append(
            _import_issue(
                "missing_skill",
                "skill references must be installed or remapped: " + ", ".join(missing_skills),
            )
        )
    missing_adapters = tuple(_string_iter(current_profile_summary.get("missing_adapters", ())))
    if missing_adapters:
        warnings.append(
            _import_issue(
                "missing_adapter",
                "external adapters require reconfiguration: " + ", ".join(missing_adapters),
            )
        )
    permission_expansions = tuple(
        _string_iter(current_profile_summary.get("permission_expansions", ()))
    )
    if permission_expansions:
        confirmations.append(
            "permission expansion requires user confirmation: "
            + ", ".join(permission_expansions)
        )
    steps = tuple(
        f"import_{section.section_kind.value}" for section in manifest.sections
    )
    return ImportDryRunReport(
        profile_id=manifest.profile_id,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        user_confirmations=tuple(confirmations),
        proposed_steps=steps,
    )


def import_dry_run_report_to_dict(report: ImportDryRunReport) -> dict[str, Any]:
    return {
        "profile_id": report.profile_id,
        "blockers": [import_issue_to_dict(issue) for issue in report.blockers],
        "warnings": [import_issue_to_dict(issue) for issue in report.warnings],
        "user_confirmations": list(report.user_confirmations),
        "proposed_steps": list(report.proposed_steps),
    }


def import_issue_to_dict(issue: ImportValidationIssue) -> dict[str, Any]:
    return {
        "code": issue.code,
        "message": issue.message,
        "severity": issue.severity.value,
        "source_ref": source_ref_to_dict(issue.source_ref) if issue.source_ref else None,
    }


def build_retention_cleanup_plan(
    items: Iterable[Mapping[str, Any]],
) -> RetentionCleanupPlan:
    """Build a cleanup dry-run plan while preserving long-term assets."""

    candidates: list[RetentionCleanupItem] = []
    protected: list[RetentionCleanupItem] = []
    blocked: list[RetentionCleanupItem] = []
    for item in items:
        cleanup_item = _cleanup_item_from_mapping(item)
        if cleanup_item.protected:
            protected.append(cleanup_item)
        elif cleanup_item.blocked:
            blocked.append(cleanup_item)
        else:
            candidates.append(cleanup_item)
    return RetentionCleanupPlan(
        candidates=tuple(candidates),
        protected_items=tuple(protected),
        blocked_items=tuple(blocked),
        estimated_size_bytes=sum(item.estimated_size_bytes for item in candidates),
    )


def retention_cleanup_plan_to_dict(plan: RetentionCleanupPlan) -> dict[str, Any]:
    return {
        "candidates": [retention_cleanup_item_to_dict(item) for item in plan.candidates],
        "protected_items": [
            retention_cleanup_item_to_dict(item) for item in plan.protected_items
        ],
        "blocked_items": [
            retention_cleanup_item_to_dict(item) for item in plan.blocked_items
        ],
        "estimated_size_bytes": plan.estimated_size_bytes,
        "request_action": plan.request_action,
    }


def retention_cleanup_item_to_dict(item: RetentionCleanupItem) -> dict[str, Any]:
    return {
        "item_id": item.item_id,
        "item_kind": item.item_kind.value,
        "estimated_size_bytes": item.estimated_size_bytes,
        "reason": item.reason,
        "protected": item.protected,
        "blocked": item.blocked,
    }


def dump_export_manifest_json(manifest: WorkerAgentsExportPackageManifest) -> str:
    return json.dumps(export_package_manifest_to_dict(manifest), sort_keys=True, indent=2)


def _find_forbidden_payload_path(value: Any, prefix: str = "") -> str:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            lowered = key_text.lower()
            if any(marker in lowered for marker in (*SECRET_MARKERS, *RAW_TRANSCRIPT_MARKERS)):
                return path
            found = _find_forbidden_payload_path(nested, path)
            if found:
                return found
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            found = _find_forbidden_payload_path(nested, f"{prefix}[{index}]")
            if found:
                return found
    return ""


def _import_issue(code: str, message: str) -> ImportValidationIssue:
    return ImportValidationIssue(
        code=code,
        message=message,
        severity=ManagementRiskSeverity.BLOCKER
        if code in {"schema_mismatch", "id_conflict"}
        else ManagementRiskSeverity.WARNING,
    )


def _string_iter(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set)):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str) and item)


def _cleanup_item_from_mapping(data: Mapping[str, Any]) -> RetentionCleanupItem:
    kind = CleanupCandidateKind(str(data.get("item_kind")))
    protected = bool(data.get("protected", False)) or kind in {
        CleanupCandidateKind.ACCEPTED_ASSET,
        CleanupCandidateKind.AUDIT_SUMMARY,
    }
    blocked = bool(data.get("blocked", False)) or (
        kind == CleanupCandidateKind.TASK_DATA and bool(data.get("active", False))
    )
    return RetentionCleanupItem(
        item_id=str(data.get("item_id", "")),
        item_kind=kind,
        estimated_size_bytes=int(data.get("estimated_size_bytes", 0))
        if isinstance(data.get("estimated_size_bytes", 0), int)
        else 0,
        reason=str(data.get("reason", "")),
        protected=protected,
        blocked=blocked,
    )

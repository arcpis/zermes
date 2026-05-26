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

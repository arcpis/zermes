import pytest

from worker_agents.management import (
    ExportPackageSection,
    ManagementSourceRef,
    WorkerAgentsExportPackageManifest,
    build_import_dry_run_report,
    build_retention_cleanup_plan,
    dump_export_manifest_json,
    export_package_manifest_to_dict,
    import_dry_run_report_to_dict,
    retention_cleanup_plan_to_dict,
    validate_export_payload,
)


def _manifest(schema_version=1):
    return WorkerAgentsExportPackageManifest(
        profile_id="profile-a",
        created_at="2026-05-26T00:00:00Z",
        schema_version=schema_version,
        sections=(
            ExportPackageSection(
                section_kind="registry",
                count=2,
                checksum="sha256:registry",
                source_ref=ManagementSourceRef("worker_registry", "workers"),
            ),
        ),
    )


def test_export_manifest_serializes_sections_and_excludes_transient_data():
    data = export_package_manifest_to_dict(_manifest())

    assert data["sections"][0]["checksum"] == "sha256:registry"
    assert "runtime_cache" in data["excluded_sections"]
    assert "secrets" in data["excluded_sections"]
    assert dump_export_manifest_json(_manifest()).startswith("{\n")


def test_export_payload_rejects_secrets_and_raw_transcripts():
    with pytest.raises(ValueError, match="api_key"):
        validate_export_payload({"registry": [{"api_key": "hidden"}]})
    with pytest.raises(ValueError, match="raw_transcript"):
        validate_export_payload({"history": {"raw_transcript": "hidden"}})


def test_import_dry_run_reports_blockers_warnings_and_confirmations():
    report = build_import_dry_run_report(
        _manifest(),
        {
            "known_ids": ["worker-a"],
            "incoming_ids": ["worker-a"],
            "missing_skills": ["release-review"],
            "missing_adapters": ["external-cli"],
            "permission_expansions": ["shell_write"],
        },
    )
    data = import_dry_run_report_to_dict(report)

    assert data["blockers"][0]["code"] == "id_conflict"
    assert {warning["code"] for warning in data["warnings"]} == {
        "missing_skill",
        "missing_adapter",
    }
    assert data["user_confirmations"] == [
        "permission expansion requires user confirmation: shell_write"
    ]
    assert data["proposed_steps"] == ["import_registry"]


def test_import_dry_run_blocks_schema_mismatch():
    report = build_import_dry_run_report(_manifest(schema_version=999), {})

    assert import_dry_run_report_to_dict(report)["blockers"][0]["code"] == "schema_mismatch"


def test_retention_cleanup_plan_protects_long_term_assets_and_audit():
    plan = build_retention_cleanup_plan(
        [
            {
                "item_id": "cache-1",
                "item_kind": "runtime_cache",
                "estimated_size_bytes": 128,
            },
            {"item_id": "task-1", "item_kind": "task_data", "active": True},
            {"item_id": "asset-1", "item_kind": "accepted_asset"},
            {"item_id": "audit-1", "item_kind": "audit_summary"},
        ]
    )
    data = retention_cleanup_plan_to_dict(plan)

    assert data["estimated_size_bytes"] == 128
    assert data["candidates"][0]["item_id"] == "cache-1"
    assert data["blocked_items"][0]["item_id"] == "task-1"
    assert {item["item_kind"] for item in data["protected_items"]} == {
        "accepted_asset",
        "audit_summary",
    }

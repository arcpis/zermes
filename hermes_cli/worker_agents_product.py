"""Product-facing Worker Agents management helpers.

This module is intentionally a thin adapter over the low-sensitivity
``worker_agents.management`` DTOs.  It reads only the management state file
owned by Worker Agents product flows and the controlled message envelope
store; it never scans raw runtime transcripts or adapter output.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from hermes_cli.config import get_hermes_home
from worker_agents.management import (
    ApprovalActionRequest,
    AssetReviewActionRequest,
    DashboardDataSources,
    EvolutionWizardInput,
    WorkerAgentsExportPackageManifest,
    build_approval_queue_item,
    build_approval_risk_presentation,
    build_asset_review_item,
    build_dashboard_snapshot,
    build_evolution_execution_view,
    build_evolution_proposal_draft,
    build_evolution_proposal_workbench_item,
    build_import_dry_run_report,
    build_managed_chat_thread_summary,
    build_organization_tree_view,
    build_retention_cleanup_plan,
    build_thread_archive_summary_view,
    build_worker_management_list,
    dashboard_snapshot_to_dict,
    evolution_execution_view_to_dict,
    evolution_proposal_draft_to_dict,
    evolution_proposal_workbench_item_to_dict,
    filter_worker_management_list,
    import_dry_run_report_to_dict,
    managed_chat_thread_summary_to_dict,
    organization_tree_view_node_to_dict,
    retention_cleanup_plan_to_dict,
    sort_worker_management_list,
    validate_approval_action_request,
    worker_management_list_item_to_dict,
    approval_action_request_to_dict,
    approval_audit_record_to_dict,
    approval_queue_item_to_dict,
    approval_risk_presentation_to_dict,
    asset_review_item_to_dict,
    create_approval_audit_record,
    thread_archive_summary_view_to_dict,
)
from worker_agents.management.import_export import (
    export_package_manifest_to_dict,
)
from worker_agents.message_router import (
    ChatMessageType,
    ChatParticipantKind,
    ChatParticipantRef,
    ChatRecipientScope,
    MessageDeliveryStatus,
    MessageRouter,
    MessageRouterError,
    MessageVisibility,
    WorkerChatThread,
    WorkerMessageEnvelope,
    chat_thread_from_dict,
    message_envelope_from_dict,
    message_envelope_to_dict,
)
from worker_agents.storage.safe_paths import validate_single_path_segment


MANAGEMENT_STATE_RELATIVE_PATH = Path("worker_agents") / "management" / "dashboard_state.json"
FORBIDDEN_KEY_MARKERS = (
    "api_key",
    "credential",
    "password",
    "raw_transcript",
    "secret",
    "stderr",
    "stdout",
    "token",
    "transcript",
)


@dataclass(frozen=True)
class ChatHistoryQuery:
    thread_id: str
    limit: int = 50
    cursor: str | None = None
    since: str | None = None
    message_type: str | None = None
    sender: str | None = None
    delivery_status: str | None = None


def load_management_state(home: Path | None = None) -> dict[str, Any]:
    """Load the low-sensitivity Worker Agents management state."""

    state_path = _management_state_path(home)
    if not state_path.exists():
        return _empty_management_state()
    with state_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, Mapping):
        raise ValueError("Worker Agents management state must be a JSON object")
    return _sanitize_mapping(data)


def write_management_state_for_tests(data: Mapping[str, Any], home: Path | None = None) -> Path:
    """Write sanitized management state for test fixtures and local demos."""

    state_path = _management_state_path(home)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(_sanitize_mapping(data), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return state_path


def get_overview() -> dict[str, Any]:
    state = load_management_state()
    sources = DashboardDataSources(
        worker_records=_mapping(state.get("worker_records")),
        organization_tree=_optional_mapping(state.get("organization_tree")),
        department_summaries=_sequence(state.get("department_summaries")),
        health_summaries=_mapping(state.get("health_summaries")),
        policy_summaries=_string_mapping(state.get("policy_summaries")),
        source_revision=str(state.get("source_revision", "")),
        source_updated_at=_optional_str(state.get("source_updated_at")),
    )
    return _sanitize_mapping(dashboard_snapshot_to_dict(build_dashboard_snapshot(sources)))


def list_workers(
    *,
    status: str | None = None,
    department_id: str | None = None,
    runtime_type: str | None = None,
    risk_badge: str | None = None,
    sort_key: str = "display_name",
) -> list[dict[str, Any]]:
    snapshot = _dashboard_snapshot_from_state(load_management_state())
    rows = sort_worker_management_list(
        filter_worker_management_list(
            build_worker_management_list(snapshot),
            status=status,
            department_id=department_id,
            runtime_type=runtime_type,
            risk_badge=risk_badge,
        ),
        sort_key=sort_key,
    )
    return _sanitize_sequence(worker_management_list_item_to_dict(row) for row in rows)


def get_organization_tree() -> list[dict[str, Any]]:
    snapshot = _dashboard_snapshot_from_state(load_management_state())
    return _sanitize_sequence(
        organization_tree_view_node_to_dict(node)
        for node in build_organization_tree_view(snapshot.organization_nodes)
    )


def list_chats() -> list[dict[str, Any]]:
    state = load_management_state()
    return _sanitize_sequence(
        managed_chat_thread_summary_to_dict(
            build_managed_chat_thread_summary(
                thread,
                status=str(thread.get("status", "active")),
                last_summary=str(thread.get("last_summary", thread.get("audit_summary", ""))),
            )
        )
        for thread in _sequence(state.get("threads"))
    )


def list_mentions() -> list[dict[str, Any]]:
    return _sanitize_sequence(_sequence(load_management_state().get("mentions")))


def list_broadcasts() -> list[dict[str, Any]]:
    return _sanitize_sequence(_sequence(load_management_state().get("broadcasts")))


def list_approvals() -> list[dict[str, Any]]:
    items = [build_approval_queue_item(item) for item in _sequence(load_management_state().get("approvals"))]
    return _sanitize_sequence(approval_queue_item_to_dict(item) for item in items)


def list_assets() -> list[dict[str, Any]]:
    items = [build_asset_review_item(item) for item in _sequence(load_management_state().get("assets"))]
    return _sanitize_sequence(asset_review_item_to_dict(item) for item in items)


def list_evolution() -> list[dict[str, Any]]:
    items = [
        build_evolution_proposal_workbench_item(item)
        for item in _sequence(load_management_state().get("evolution"))
    ]
    return _sanitize_sequence(evolution_proposal_workbench_item_to_dict(item) for item in items)


def get_retention_cleanup_plan() -> dict[str, Any]:
    plan = build_retention_cleanup_plan(_sequence(load_management_state().get("retention_candidates")))
    return _sanitize_mapping(retention_cleanup_plan_to_dict(plan))


def get_export_manifest() -> dict[str, Any]:
    raw = _optional_mapping(load_management_state().get("export_manifest")) or {
        "profile_id": "default",
        "created_at": _now_iso(),
        "sections": [],
    }
    manifest = WorkerAgentsExportPackageManifest(
        profile_id=str(raw.get("profile_id", "default")),
        created_at=str(raw.get("created_at", _now_iso())),
    )
    return _sanitize_mapping(export_package_manifest_to_dict(manifest))


def get_import_dry_run(manifest_path: str | None = None) -> dict[str, Any]:
    state = load_management_state()
    raw_manifest = _load_manifest_payload(manifest_path) if manifest_path else _optional_mapping(state.get("export_manifest"))
    manifest = WorkerAgentsExportPackageManifest(
        profile_id=str((raw_manifest or {}).get("profile_id", "default")),
        created_at=str((raw_manifest or {}).get("created_at", _now_iso())),
        schema_version=int((raw_manifest or {}).get("schema_version", 1)),
    )
    report = build_import_dry_run_report(
        manifest,
        _optional_mapping(state.get("import_context")) or {},
    )
    return _sanitize_mapping(import_dry_run_report_to_dict(report))


def get_thread_history(query: ChatHistoryQuery) -> dict[str, Any]:
    thread = _require_thread(query.thread_id)
    messages = _read_thread_messages(query.thread_id)
    filtered = _filter_messages(messages, query)
    start = _cursor_to_index(query.cursor)
    limit = max(1, min(query.limit, 200))
    page = filtered[start : start + limit]
    next_cursor = str(start + limit) if start + limit < len(filtered) else None
    return {
        "thread": managed_chat_thread_summary_to_dict(
            build_managed_chat_thread_summary(thread, status=str(thread.get("status", "active")))
        ),
        "messages": _sanitize_sequence(message_envelope_to_dict(message) for message in page),
        "next_cursor": next_cursor,
    }


def send_chat_message(
    *,
    thread_id: str,
    sender_id: str,
    text: str,
    message_type: str = "normal",
    target_ids: Iterable[str] = (),
    dry_run: bool = False,
) -> dict[str, Any]:
    thread = _require_thread(thread_id)
    _require_writable_thread(thread)
    message = _build_outbound_message(
        thread_id=thread_id,
        sender_id=sender_id,
        text=text,
        message_type=message_type,
        target_ids=tuple(target_ids),
    )
    router = MessageRouter()
    router.add_thread(chat_thread_from_dict(_thread_contract_dict(thread)))
    for existing in _read_thread_messages(thread_id):
        router.append_message(existing)
    if not dry_run:
        router.append_message(message)
        _append_thread_message(message)
    return _action_response(
        action=f"chat_{message_type}",
        target_id=thread_id,
        audit_ref=f"worker_agents/threads/{thread_id}/{message.message_id}",
        summary="Message accepted by the managed message router."
        if not dry_run
        else "Message route validated; no message was written.",
        updated_status="validated" if dry_run else "created",
    )


def apply_approval_action(
    *,
    approval_id: str,
    decision: str,
    actor_id: str,
    reason: str,
    confirm_high_risk: bool = False,
    delegated_reviewer_id: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    item = _find_by_key(list_approvals(), "approval_id", approval_id)
    queue_item = build_approval_queue_item(item)
    request = ApprovalActionRequest(
        approval_id=approval_id,
        decision=decision,
        actor_id=actor_id,
        reason=reason,
        explicit_high_risk_confirmation=confirm_high_risk,
        delegated_reviewer_id=delegated_reviewer_id,
        decided_at=_now_iso(),
    )
    validate_approval_action_request(queue_item, request, allowed_actor_ids=[actor_id])
    audit = create_approval_audit_record(queue_item, request, timestamp=_now_iso())
    return _action_response(
        action=f"approval_{decision}",
        target_id=approval_id,
        audit_ref=f"worker_agents/approvals/{approval_id}/{audit.timestamp}",
        summary="Approval action validated." if dry_run else "Approval action request accepted.",
        updated_status="validated" if dry_run else decision,
        request=approval_action_request_to_dict(request),
        audit=approval_audit_record_to_dict(audit),
    )


def apply_asset_action(
    *,
    proposal_id: str,
    decision: str,
    actor_id: str,
    reason: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    _find_by_key(list_assets(), "proposal_id", proposal_id)
    request = AssetReviewActionRequest(proposal_id, decision, actor_id, reason)
    return _action_response(
        action=f"asset_{decision}",
        target_id=proposal_id,
        audit_ref=f"worker_agents/assets/{proposal_id}/{_now_compact()}",
        summary="Asset review validated." if dry_run else "Asset review action request accepted.",
        updated_status="validated" if dry_run else decision,
        request={
            "proposal_id": request.proposal_id,
            "decision": request.decision.value,
            "actor_id": request.actor_id,
            "reason": request.reason,
            "accepted_refs": list(request.accepted_refs),
            "rejected_refs": list(request.rejected_refs),
        },
    )


def draft_evolution_proposal(**kwargs: Any) -> dict[str, Any]:
    draft = build_evolution_proposal_draft(EvolutionWizardInput(**kwargs))
    return _sanitize_mapping(evolution_proposal_draft_to_dict(draft))


def get_evolution_execution(proposal_id: str) -> dict[str, Any]:
    record = _find_by_key(
        _sequence(load_management_state().get("evolution_executions")),
        "proposal_id",
        proposal_id,
    )
    return _sanitize_mapping(evolution_execution_view_to_dict(build_evolution_execution_view(record)))


def get_approval_risk(approval_id: str) -> dict[str, Any]:
    item = build_approval_queue_item(_find_by_key(list_approvals(), "approval_id", approval_id))
    return _sanitize_mapping(approval_risk_presentation_to_dict(build_approval_risk_presentation(item)))


def list_thread_archives() -> list[dict[str, Any]]:
    return _sanitize_sequence(
        thread_archive_summary_view_to_dict(build_thread_archive_summary_view(item))
        for item in _sequence(load_management_state().get("thread_archives"))
    )


def _dashboard_snapshot_from_state(state: Mapping[str, Any]):
    return build_dashboard_snapshot(
        DashboardDataSources(
            worker_records=_mapping(state.get("worker_records")),
            organization_tree=_optional_mapping(state.get("organization_tree")),
            department_summaries=_sequence(state.get("department_summaries")),
            health_summaries=_mapping(state.get("health_summaries")),
            policy_summaries=_string_mapping(state.get("policy_summaries")),
            source_revision=str(state.get("source_revision", "")),
            source_updated_at=_optional_str(state.get("source_updated_at")),
        )
    )


def _require_thread(thread_id: str) -> dict[str, Any]:
    validate_single_path_segment(thread_id, "thread_id")
    for thread in _sequence(load_management_state().get("threads")):
        if thread.get("thread_id") == thread_id:
            return dict(thread)
    raise ValueError(f"chat thread does not exist: {thread_id!r}")


def _thread_contract_dict(thread: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "thread_id",
        "schema_version",
        "thread_type",
        "participants",
        "title",
        "created_at",
        "updated_at",
        "main_agent_visible",
        "audit_summary",
    }
    return {key: value for key, value in thread.items() if key in allowed}


def _require_writable_thread(thread: Mapping[str, Any]) -> None:
    status = str(thread.get("status", "active")).lower()
    if status in {"archived", "frozen"} or bool(thread.get("read_only", False)):
        raise ValueError("chat thread is read-only")


def _build_outbound_message(
    *,
    thread_id: str,
    sender_id: str,
    text: str,
    message_type: str,
    target_ids: tuple[str, ...],
) -> WorkerMessageEnvelope:
    sender = ChatParticipantRef(ChatParticipantKind.USER, sender_id)
    participant_refs = tuple(
        ChatParticipantRef(ChatParticipantKind.WORKER, target_id)
        for target_id in target_ids
    )
    return WorkerMessageEnvelope(
        message_id=f"msg-{uuid.uuid4().hex[:16]}",
        thread_id=thread_id,
        sender=sender,
        recipient_scope=ChatRecipientScope(
            participant_refs=participant_refs,
            include_entire_thread=not participant_refs,
        ),
        message_type=ChatMessageType(message_type),
        created_at=_now_iso(),
        delivery_status=MessageDeliveryStatus.CREATED,
        visibility=MessageVisibility.TARGETED if participant_refs else MessageVisibility.THREAD,
        body_preview=_redact_text(text[:500]),
        audit_summary="Submitted through Worker Agents product entrypoint.",
    )


def _read_thread_messages(thread_id: str) -> list[WorkerMessageEnvelope]:
    path = _thread_messages_path(thread_id)
    if not path.exists():
        return []
    messages: list[WorkerMessageEnvelope] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        messages.append(message_envelope_from_dict(json.loads(line)))
    return messages


def _append_thread_message(message: WorkerMessageEnvelope) -> None:
    path = _thread_messages_path(message.thread_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(message_envelope_to_dict(message), sort_keys=True) + "\n")


def _thread_messages_path(thread_id: str) -> Path:
    validate_single_path_segment(thread_id, "thread_id")
    return get_hermes_home() / "worker_agents" / "threads" / thread_id / "messages.jsonl"


def _management_state_path(home: Path | None) -> Path:
    return (home or get_hermes_home()) / MANAGEMENT_STATE_RELATIVE_PATH


def _filter_messages(
    messages: list[WorkerMessageEnvelope],
    query: ChatHistoryQuery,
) -> list[WorkerMessageEnvelope]:
    result = []
    for message in messages:
        if query.since and (message.created_at or "") < query.since:
            continue
        if query.message_type and message.message_type.value != query.message_type:
            continue
        if query.delivery_status and message.delivery_status.value != query.delivery_status:
            continue
        if query.sender and message.sender.participant_id != query.sender:
            continue
        result.append(message)
    return result


def _cursor_to_index(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        return max(0, int(cursor))
    except ValueError as exc:
        raise ValueError("cursor must be an integer offset") from exc


def _action_response(
    *,
    action: str,
    target_id: str,
    audit_ref: str,
    summary: str,
    updated_status: str,
    request: Mapping[str, Any] | None = None,
    audit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "action": action,
        "target_id": target_id,
        "audit_ref": audit_ref,
        "updated_status": updated_status,
        "next_required_action": "review_audit_result",
        "summary": summary,
    }
    if request is not None:
        data["request"] = request
    if audit is not None:
        data["audit"] = audit
    return _sanitize_mapping(data)


def _load_manifest_payload(path_text: str) -> Mapping[str, Any]:
    path = Path(path_text).expanduser()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError("import manifest must be a JSON object")
    return _sanitize_mapping(data)


def _find_by_key(items: Iterable[Mapping[str, Any]], key: str, value: str) -> Mapping[str, Any]:
    for item in items:
        if item.get(key) == value:
            return item
    raise ValueError(f"{key} does not exist: {value!r}")


def _sanitize_mapping(data: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in data.items():
        key_text = str(key)
        if _is_forbidden_key(key_text):
            continue
        result[key_text] = _sanitize_value(value)
    return result


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _sanitize_mapping(value)
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _sanitize_sequence(items: Iterable[Any]) -> list[Any]:
    return [_sanitize_value(item) for item in items]


def _redact_text(value: str) -> str:
    lowered = value.lower()
    if any(marker in lowered for marker in FORBIDDEN_KEY_MARKERS):
        return "[redacted summary]"
    return value


def _is_forbidden_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in FORBIDDEN_KEY_MARKERS)


def _empty_management_state() -> dict[str, Any]:
    return {
        "worker_records": {},
        "organization_tree": None,
        "department_summaries": [],
        "threads": [],
        "mentions": [],
        "broadcasts": [],
        "approvals": [],
        "assets": [],
        "evolution": [],
        "retention_candidates": [],
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _optional_mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _string_mapping(value: Any) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): str(item) for key, item in value.items() if isinstance(item, str)}


def _sequence(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

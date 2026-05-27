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
from worker_agents.message_broadcasts import (
    BroadcastImportance,
    BroadcastTarget,
    BroadcastTargetKind,
    broadcast_delivery_record_to_dict,
)
from worker_agents.message_mentions import (
    MentionTarget,
    MentionTargetKind,
    mention_delivery_record_to_dict,
    resolve_mention_targets,
)
from worker_agents.organization import MAIN_AGENT_ID, org_tree_from_dict
from worker_agents.message_router import (
    ChatMessageType,
    ChatParticipantKind,
    ChatParticipantRef,
    ChatRecipientScope,
    ChatThreadType,
    MessageDeliveryStatus,
    MessageRouter,
    MessageRouterError,
    MessageVisibility,
    WorkerChatThread,
    WorkerMessageEnvelope,
    chat_thread_from_dict,
    chat_thread_to_dict,
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


def write_management_state(data: Mapping[str, Any], home: Path | None = None) -> Path:
    """Write sanitized Worker Agents management state for product entrypoints."""

    return write_management_state_for_tests(data, home)


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
    state = _state_with_materialized_department_chats(state)
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


def ensure_department_chat(
    *,
    org_node_id: str,
    user_id: str = "user",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Create or return the default user-present chat for one active department."""

    validate_single_path_segment(org_node_id, "org_node_id")
    validate_single_path_segment(user_id, "user_id")
    state = load_management_state()
    response = _ensure_department_chat_in_state(
        state,
        org_node_id=org_node_id,
        user_id=user_id,
        dry_run=dry_run,
    )
    if response.get("updated_status") == "created" and not dry_run:
        state["source_updated_at"] = _now_iso()
        write_management_state(state)
    return _sanitize_mapping(response)


def ensure_direct_worker_chat(
    *,
    worker_id: str,
    user_id: str = "user",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Create or return the user-present direct chat for one enabled worker.

    This only updates the low-sensitivity product management state. It does not
    create worker profiles, alter the registry, or grant any new permissions.
    """

    validate_single_path_segment(worker_id, "worker_id")
    validate_single_path_segment(user_id, "user_id")
    state = _state_with_materialized_department_chats(load_management_state())
    worker = _optional_mapping(_mapping(state.get("worker_records")).get(worker_id))
    if worker is None:
        raise ValueError(f"worker does not exist: {worker_id!r}")
    status = str(worker.get("status", "")).lower()
    if status != "enabled":
        return _sanitize_mapping(
            {
                "action": "ensure_direct_worker_chat",
                "target_id": worker_id,
                "updated_status": "disabled",
                "disabled_reason": f"worker is not enabled: {status or 'unknown'}",
                "next_required_action": "enable_worker_before_chat",
            }
        )

    existing = _find_direct_thread(state, worker_id, user_id)
    if existing is not None:
        return _sanitize_mapping(
            {
                "action": "ensure_direct_worker_chat",
                "target_id": worker_id,
                "updated_status": "existing",
                "thread": _thread_response(existing),
                "audit_ref": f"worker_agents/threads/{existing['thread_id']}",
                "next_required_action": "open_chat_thread",
            }
        )

    thread = _build_direct_thread(worker, worker_id=worker_id, user_id=user_id)
    if not dry_run:
        state["threads"] = [*_sequence(state.get("threads")), thread]
        state["source_updated_at"] = _now_iso()
        write_management_state(state)
    return _sanitize_mapping(
        {
            "action": "ensure_direct_worker_chat",
            "target_id": worker_id,
            "updated_status": "validated" if dry_run else "created",
            "thread": _thread_response(thread),
            "audit_ref": f"worker_agents/threads/{thread['thread_id']}",
            "next_required_action": "open_chat_thread",
        }
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
    target_kind: str | None = None,
    target_id: str | None = None,
    importance: str = "informational",
    dry_run: bool = False,
) -> dict[str, Any]:
    state = load_management_state()
    routing_state = _state_with_materialized_department_chats(state)
    thread = _require_thread_from_state(routing_state, thread_id)
    _require_writable_thread(thread)
    message = _build_outbound_message(
        thread_id=thread_id,
        sender_id=sender_id,
        text=text,
        message_type=message_type,
        target_ids=tuple(target_ids) if message_type == "normal" else (),
    )
    router = MessageRouter()
    router.add_thread(chat_thread_from_dict(_thread_contract_dict(thread)))
    for existing in _read_thread_messages(thread_id):
        router.append_message(existing)
    delivery_records: tuple[Mapping[str, Any], ...] = ()
    if not dry_run:
        delivery_records = _append_routed_message(
            router=router,
            state=routing_state,
            message=message,
            target_ids=tuple(target_ids),
            target_kind=target_kind,
            target_id=target_id,
            importance=importance,
        )
        _append_thread_message(message)
        if delivery_records:
            _append_delivery_records(state, message.message_type, delivery_records)
            state["source_updated_at"] = _now_iso()
            write_management_state(state)
    else:
        delivery_records = _append_routed_message(
            router=router,
            state=routing_state,
            message=message,
            target_ids=tuple(target_ids),
            target_kind=target_kind,
            target_id=target_id,
            importance=importance,
        )
    return _action_response(
        action=f"chat_{message_type}",
        target_id=thread_id,
        audit_ref=f"worker_agents/threads/{thread_id}/{message.message_id}",
        summary="Message accepted by the managed message router."
        if not dry_run
        else "Message route validated; no message was written.",
        updated_status="validated" if dry_run else "created",
        audit={"delivery_records": list(delivery_records)} if delivery_records else None,
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


def apply_evolution_draft(**kwargs: Any) -> dict[str, Any]:
    """Apply a safe no-blocker create-child draft to the management snapshot.

    This is intentionally scoped to the low-sensitivity management state used by
    the current dashboard product surface. It does not mutate active organization
    executor state, private worker profiles, or runtime task stores.
    """

    dry_run = bool(kwargs.pop("dry_run", False))
    draft = build_evolution_proposal_draft(EvolutionWizardInput(**kwargs))
    draft_data = evolution_proposal_draft_to_dict(draft)
    if draft.blockers:
        raise ValueError("evolution draft has blockers: " + "; ".join(draft.blockers))
    if draft.proposal_kind.value != "create_child_agent":
        raise ValueError("only create_child_agent drafts can be applied to management state")

    requested_worker_id = kwargs.get("requested_worker_id")
    if not isinstance(requested_worker_id, str) or not requested_worker_id:
        raise ValueError("requested_worker_id is required")
    validate_single_path_segment(requested_worker_id, "requested_worker_id")
    target_node_id = str(kwargs.get("target_node_id", ""))
    validate_single_path_segment(target_node_id, "target_node_id")

    state = load_management_state()
    worker_records = dict(_mapping(state.get("worker_records")))
    if requested_worker_id in worker_records:
        raise ValueError(f"worker already exists in management state: {requested_worker_id!r}")

    now = _now_iso()
    organization_tree = _ensure_management_organization_tree(state, target_node_id, now)
    nodes = dict(_mapping(organization_tree.get("nodes")))
    target_node = _optional_mapping(nodes.get(target_node_id))
    if target_node is None:
        raise ValueError(f"target organization node does not exist: {target_node_id!r}")
    if requested_worker_id in nodes:
        raise ValueError(f"organization node already exists: {requested_worker_id!r}")

    reason = str(kwargs.get("reason", "") or "")
    display_name = _display_name_from_id(requested_worker_id)
    child_node = {
        "org_node_id": requested_worker_id,
        "name": display_name,
        "node_type": "department",
        "description": reason,
        "responsibilities": [reason] if reason else [],
        "parent_id": target_node_id,
        "child_ids": [],
        "leader": {"kind": "worker", "worker_id": requested_worker_id},
        "member_worker_ids": [requested_worker_id],
        "chat_policy": {
            "default_thread_policy": "parent_group_chat",
            "allow_default_group_chat": False,
        },
        "lifecycle": "active",
        "schema_version": 1,
    }
    nodes[requested_worker_id] = child_node
    target_children = list(_list_value(target_node.get("child_ids")))
    if requested_worker_id not in target_children:
        target_children.append(requested_worker_id)
    nodes[target_node_id] = {**target_node, "child_ids": target_children}

    revision = _int_value(organization_tree.get("revision", 0)) + 1
    state["organization_tree"] = {
        **organization_tree,
        "revision": revision,
        "updated_at": now,
        "nodes": nodes,
    }
    worker_records[requested_worker_id] = {
        "worker_id": requested_worker_id,
        "display_name": display_name,
        "role": "managed_worker",
        "runtime_type": "internal",
        "status": "enabled",
        "created_at": now,
        "updated_at": now,
        "created_by": str(kwargs.get("actor_id", "")),
        "updated_by": str(kwargs.get("actor_id", "")),
        "metadata": {
            "department_ids": [requested_worker_id],
            "parent_node_id": target_node_id,
            "source": "worker_agents_evolution_apply_draft",
            "summary": reason,
        },
    }
    state["worker_records"] = worker_records
    state["department_summaries"] = _upsert_department_summary(
        _sequence(state.get("department_summaries")),
        department_id=requested_worker_id,
        display_name=display_name,
        owner_worker_id=requested_worker_id,
        reason=reason,
    )
    state["source_revision"] = str(revision)
    state["source_updated_at"] = now
    department_chat = _ensure_department_chat_in_state(
        state,
        org_node_id=target_node_id,
        user_id="user",
        dry_run=dry_run,
    )
    if not dry_run:
        write_management_state(state)
    return _sanitize_mapping(
        {
            "action": "evolution_apply_draft",
            "target_id": requested_worker_id,
            "updated_status": "validated" if dry_run else "created",
            "summary": "Validated create_child_agent draft for Worker Agents management state."
            if dry_run
            else "Applied create_child_agent draft to Worker Agents management state.",
            "draft": draft_data,
            "department_chat": department_chat,
            "overview": _sanitize_mapping(
                dashboard_snapshot_to_dict(
                    build_dashboard_snapshot(
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
                )
            ),
        }
    )


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
    state = _state_with_materialized_department_chats(load_management_state())
    return _require_thread_from_state(state, thread_id)


def _require_thread_from_state(
    state: Mapping[str, Any], thread_id: str
) -> dict[str, Any]:
    validate_single_path_segment(thread_id, "thread_id")
    for thread in _sequence(state.get("threads")):
        if thread.get("thread_id") == thread_id:
            return dict(thread)
    raise ValueError(f"chat thread does not exist: {thread_id!r}")


def _append_routed_message(
    *,
    router: MessageRouter,
    state: Mapping[str, Any],
    message: WorkerMessageEnvelope,
    target_ids: tuple[str, ...],
    target_kind: str | None,
    target_id: str | None,
    importance: str,
) -> tuple[Mapping[str, Any], ...]:
    if message.message_type == ChatMessageType.NORMAL:
        if target_kind or target_id:
            raise ValueError("normal messages do not accept target_kind or target_id")
        router.append_message(message)
        return ()
    if message.message_type == ChatMessageType.MENTION:
        targets = _mention_targets(target_ids, target_kind=target_kind, target_id=target_id)
        records = router.append_mention_message(
            message=message,
            resolved_targets=resolve_mention_targets(
                targets,
                organization_tree=_organization_tree_from_state(state),
                worker_lookup=_mapping(state.get("worker_records")),
            ),
        )
        return tuple(mention_delivery_record_to_dict(record) for record in records)
    if message.message_type == ChatMessageType.BROADCAST:
        target = _broadcast_target(
            thread_id=message.thread_id,
            target_kind=target_kind,
            target_id=target_id,
        )
        explicit_worker_ids = target_ids if target.target_kind == BroadcastTargetKind.EXPLICIT_WORKERS else ()
        records = router.append_broadcast_message(
            message=message,
            target=target,
            importance=BroadcastImportance(importance),
            organization_tree=_organization_tree_from_state(state),
            explicit_worker_ids=explicit_worker_ids,
        )
        return tuple(broadcast_delivery_record_to_dict(record) for record in records)
    raise ValueError(f"unsupported product chat message_type: {message.message_type.value!r}")


def _mention_targets(
    target_ids: tuple[str, ...], *, target_kind: str | None, target_id: str | None
) -> tuple[MentionTarget, ...]:
    raw_targets = tuple(
        item for item in (*target_ids, *((target_id,) if target_id else ())) if item
    )
    if not raw_targets:
        raise ValueError("mention messages require at least one target")
    kind = MentionTargetKind(target_kind) if target_kind else None
    return tuple(MentionTarget(raw_target=raw_target, target_kind=kind) for raw_target in raw_targets)


def _broadcast_target(
    *, thread_id: str, target_kind: str | None, target_id: str | None
) -> BroadcastTarget:
    kind = BroadcastTargetKind(target_kind or BroadcastTargetKind.THREAD.value)
    if kind == BroadcastTargetKind.THREAD:
        return BroadcastTarget(kind, target_id or thread_id)
    if kind == BroadcastTargetKind.EXPLICIT_WORKERS:
        return BroadcastTarget(kind, target_id or "explicit_workers")
    if not target_id:
        raise ValueError(f"{kind.value} broadcasts require target_id")
    return BroadcastTarget(kind, target_id)


def _organization_tree_from_state(state: Mapping[str, Any]):
    tree = _optional_mapping(state.get("organization_tree"))
    if tree is None:
        return None
    data = dict(tree)
    nodes = _mapping(data.get("nodes"))
    data.setdefault("tree_id", "management")
    data.setdefault("root_node_id", _infer_root_node_id(nodes))
    if isinstance(data.get("revision"), str) and str(data["revision"]).isdigit():
        data["revision"] = int(str(data["revision"]))
    return org_tree_from_dict(data)


def _infer_root_node_id(nodes: Mapping[str, Any]) -> str:
    for node_id, node in nodes.items():
        node_data = _optional_mapping(node)
        if node_data is not None and str(node_data.get("node_type", "")).lower() == "root":
            return str(node_id)
    raise ValueError("organization tree root node is missing")


def _append_delivery_records(
    state: dict[str, Any],
    message_type: ChatMessageType,
    records: tuple[Mapping[str, Any], ...],
) -> None:
    if not records:
        return
    if message_type == ChatMessageType.MENTION:
        state["mentions"] = [*_sequence(state.get("mentions")), *records]
        return
    if message_type == ChatMessageType.BROADCAST:
        state["broadcasts"] = [*_sequence(state.get("broadcasts")), *records]


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


def _state_with_materialized_department_chats(state: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(state)
    existing_threads = [dict(thread) for thread in _sequence(result.get("threads"))]
    existing_ids = {str(thread.get("thread_id", "")) for thread in existing_threads}
    materialized = [
        thread
        for thread in _materialized_department_threads(result)
        if str(thread.get("thread_id", "")) not in existing_ids
    ]
    if materialized:
        result["threads"] = [*existing_threads, *materialized]
    else:
        result["threads"] = existing_threads
    return result


def _materialized_department_threads(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    organization_tree = _optional_mapping(state.get("organization_tree"))
    if organization_tree is None:
        return []
    nodes = _mapping(organization_tree.get("nodes"))
    worker_records = _mapping(state.get("worker_records"))
    threads: list[dict[str, Any]] = []
    for node_id in sorted(nodes):
        node = _optional_mapping(nodes.get(node_id))
        if node is None or not _node_supports_department_chat(node):
            continue
        worker_ids = _department_worker_ids(node, nodes)
        enabled_workers = [
            worker_id
            for worker_id in worker_ids
            if _worker_is_enabled(worker_records.get(worker_id))
        ]
        if len(enabled_workers) < 2:
            continue
        threads.append(_build_department_thread(node, enabled_workers, user_id="user"))
    return threads


def _node_supports_department_chat(node: Mapping[str, Any]) -> bool:
    return (
        str(node.get("lifecycle", "")).lower() == "active"
        and str(node.get("node_type", "")).lower() in {"department", "team"}
    )


def _department_worker_ids(
    node: Mapping[str, Any],
    nodes: Mapping[str, Any],
) -> list[str]:
    result: list[str] = []
    leader = _optional_mapping(node.get("leader"))
    if leader is not None and leader.get("kind") == "worker":
        worker_id = leader.get("worker_id")
        if isinstance(worker_id, str) and worker_id:
            result.append(worker_id)
    for worker_id in _list_value(node.get("member_worker_ids")):
        if isinstance(worker_id, str) and worker_id:
            result.append(worker_id)
    # Direct child leads are department members; their own members stay scoped
    # to the child department chat.
    for child_id in _list_value(node.get("child_ids")):
        if not isinstance(child_id, str):
            continue
        child = _optional_mapping(nodes.get(child_id))
        if child is None:
            continue
        child_worker_id = _direct_child_worker_id(child)
        if child_worker_id:
            result.append(child_worker_id)
    return list(dict.fromkeys(result))


def _direct_child_worker_id(node: Mapping[str, Any]) -> str | None:
    if str(node.get("node_type", "")).lower() == "individual":
        worker_id = node.get("individual_worker_id")
        return worker_id if isinstance(worker_id, str) and worker_id else None
    leader = _optional_mapping(node.get("leader"))
    if leader is None or leader.get("kind") != "worker":
        return None
    worker_id = leader.get("worker_id")
    return worker_id if isinstance(worker_id, str) and worker_id else None


def _worker_is_enabled(worker: Any) -> bool:
    record = _optional_mapping(worker)
    return record is not None and str(record.get("status", "")).lower() == "enabled"


def _ensure_department_chat_in_state(
    state: dict[str, Any],
    *,
    org_node_id: str,
    user_id: str,
    dry_run: bool,
) -> dict[str, Any]:
    organization_tree = _optional_mapping(state.get("organization_tree"))
    if organization_tree is None:
        raise ValueError("organization tree is missing")
    nodes = _mapping(organization_tree.get("nodes"))
    node = _optional_mapping(nodes.get(org_node_id))
    if node is None:
        raise ValueError(f"organization node does not exist: {org_node_id!r}")
    thread_id = _department_thread_id(org_node_id)
    existing = _find_thread_by_id(state, thread_id)
    if existing is not None:
        return {
            "action": "ensure_department_chat",
            "target_id": org_node_id,
            "updated_status": "existing",
            "thread": _thread_response(existing),
            "audit_ref": f"worker_agents/threads/{thread_id}",
            "next_required_action": "open_chat_thread",
        }
    if not _node_supports_department_chat(node):
        return _department_chat_skipped_response(
            org_node_id,
            "node is not an active department or team",
        )

    worker_records = _mapping(state.get("worker_records"))
    worker_ids = _department_worker_ids(node, nodes)
    enabled_workers = [
        worker_id
        for worker_id in worker_ids
        if _worker_is_enabled(worker_records.get(worker_id))
    ]
    if len(enabled_workers) < 2:
        return _department_chat_skipped_response(
            org_node_id,
            "department needs an enabled owner and at least one enabled direct member",
        )

    thread = _build_department_thread(node, enabled_workers, user_id=user_id)
    if not dry_run:
        state["threads"] = [*_sequence(state.get("threads")), thread]
    return {
        "action": "ensure_department_chat",
        "target_id": org_node_id,
        "updated_status": "validated" if dry_run else "created",
        "thread": _thread_response(thread),
        "audit_ref": f"worker_agents/threads/{thread_id}",
        "next_required_action": "open_chat_thread",
    }


def _department_chat_skipped_response(org_node_id: str, reason: str) -> dict[str, Any]:
    return {
        "action": "ensure_department_chat",
        "target_id": org_node_id,
        "updated_status": "skipped",
        "disabled_reason": reason,
        "next_required_action": "add_direct_department_member_before_chat",
    }


def _find_thread_by_id(state: Mapping[str, Any], thread_id: str) -> dict[str, Any] | None:
    for thread in _sequence(state.get("threads")):
        if thread.get("thread_id") == thread_id:
            return dict(thread)
    return None


def _department_thread_id(org_node_id: str) -> str:
    return f"dept-{org_node_id}"


def _build_department_thread(
    node: Mapping[str, Any],
    worker_ids: list[str],
    *,
    user_id: str,
) -> dict[str, Any]:
    node_id = str(node.get("org_node_id", ""))
    title = str(node.get("name", node_id))
    thread = WorkerChatThread(
        thread_id=_department_thread_id(node_id),
        thread_type=ChatThreadType.ORGANIZATION_GROUP,
        participants=(
            ChatParticipantRef(ChatParticipantKind.USER, user_id),
            ChatParticipantRef(ChatParticipantKind.MAIN_AGENT, MAIN_AGENT_ID),
            *(
                ChatParticipantRef(ChatParticipantKind.WORKER, worker_id)
                for worker_id in worker_ids
            ),
            ChatParticipantRef(ChatParticipantKind.ORGANIZATION_NODE, node_id),
        ),
        title=title,
        created_at=_now_iso(),
        updated_at=_now_iso(),
        audit_summary=_department_thread_summary(node, worker_ids, user_id),
    )
    data = chat_thread_to_dict(thread)
    data.update(
        {
            "status": "active",
            "org_node_id": node_id,
            "binding_id": f"{node_id}-default",
            "last_summary": _department_thread_summary(node, worker_ids, user_id),
        }
    )
    return data


def _department_thread_summary(
    node: Mapping[str, Any],
    worker_ids: list[str],
    user_id: str,
) -> str:
    node_id = str(node.get("org_node_id", ""))
    title = str(node.get("name", node_id))
    owner_worker_id = _owner_worker_id(node)
    direct_members = [worker_id for worker_id in worker_ids if worker_id != owner_worker_id]
    member_text = ", ".join(direct_members) if direct_members else "none"
    owner_text = owner_worker_id or "none"
    return (
        f"Default department chat for {title}. "
        f"User: {user_id}. Department owner: {owner_text}. "
        f"Direct members: {member_text}."
    )


def _owner_worker_id(node: Mapping[str, Any]) -> str | None:
    leader = _optional_mapping(node.get("leader"))
    if leader is None or leader.get("kind") != "worker":
        return None
    worker_id = leader.get("worker_id")
    return worker_id if isinstance(worker_id, str) and worker_id else None


def _find_direct_thread(
    state: Mapping[str, Any],
    worker_id: str,
    user_id: str,
) -> dict[str, Any] | None:
    expected_id = _direct_thread_id(worker_id, user_id)
    for thread in _sequence(state.get("threads")):
        if thread.get("thread_id") == expected_id:
            return dict(thread)
        if _is_direct_thread_for_worker(thread, worker_id=worker_id, user_id=user_id):
            return dict(thread)
    return None


def _is_direct_thread_for_worker(
    thread: Mapping[str, Any],
    *,
    worker_id: str,
    user_id: str,
) -> bool:
    if str(thread.get("thread_type", "")) != "direct":
        return False
    participants = _sequence(thread.get("participants"))
    return (
        {"kind": "user", "participant_id": user_id} in participants
        and {"kind": "worker", "participant_id": worker_id} in participants
    )


def _build_direct_thread(
    worker: Mapping[str, Any],
    *,
    worker_id: str,
    user_id: str,
) -> dict[str, Any]:
    display_name = str(worker.get("display_name", worker_id))
    thread = WorkerChatThread(
        thread_id=_direct_thread_id(worker_id, user_id),
        thread_type=ChatThreadType.DIRECT,
        participants=(
            ChatParticipantRef(ChatParticipantKind.USER, user_id),
            ChatParticipantRef(ChatParticipantKind.WORKER, worker_id),
        ),
        title=display_name,
        created_at=_now_iso(),
        updated_at=_now_iso(),
        main_agent_visible=True,
        audit_summary=f"Direct user-present worker chat for {worker_id}.",
    )
    data = chat_thread_to_dict(thread)
    data.update({"status": "active", "worker_id": worker_id})
    return data


def _direct_thread_id(worker_id: str, user_id: str) -> str:
    return f"direct-{user_id}-{worker_id}"


def _thread_response(thread: Mapping[str, Any]) -> dict[str, Any]:
    summary = build_managed_chat_thread_summary(
        thread,
        status=str(thread.get("status", "active")),
        last_summary=str(thread.get("last_summary", thread.get("audit_summary", ""))),
    )
    return managed_chat_thread_summary_to_dict(summary)


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


def _ensure_management_organization_tree(
    state: Mapping[str, Any],
    target_node_id: str,
    now: str,
) -> dict[str, Any]:
    existing = _optional_mapping(state.get("organization_tree"))
    if existing is not None:
        return dict(existing)
    if target_node_id != "root":
        raise ValueError("management organization tree is missing; create under 'root' first")
    return {
        "schema_version": 1,
        "tree_id": "active",
        "root_node_id": "root",
        "revision": 0,
        "created_at": now,
        "updated_at": now,
        "nodes": {
            "root": {
                "schema_version": 1,
                "org_node_id": "root",
                "name": "Root",
                "node_type": "root",
                "description": "Worker Agents root organization",
                "responsibilities": [],
                "parent_id": None,
                "child_ids": [],
                "leader": {"kind": "main_agent"},
                "member_worker_ids": [],
                "chat_policy": {
                    "default_thread_policy": "none",
                    "allow_default_group_chat": False,
                },
                "lifecycle": "active",
            }
        },
    }


def _display_name_from_id(value: str) -> str:
    return " ".join(part.capitalize() for part in value.replace("_", "-").split("-") if part) or value


def _list_value(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _int_value(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def _upsert_department_summary(
    summaries: list[Mapping[str, Any]],
    *,
    department_id: str,
    display_name: str,
    owner_worker_id: str,
    reason: str,
) -> list[dict[str, Any]]:
    row = {
        "department_id": department_id,
        "display_name": display_name,
        "owner_worker_id": owner_worker_id,
        "member_count": 1,
        "default_chat_available": False,
        "collaboration_mode": "private_or_parent_chat",
        "public_metadata": {"summary": reason} if reason else {},
    }
    result = [dict(item) for item in summaries if item.get("department_id") != department_id]
    result.append(row)
    return sorted(result, key=lambda item: str(item.get("department_id", "")))

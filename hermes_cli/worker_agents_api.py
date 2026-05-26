"""FastAPI router for Worker Agents dashboard product entrypoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from hermes_cli import worker_agents_product as product


router = APIRouter()


class ChatSendRequest(BaseModel):
    sender_id: str = "user"
    text: str
    message_type: str = Field(default="normal", pattern="^(normal|mention|broadcast)$")
    target_ids: list[str] = Field(default_factory=list)
    dry_run: bool = False


class ApprovalActionBody(BaseModel):
    decision: str
    actor_id: str
    reason: str
    confirm_high_risk: bool = False
    delegated_reviewer_id: str | None = None
    dry_run: bool = False


class AssetActionBody(BaseModel):
    decision: str
    actor_id: str
    reason: str
    dry_run: bool = False


class EvolutionDraftBody(BaseModel):
    proposal_kind: str
    actor_id: str
    target_node_id: str
    requested_worker_id: str | None = None
    destination_node_id: str | None = None
    asset_disposition_ref: str | None = None
    rollback_plan_ref: str | None = None
    active_task_refs: list[str] = Field(default_factory=list)
    reason: str = ""


@router.get("/overview")
def overview() -> dict[str, Any]:
    return product.get_overview()


@router.get("/workers")
def workers(
    status: str | None = None,
    department: str | None = None,
    runtime: str | None = None,
    risk: str | None = None,
    sort: str = "display_name",
) -> list[dict[str, Any]]:
    return product.list_workers(
        status=status,
        department_id=department,
        runtime_type=runtime,
        risk_badge=risk,
        sort_key=sort,
    )


@router.get("/organization")
def organization() -> list[dict[str, Any]]:
    return product.get_organization_tree()


@router.get("/chats")
def chats() -> list[dict[str, Any]]:
    return product.list_chats()


@router.get("/chats/{thread_id}/history")
def chat_history(
    thread_id: str,
    limit: int = 50,
    cursor: str | None = None,
    since: str | None = None,
    message_type: str | None = None,
    sender: str | None = None,
    delivery_status: str | None = None,
) -> dict[str, Any]:
    return _guard(
        lambda: product.get_thread_history(
            product.ChatHistoryQuery(
                thread_id=thread_id,
                limit=limit,
                cursor=cursor,
                since=since,
                message_type=message_type,
                sender=sender,
                delivery_status=delivery_status,
            )
        )
    )


@router.post("/chats/{thread_id}/send")
def chat_send(thread_id: str, body: ChatSendRequest) -> dict[str, Any]:
    return _guard(
        lambda: product.send_chat_message(
            thread_id=thread_id,
            sender_id=body.sender_id,
            text=body.text,
            message_type=body.message_type,
            target_ids=body.target_ids,
            dry_run=body.dry_run,
        )
    )


@router.get("/mentions")
def mentions() -> list[dict[str, Any]]:
    return product.list_mentions()


@router.get("/broadcasts")
def broadcasts() -> list[dict[str, Any]]:
    return product.list_broadcasts()


@router.get("/thread-archives")
def thread_archives() -> list[dict[str, Any]]:
    return product.list_thread_archives()


@router.get("/approvals")
def approvals() -> list[dict[str, Any]]:
    return product.list_approvals()


@router.get("/approvals/{approval_id}/risk")
def approval_risk(approval_id: str) -> dict[str, Any]:
    return _guard(lambda: product.get_approval_risk(approval_id))


@router.post("/approvals/{approval_id}/action")
def approval_action(approval_id: str, body: ApprovalActionBody) -> dict[str, Any]:
    return _guard(
        lambda: product.apply_approval_action(
            approval_id=approval_id,
            decision=body.decision,
            actor_id=body.actor_id,
            reason=body.reason,
            confirm_high_risk=body.confirm_high_risk,
            delegated_reviewer_id=body.delegated_reviewer_id,
            dry_run=body.dry_run,
        )
    )


@router.get("/assets")
def assets() -> list[dict[str, Any]]:
    return product.list_assets()


@router.post("/assets/{proposal_id}/action")
def asset_action(proposal_id: str, body: AssetActionBody) -> dict[str, Any]:
    return _guard(
        lambda: product.apply_asset_action(
            proposal_id=proposal_id,
            decision=body.decision,
            actor_id=body.actor_id,
            reason=body.reason,
            dry_run=body.dry_run,
        )
    )


@router.get("/evolution")
def evolution() -> list[dict[str, Any]]:
    return product.list_evolution()


@router.post("/evolution/draft")
def evolution_draft(body: EvolutionDraftBody) -> dict[str, Any]:
    return _guard(
        lambda: product.draft_evolution_proposal(
            proposal_kind=body.proposal_kind,
            actor_id=body.actor_id,
            target_node_id=body.target_node_id,
            requested_worker_id=body.requested_worker_id,
            destination_node_id=body.destination_node_id,
            asset_disposition_ref=body.asset_disposition_ref,
            rollback_plan_ref=body.rollback_plan_ref,
            active_task_refs=tuple(body.active_task_refs),
            reason=body.reason,
        )
    )


@router.get("/evolution/{proposal_id}/execution")
def evolution_execution(proposal_id: str) -> dict[str, Any]:
    return _guard(lambda: product.get_evolution_execution(proposal_id))


@router.get("/export-manifest")
def export_manifest() -> dict[str, Any]:
    return product.get_export_manifest()


@router.post("/import-dry-run")
def import_dry_run(body: dict[str, Any] | None = None) -> dict[str, Any]:
    manifest_path = None if body is None else body.get("manifest_path")
    return _guard(lambda: product.get_import_dry_run(manifest_path))


@router.get("/cleanup-plan")
def cleanup_plan() -> dict[str, Any]:
    return product.get_retention_cleanup_plan()


def _guard(callback):
    try:
        return callback()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

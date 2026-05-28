"""CLI commands for Worker Agents management views and controlled actions."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Callable, Iterable, Mapping

from hermes_cli import worker_agents_product as product


JsonSupplier = Callable[[argparse.Namespace], Any]


def add_worker_agents_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "worker-agents",
        help="Inspect and operate Worker Agents management consoles",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.set_defaults(func=cmd_worker_agents)
    commands = parser.add_subparsers(dest="worker_agents_command")

    _read_command(commands, "overview", lambda _args: product.get_overview())
    workers = _read_command(commands, "workers", _workers)
    workers.add_argument("--status")
    workers.add_argument("--department", dest="department_id")
    workers.add_argument("--runtime", dest="runtime_type")
    workers.add_argument("--risk", dest="risk_badge")
    workers.add_argument("--sort", default="display_name")
    prompt_summary = _read_command(commands, "prompt-summary", _prompt_summary)
    prompt_summary.add_argument("worker_id")
    _read_command(commands, "organization", lambda _args: product.get_organization_tree())
    _read_command(commands, "chats", lambda _args: product.list_chats())
    history = _read_command(commands, "chat-history", _chat_history)
    history.add_argument("thread_id")
    history.add_argument("--limit", type=int, default=50)
    history.add_argument("--cursor")
    history.add_argument("--since")
    history.add_argument("--message-type")
    history.add_argument("--sender")
    history.add_argument("--delivery-status")
    _read_command(commands, "mentions", lambda _args: product.list_mentions())
    _read_command(commands, "broadcasts", lambda _args: product.list_broadcasts())
    _read_command(commands, "approvals", lambda _args: product.list_approvals())
    _read_command(commands, "assets", lambda _args: product.list_assets())
    _read_command(commands, "evolution", lambda _args: product.list_evolution())
    _read_command(commands, "cleanup-plan", lambda _args: product.get_retention_cleanup_plan())
    _read_command(commands, "export-manifest", lambda _args: product.get_export_manifest())
    import_dry_run = _read_command(commands, "import-dry-run", _import_dry_run)
    import_dry_run.add_argument("--manifest")

    send = _action_command(commands, "send", _send)
    _add_chat_args(send)
    mention = _action_command(commands, "mention", _mention)
    _add_chat_args(mention)
    mention.add_argument("--target", action="append", default=[])
    mention.add_argument("--target-kind")
    mention.add_argument("--target-id")
    broadcast = _action_command(commands, "broadcast", _broadcast)
    _add_chat_args(broadcast)
    broadcast.add_argument("--target-kind", default="thread")
    broadcast.add_argument("--target-id")
    broadcast.add_argument("--target", action="append", default=[])
    broadcast.add_argument("--importance", default="informational")
    direct_chat = _action_command(commands, "direct-chat", _direct_chat)
    direct_chat.add_argument("worker_id")
    direct_chat.add_argument("--user", default="user")
    department_chat = _action_command(commands, "department-chat", _department_chat)
    department_chat.add_argument("org_node_id")
    department_chat.add_argument("--user", default="user")

    approval = commands.add_parser("approval", help="Submit an approval action request")
    approval.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    approval_sub = approval.add_subparsers(dest="approval_action", required=True)
    for action in ("approve", "reject", "request-changes", "delegate"):
        sub = _action_command(approval_sub, action, _approval)
        sub.add_argument("approval_id")
        sub.add_argument("--actor", required=True)
        sub.add_argument("--reason", required=True)
        sub.add_argument("--confirm-high-risk", action="store_true")
        sub.add_argument("--delegate-to")

    asset = commands.add_parser("asset", help="Submit an asset review action request")
    asset.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    asset_sub = asset.add_subparsers(dest="asset_action", required=True)
    for action in ("accept", "reject", "request-redaction", "archive"):
        sub = _action_command(asset_sub, action, _asset)
        sub.add_argument("proposal_id")
        sub.add_argument("--actor", required=True)
        sub.add_argument("--reason", required=True)

    draft = _read_command(commands, "evolution-draft", _evolution_draft)
    draft.add_argument("--proposal-kind", required=True)
    draft.add_argument("--actor", required=True)
    draft.add_argument("--target-node", required=True)
    draft.add_argument("--requested-worker")
    draft.add_argument("--destination-node")
    draft.add_argument("--asset-disposition-ref")
    draft.add_argument("--rollback-plan-ref")
    draft.add_argument("--active-task-ref", action="append", default=[])
    draft.add_argument("--reason", default="")

    apply_draft = _action_command(commands, "evolution-apply-draft", _evolution_apply_draft)
    apply_draft.add_argument("--proposal-kind", required=True)
    apply_draft.add_argument("--actor", required=True)
    apply_draft.add_argument("--target-node", required=True)
    apply_draft.add_argument("--requested-worker")
    apply_draft.add_argument("--destination-node")
    apply_draft.add_argument("--asset-disposition-ref")
    apply_draft.add_argument("--rollback-plan-ref")
    apply_draft.add_argument("--active-task-ref", action="append", default=[])
    apply_draft.add_argument("--reason", default="")


def cmd_worker_agents(args: argparse.Namespace) -> None:
    if not getattr(args, "worker_agents_command", None):
        print("Usage: hermes worker-agents <command>", file=sys.stderr)
        raise SystemExit(2)
    func = getattr(args, "_worker_agents_handler", None)
    if func is None:
        print("Unknown worker-agents command", file=sys.stderr)
        raise SystemExit(2)
    try:
        data = func(args)
    except Exception as exc:
        _print_error(args, exc)
        raise SystemExit(1) from exc
    _print_result(args, data)


def _read_command(
    commands: argparse._SubParsersAction,
    name: str,
    handler: JsonSupplier,
) -> argparse.ArgumentParser:
    parser = commands.add_parser(name)
    parser.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    parser.set_defaults(_worker_agents_handler=handler)
    return parser


def _action_command(
    commands: argparse._SubParsersAction,
    name: str,
    handler: JsonSupplier,
) -> argparse.ArgumentParser:
    parser = commands.add_parser(name)
    parser.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--dry-run", action="store_true")
    parser.set_defaults(_worker_agents_handler=handler)
    return parser


def _add_chat_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("thread_id")
    parser.add_argument("--sender", default="user")
    parser.add_argument("--text", required=True)


def _workers(args: argparse.Namespace) -> Any:
    return product.list_workers(
        status=args.status,
        department_id=args.department_id,
        runtime_type=args.runtime_type,
        risk_badge=args.risk_badge,
        sort_key=args.sort,
    )


def _prompt_summary(args: argparse.Namespace) -> Any:
    return product.get_worker_prompt_summary(args.worker_id)


def _chat_history(args: argparse.Namespace) -> Any:
    return product.get_thread_history(
        product.ChatHistoryQuery(
            thread_id=args.thread_id,
            limit=args.limit,
            cursor=args.cursor,
            since=args.since,
            message_type=args.message_type,
            sender=args.sender,
            delivery_status=args.delivery_status,
        )
    )


def _send(args: argparse.Namespace) -> Any:
    return product.send_chat_message(
        thread_id=args.thread_id,
        sender_id=args.sender,
        text=args.text,
        dry_run=args.dry_run,
        runtime_reply_handler=None
        if args.dry_run
        else product.build_worker_runtime_reply_handler(),
    )


def _mention(args: argparse.Namespace) -> Any:
    return product.send_chat_message(
        thread_id=args.thread_id,
        sender_id=args.sender,
        text=args.text,
        message_type="mention",
        target_ids=args.target,
        target_kind=args.target_kind,
        target_id=args.target_id,
        dry_run=args.dry_run,
        runtime_reply_handler=None
        if args.dry_run
        else product.build_worker_runtime_reply_handler(),
    )


def _broadcast(args: argparse.Namespace) -> Any:
    return product.send_chat_message(
        thread_id=args.thread_id,
        sender_id=args.sender,
        text=args.text,
        message_type="broadcast",
        target_ids=args.target,
        target_kind=args.target_kind,
        target_id=args.target_id,
        importance=args.importance,
        dry_run=args.dry_run,
    )


def _direct_chat(args: argparse.Namespace) -> Any:
    return product.ensure_direct_worker_chat(
        worker_id=args.worker_id,
        user_id=args.user,
        dry_run=args.dry_run,
    )


def _department_chat(args: argparse.Namespace) -> Any:
    return product.ensure_department_chat(
        org_node_id=args.org_node_id,
        user_id=args.user,
        dry_run=args.dry_run,
    )


def _approval(args: argparse.Namespace) -> Any:
    return product.apply_approval_action(
        approval_id=args.approval_id,
        decision=args.approval_action.replace("-", "_"),
        actor_id=args.actor,
        reason=args.reason,
        confirm_high_risk=args.confirm_high_risk,
        delegated_reviewer_id=args.delegate_to,
        dry_run=args.dry_run,
    )


def _asset(args: argparse.Namespace) -> Any:
    return product.apply_asset_action(
        proposal_id=args.proposal_id,
        decision=args.asset_action.replace("-", "_"),
        actor_id=args.actor,
        reason=args.reason,
        dry_run=args.dry_run,
    )


def _evolution_draft(args: argparse.Namespace) -> Any:
    return product.draft_evolution_proposal(
        proposal_kind=args.proposal_kind,
        actor_id=args.actor,
        target_node_id=args.target_node,
        requested_worker_id=args.requested_worker,
        destination_node_id=args.destination_node,
        asset_disposition_ref=args.asset_disposition_ref,
        rollback_plan_ref=args.rollback_plan_ref,
        active_task_refs=tuple(args.active_task_ref),
        reason=args.reason,
    )


def _evolution_apply_draft(args: argparse.Namespace) -> Any:
    return product.apply_evolution_draft(
        proposal_kind=args.proposal_kind,
        actor_id=args.actor,
        target_node_id=args.target_node,
        requested_worker_id=args.requested_worker,
        destination_node_id=args.destination_node,
        asset_disposition_ref=args.asset_disposition_ref,
        rollback_plan_ref=args.rollback_plan_ref,
        active_task_refs=tuple(args.active_task_ref),
        reason=args.reason,
        dry_run=args.dry_run,
    )


def _import_dry_run(args: argparse.Namespace) -> Any:
    return product.get_import_dry_run(args.manifest)


def _print_result(args: argparse.Namespace, data: Any) -> None:
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2, sort_keys=True))
        return
    if isinstance(data, list):
        _print_table(data)
    elif isinstance(data, Mapping) and "messages" in data:
        _print_table(data["messages"])
        if data.get("next_cursor"):
            print(f"next_cursor: {data['next_cursor']}")
    else:
        print(json.dumps(data, indent=2, sort_keys=True))


def _print_error(args: argparse.Namespace, exc: Exception) -> None:
    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "error": {
                        "message": str(exc),
                        "blocker": str(exc),
                        "disabled_reason": str(exc),
                        "source_ref": "worker_agents_product_entrypoint",
                        "next_required_action": "resolve_blocker_and_retry",
                    }
                },
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return
    print(f"Error: {exc}", file=sys.stderr)


def _print_table(rows: Iterable[Mapping[str, Any]]) -> None:
    rows = list(rows)
    if not rows:
        print("(empty)")
        return
    preferred = (
        "worker_id",
        "display_name",
        "status",
        "runtime_type",
        "thread_id",
        "message_id",
        "message_type",
        "delivery_status",
        "approval_id",
        "proposal_id",
        "summary",
    )
    keys = [key for key in preferred if any(key in row for row in rows)]
    if not keys:
        keys = list(rows[0])[:5]
    print("  ".join(key[:24].ljust(24) for key in keys))
    for row in rows:
        print("  ".join(_cell(row.get(key, "")) for key in keys))


def _cell(value: Any) -> str:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, sort_keys=True)
    else:
        text = "" if value is None else str(value)
    return (text[:21] + "...").ljust(24) if len(text) > 24 else text.ljust(24)

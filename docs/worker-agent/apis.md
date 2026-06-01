# Worker Agent API Reference

## CLI

The `hermes worker-agents` command exposes management views and controlled actions. Add `--json` for machine-readable output.

### Read Commands

```bash
hermes worker-agents overview --json
hermes worker-agents workers --status enabled --runtime internal --json
hermes worker-agents organization --json
hermes worker-agents chats --json
hermes worker-agents chat-history <thread_id> --limit 50 --cursor 50 --json
hermes worker-agents mentions --json
hermes worker-agents broadcasts --json
hermes worker-agents approvals --json
hermes worker-agents assets --json
hermes worker-agents evolution --json
hermes worker-agents export-manifest --json
hermes worker-agents import-dry-run --manifest package-manifest.json --json
hermes worker-agents cleanup-plan --json
hermes worker-agents prompt-summary <worker_id>
```

`chat-history` supports `--limit`, `--cursor`, `--since`, `--message-type`, `--sender`, `--delivery-status`.

### Action Commands

Chat sends are validated through the managed message router:

```bash
hermes worker-agents direct-chat <worker_id> --json
hermes worker-agents department-chat <org_node_id> --json
hermes worker-agents send <thread_id> --sender user --text "Status update" --json
hermes worker-agents mention <thread_id> --sender user --target worker-a --text "@worker-a review this" --json
hermes worker-agents broadcast <thread_id> --sender user --text "Team update" --json
```

Approval and asset actions create action request/audit summaries. High-risk approvals require `--confirm-high-risk`:

```bash
hermes worker-agents approval approve <approval_id> --actor lead --reason "Reviewed" --confirm-high-risk --json
hermes worker-agents approval reject <approval_id> --actor lead --reason "Blocked" --json
hermes worker-agents asset reject <proposal_id> --actor lead --reason "Needs redaction" --json
hermes worker-agents evolution-draft --proposal-kind archive_node --actor lead --target-node engineering --json
hermes worker-agents evolution-apply-draft --proposal-kind create_child_agent --actor lead --target-node root --requested-worker frontend --json
```

`evolution-draft` is validation-only. `evolution-apply-draft` updates the low-sensitivity management snapshot only.

## Dashboard API

All endpoints are protected by the dashboard session token and Host header checks.

### Read Endpoints

```
GET /api/worker-agents/overview
GET /api/worker-agents/workers
GET /api/worker-agents/organization
GET /api/worker-agents/chats
GET /api/worker-agents/chats/{thread_id}/history
GET /api/worker-agents/mentions
GET /api/worker-agents/broadcasts
GET /api/worker-agents/approvals
GET /api/worker-agents/assets
GET /api/worker-agents/evolution
GET /api/worker-agents/export-manifest
GET /api/worker-agents/cleanup-plan
```

### Action Endpoints

```
POST /api/worker-agents/workers/{worker_id}/direct-chat
POST /api/worker-agents/chats/{thread_id}/send
POST /api/worker-agents/approvals/{approval_id}/action
POST /api/worker-agents/assets/{proposal_id}/action
POST /api/worker-agents/evolution/draft
POST /api/worker-agents/evolution/apply-draft
POST /api/worker-agents/import-dry-run
```

Responses are sanitized DTOs. Fields such as `raw_transcript`, `stdout`, `stderr`, `secret`, `token`, `credential`, `api_key`, and `password` are removed or redacted.

### Dashboard Page

The `Worker Agents` page has tabs for Overview, Workers, Organization, Chats, Approvals, Assets, Evolution, Import/Export, and Retention. It shows operational state, risks, blockers, read-only chat threads, delivery status, and audit refs.

## Main Agent Tools

The main agent interacts with Worker Agents through three tools in the `worker_messaging` toolset:

### send_worker_message

Post a task to the group chat and @mention target workers. Returns immediately without waiting.

```json
{
  "text": "任务描述",
  "mention_worker_ids": ["coder-agent"],
  "thread_id": "thread-default-group"
}
```

Response:
```json
{
  "status": "dispatched",
  "message_id": "msg-...",
  "task_id": "task-...",
  "dispatched_to": ["coder-agent"],
  "task_summary": "..."
}
```

### check_worker_replies

Check for new Worker replies since last check. Auto-completes pending tasks when Worker replies are detected.

```json
{
  "thread_id": "thread-default-group"
}
```

Response:
```json
{
  "new_replies": [...],
  "completed_tasks": ["task-..."],
  "pending_tasks": [...]
}
```

### wait_for_worker_reply

Block until a Worker replies or timeout expires. For critical tasks only; non-critical tasks should use the async `send_worker_message` + `check_worker_replies` pattern.

```json
{
  "thread_id": "thread-default-group",
  "timeout_seconds": 300,
  "worker_ids": ["coder-agent"]
}
```

# Information Sources

Use this file when the agent needs to know where WorkerAgent product information comes from. Prefer commands first; use files only for read-only inspection or troubleshooting.

## Preferred Product Commands

Current management snapshot:

```bash
zermes worker-agents overview --json
```

Workers:

```bash
zermes worker-agents workers --json
```

Organization tree:

```bash
zermes worker-agents organization --json
```

Chats:

```bash
zermes worker-agents chats --json
zermes worker-agents chat-history <thread_id> --limit 50 --json
```

Evolution and approvals:

```bash
zermes worker-agents evolution --json
zermes worker-agents approvals --json
```

Assets and retention:

```bash
zermes worker-agents assets --json
zermes worker-agents cleanup-plan --json
```

Import/export:

```bash
zermes worker-agents export-manifest --json
zermes worker-agents import-dry-run --manifest <manifest.json> --json
```

## Dashboard API

When operating through the local dashboard server, the corresponding API namespace is:

```text
/api/worker-agents/*
```

Useful endpoints:

```text
GET  /api/worker-agents/overview
GET  /api/worker-agents/workers
GET  /api/worker-agents/organization
GET  /api/worker-agents/chats
GET  /api/worker-agents/chats/{thread_id}/history
POST /api/worker-agents/chats/{thread_id}/send
GET  /api/worker-agents/approvals
POST /api/worker-agents/approvals/{approval_id}/action
GET  /api/worker-agents/assets
POST /api/worker-agents/assets/{proposal_id}/action
GET  /api/worker-agents/evolution
POST /api/worker-agents/evolution/draft
GET  /api/worker-agents/export-manifest
POST /api/worker-agents/import-dry-run
GET  /api/worker-agents/cleanup-plan
```

Dashboard APIs require the existing local dashboard session token. Do not bypass dashboard authentication.

## Profile State Files

The product adapter reads low-sensitivity state from the active profile home:

```text
<HERMES_HOME>/worker_agents/management/dashboard_state.json
```

This file may contain:

- `worker_records`
- `organization_tree`
- `department_summaries`
- `health_summaries`
- `policy_summaries`
- `threads`
- `mentions`
- `broadcasts`
- `approvals`
- `assets`
- `evolution`
- `evolution_executions`
- `retention_candidates`
- `export_manifest`
- `import_context`

Use this file only to understand why product commands return a given result. Do not write it directly.

Controlled chat history is stored by thread id:

```text
<HERMES_HOME>/worker_agents/threads/<thread_id>/messages.jsonl
```

Each line is a managed message envelope. It is not a runtime raw transcript. It should include low-sensitivity fields such as:

- message id
- thread id
- sender
- recipient scope
- message type
- delivery status
- visibility
- body preview
- audit summary
- sensitivity flags

Do not reconstruct raw transcript, stdout, stderr, adapter output, model context, credentials, or private memory from any source.

## Source Code Locations

Read source code only if commands/API are unavailable, unexpectedly fail, or the user asks for implementation changes.

Relevant files:

```text
hermes_cli/worker_agents_product.py   # shared product adapter
hermes_cli/worker_agents_cmd.py       # zermes worker-agents CLI
hermes_cli/worker_agents_api.py       # /api/worker-agents router
hermes_cli/web_server.py              # dashboard API registration
web/src/pages/WorkerAgentsPage.tsx    # dashboard page
worker_agents/management/             # low-sensitivity DTOs and serializers
worker_agents/message_router.py       # managed message route validation
```

When normal organization planning is requested, do not start with these files. Start with product commands and the user's requested tree.

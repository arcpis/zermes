# Worker Agents Dashboard

The dashboard exposes Worker Agents through a built-in `Worker Agents` page and
the `/api/worker-agents/*` API namespace. Both surfaces use the same
low-sensitivity product adapter as the CLI.

## API

All endpoints are protected by the existing dashboard session token and Host
header checks.

Read endpoints:

- `GET /api/worker-agents/overview`
- `GET /api/worker-agents/workers`
- `GET /api/worker-agents/organization`
- `GET /api/worker-agents/chats`
- `GET /api/worker-agents/chats/{thread_id}/history`
- `GET /api/worker-agents/mentions`
- `GET /api/worker-agents/broadcasts`
- `GET /api/worker-agents/approvals`
- `GET /api/worker-agents/assets`
- `GET /api/worker-agents/evolution`
- `GET /api/worker-agents/export-manifest`
- `GET /api/worker-agents/cleanup-plan`

Action endpoints:

- `POST /api/worker-agents/workers/{worker_id}/direct-chat`
- `POST /api/worker-agents/chats/{thread_id}/send`
- `POST /api/worker-agents/approvals/{approval_id}/action`
- `POST /api/worker-agents/assets/{proposal_id}/action`
- `POST /api/worker-agents/evolution/draft`
- `POST /api/worker-agents/evolution/apply-draft`
- `POST /api/worker-agents/import-dry-run`

Responses are sanitized DTOs. Forbidden raw fields such as `raw_transcript`,
`stdout`, `stderr`, `secret`, `token`, `credential`, `api_key`, and `password`
are removed or redacted before the browser sees them.

## Page

The `Worker Agents` page is a work surface with tabs for Overview, Workers,
Organization, Chats, Approvals, Assets, Evolution, Import/Export, and
Retention. It prioritizes operational state: risks, blockers, read-only chat
threads, delivery status, and audit refs.

The Organization tab renders the managed organization tree returned by the API.
Nodes show lifecycle, leader, members, collaboration mode, read-only state, and
warnings. Multi-worker departments can open their default department chat.
Single-worker departments show the `private_or_parent_chat` mode instead of a
redundant group thread.

The Workers tab can open a user-present direct chat for an enabled worker. The
API reuses an existing direct thread when one exists; otherwise it creates a
low-sensitivity thread summary in the management snapshot. Archived, deleted,
or missing workers return a disabled reason instead of creating a chat.

The Chats tab reads controlled message envelopes by `thread_id`. Sending a
normal message, mention, or broadcast calls the API, which validates the route
through the Message Router before appending a managed envelope. Archived,
frozen, or invalid-boundary threads disable the composer.

Department chats and direct worker chats have separate `thread_id` values and
separate `worker_agents/threads/<thread_id>/messages.jsonl` histories. The
dashboard never merges a department conversation into a direct worker chat.

The page does not read runtime raw transcripts or external adapter raw output.

`/evolution/draft` validates wizard input without writes. `/evolution/apply-draft`
accepts the same body for no-blocker `create_child_agent` drafts and updates the
low-sensitivity management snapshot used by Overview, Workers, and Organization.
It is not the controlled executor for active organization state.

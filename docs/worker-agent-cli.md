# Worker Agents CLI

The `hermes worker-agents` command exposes low-sensitivity Worker Agents
management views and controlled action requests. It reads the management state
from the active Hermes profile under `worker_agents/management/` and controlled
message envelopes under `worker_agents/threads/`.

## Read Views

Use `--json` on any subcommand for stable machine-readable output.

```bash
hermes worker-agents overview --json
hermes worker-agents workers --status enabled --runtime internal --json
hermes worker-agents organization --json
hermes worker-agents chats --json
hermes worker-agents chat-history thread-1 --limit 50 --cursor 50 --json
hermes worker-agents approvals --json
hermes worker-agents assets --json
hermes worker-agents evolution --json
hermes worker-agents export-manifest --json
hermes worker-agents import-dry-run --manifest package-manifest.json --json
hermes worker-agents cleanup-plan --json
```

`chat-history` is scoped by `thread_id` and supports `--limit`, `--cursor`,
`--since`, `--message-type`, `--sender`, and `--delivery-status`. It returns
managed message envelopes and display previews only. It does not read runtime
raw transcripts, adapter stdout/stderr, private memory, or credential material.

## Controlled Actions

Chat sends are validated through the managed message router before any envelope
is appended.

```bash
hermes worker-agents direct-chat worker-a --json
hermes worker-agents send thread-1 --sender user --text "Status update" --json
hermes worker-agents mention thread-1 --sender user --target worker-a --text "@worker-a review this" --json
hermes worker-agents broadcast thread-1 --sender user --text "Team update" --json
```

`direct-chat` creates or reuses the user-present direct thread for an enabled
worker. It writes only the low-sensitivity management chat summary; message
history still lives under the returned `thread_id`.

Approval and asset commands create action request/audit summaries. High-risk
approvals require `--confirm-high-risk`.

```bash
hermes worker-agents approval approve approval-1 --actor lead --reason "Reviewed" --confirm-high-risk --json
hermes worker-agents approval reject approval-1 --actor lead --reason "Blocked" --json
hermes worker-agents asset reject asset-1 --actor lead --reason "Needs redaction" --json
hermes worker-agents evolution-draft --proposal-kind archive_node --actor lead --target-node engineering --json
hermes worker-agents evolution-apply-draft --proposal-kind create_child_agent --actor lead --target-node root --requested-worker frontend --json
```

These commands do not directly edit the active organization tree, registry,
department assets, tool policies, or retention data. Mutating services remain
responsible for final state changes.

`evolution-draft` is validation-only and never writes state. Use
`evolution-apply-draft` only for no-blocker `create_child_agent` drafts when
you need to materialize the current dashboard management snapshot; it updates
the low-sensitivity `worker_agents/management/dashboard_state.json` view, not
the executor-owned active organization tree or private worker profile store.

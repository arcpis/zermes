# Worker Agents

Worker Agents management is available from the CLI and the local dashboard.

## CLI

Use `hermes worker-agents` for read-only views and controlled action requests:

```bash
hermes worker-agents overview --json
hermes worker-agents workers --json
hermes worker-agents chats --json
hermes worker-agents chat-history thread-1 --limit 50 --json
hermes worker-agents cleanup-plan --json
```

Messages are scoped to one managed `thread_id`:

```bash
hermes worker-agents send thread-1 --sender user --text "Status update" --json
hermes worker-agents mention thread-1 --sender user --target worker-a --text "@worker-a please review" --json
hermes worker-agents broadcast thread-1 --sender user --text "Team update" --json
```

Approval and asset actions produce audited action requests:

```bash
hermes worker-agents approval approve approval-1 --actor lead --reason "Reviewed" --confirm-high-risk --json
hermes worker-agents asset reject asset-1 --actor lead --reason "Needs redaction" --json
```

## Dashboard

Open the dashboard and select `Worker Agents` in the sidebar. The page contains
tabs for overview, workers, organization, chats, approvals, assets, evolution,
import/export, and retention.

The Chats tab shows controlled message history and disables sending when a
thread is archived, frozen, or outside the managed routing boundary.

## Safety

Worker Agents product surfaces show controlled summaries and message previews.
They do not expose runtime raw transcripts, adapter stdout/stderr, private
memory text, secrets, tokens, credentials, API keys, or passwords.

# Worker Agent Message Router

The message router defines the user-present chat boundary for managed worker
agents. It is implemented in `worker_agents.message_router`.

The router is a coordination layer, not a runtime adapter. It validates and
stores low-sensitivity thread and message envelopes, but it does not launch
workers, execute tools, call external agents, or write worker memory.

## Contracts

`WorkerChatThread` represents a managed conversation:

- `direct`: user plus one WorkerAgent, visible to the main agent for governance.
- `organization_group`: user, Zermes main agent, and workers or organization nodes.
- `project_group`: user, Zermes main agent, and project-specific participants.

`WorkerMessageEnvelope` represents a routed message with sender, recipient
scope, message type, delivery status, visibility, preview text, audit summary,
and sensitivity flags.

The contract intentionally stores participant references rather than embedding
worker profiles, organization trees, private memory, skill bindings, tool
policies, task state, credentials, raw transcripts, or adapter output.

## User-Present Policy

All threads must include exactly one user.

Direct threads must include exactly one worker and remain main-agent visible.
They cannot be used for worker-to-worker private communication.

Group threads must include the user, the Zermes main agent, and at least one
worker or organization node. Organization node participants are only references;
this layer does not expand departments or read the active organization store.

Message routes must stay inside the thread participant list. A sender must be a
thread participant, and targeted recipients must also be thread participants.

## Router Service

`MessageRouter` is a small in-memory service for the foundation layer. It can:

- create user-to-worker direct threads
- create user-present group threads
- append messages
- update basic delivery status
- return low-sensitivity thread and message summaries
- return minimal routed message views for a worker

The service does not call runtime adapters or task executors. Later runtime
adapter integration should consume routed envelopes and write back messages,
requests, results, or artifact summaries through this boundary.

## Mentions

Mention handling is implemented in `worker_agents.message_mentions` and exposed
through `MessageRouter.append_mention_message`.

A mention is a directed responsibility signal, not a task execution request.
The router records one delivery state per resolved target. Mention targets can
refer to workers, departments, teams, or organization nodes. Department and team
mentions route to the node's worker leader by default; missing, inactive,
ambiguous, or ownerless targets are recorded as failed resolution results
instead of being silently dropped.

Supported mention delivery states include pending, seen, public replied, silent
acknowledged, no response needed, rejected, delegated, deferred, internal todo,
timed out, and failed. A worker may acknowledge or defer a mention without
posting a public reply. Internal todo means follow-up tracking only; it does not
create `WorkerTask` state or start a runtime adapter.

## Broadcasts

Broadcast handling is implemented in `worker_agents.message_broadcasts` and
exposed through `MessageRouter.append_broadcast_message`.

A broadcast is low-sensitivity context synchronization. It can target the
current thread, a department, a team, an organization node, or explicit workers
already present in the managed thread. The default organization routing is
conservative: department, team, and organization-node broadcasts route to the
worker leader rather than expanding to every member.

Broadcast delivery states are delivered, seen, handled, ignored, and failed.
Informational broadcasts do not require every worker to reply or even mark seen.
Important and requires-ack broadcasts can appear in main-agent follow-up
summaries, but this layer does not implement UI reminders or confirmation
cards.

## Follow-Up Summaries

Follow-up summaries are implemented in `worker_agents.message_followups`.
`MessageRouter.apply_mention_timeouts` marks eligible open mention deliveries as
timed out, and `MessageRouter.summarize_delivery_followups` returns
low-sensitivity items for main-agent review.

Timeout scans are idempotent and only update tracking records. They do not send
reminder messages, create tasks, call workers, write memory, or invoke external
adapters.

## Summaries

Use `summarize_chat_thread` and `summarize_message` for prompt context, audit,
and UI list output. Summaries include ids, participant counts, worker counts,
message type, delivery status, visibility, preview text, audit summary, and
sensitivity flags.

Summaries intentionally exclude full transcripts, private worker memory,
department memory, tool credentials, environment variables, raw external agent
stdout/stderr, and runtime task state.

Mention, broadcast, and follow-up summaries follow the same low-sensitivity
rule. They store ids, target summaries, delivery states, timestamps, and audit
summaries, not raw transcripts, private memory, credentials, environment
variables, or external adapter output.

## Storage Boundary

Important long-term thread summaries should live under profile home:

```text
<zermes_home>/worker_agents/threads/
```

Clearable runtime transcripts, detailed event logs, caches, and temporary debug
state should live under install data:

```text
<install_dir>/data/worker_agents/threads/
```

Deleting runtime `data/` must not delete worker identity, organization
structure, important thread summaries, or retained manifest references.
Important mention and broadcast audit summaries should follow the same boundary:
long-lived summaries belong under profile home, while raw event logs and
temporary tracking details belong under runtime data.

## Future Layers

The next organization-chat layers build on this router:

- Department chat binding connects organization nodes to default group threads
  and enforces single-worker department fallbacks.
- Runtime adapters receive and emit normalized messages through the router
  instead of contacting users or workers directly.

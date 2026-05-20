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

## Summaries

Use `summarize_chat_thread` and `summarize_message` for prompt context, audit,
and UI list output. Summaries include ids, participant counts, worker counts,
message type, delivery status, visibility, preview text, audit summary, and
sensitivity flags.

Summaries intentionally exclude full transcripts, private worker memory,
department memory, tool credentials, environment variables, raw external agent
stdout/stderr, and runtime task state.

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

## Future Layers

The next organization-chat layers build on this router:

- `@` and broadcast handling add recipient expansion, handled outcomes, and
  timeout tracking.
- Department chat binding connects organization nodes to default group threads
  and enforces single-worker department fallbacks.
- Runtime adapters receive and emit normalized messages through the router
  instead of contacting users or workers directly.

# Worker Agent Storage Boundaries

Managed worker agents use two storage roots with different lifetimes.

Durable worker assets live under the active profile home:

```text
<zermes_home>/worker_agents/
  registry.json
  shared/
  organization/
    active.json
    proposals/
    history/
  workers/
  threads/
  manifests/
```

This area is for worker identity, durable memory, skill bindings, policy or
strategy records, manifests, and the minimal summaries or decisions that must
survive cleanup.

Clearable runtime data lives under the installation data directory:

```text
<install_dir>/data/worker_agents/
  organization/
  tasks/
  cache/
  logs/
```

Task directories hold runtime state, events, messages, requests, transcripts,
stdout or stderr captures, rolling summaries, results, and temporary artifacts.
Deleting `data/` must not delete worker identity, memory, skill bindings, or
manifests.

Durable organization records live in profile home. Runtime organization
analysis caches, temporary project rooms, proposal runs, and detailed chat
transcripts belong under installation `data/` and may be cleaned or rebuilt.

Use `worker_agents.storage` instead of manually joining these paths. The store
objects create only the directory skeleton. Durable profile schema, registry
lifecycle, and task runtime schema are documented separately.

Worker profile contracts are documented in `docs/worker-agent-profiles.md`.
Worker registry lifecycle records are documented in
`docs/worker-agent-registry.md`.
Worker task state is documented in `docs/worker-agent-tasks.md`.
Worker retention and cleanup are documented in
`docs/worker-agent-retention.md`.
Worker organization contracts and durable organization storage are documented in
`docs/worker-agent-organization.md`.

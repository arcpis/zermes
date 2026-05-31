# Worker Agent Runtime Boundary

Managed worker execution starts with a shared runtime boundary. The boundary
keeps the main agent, durable worker agents, and task-scoped child agents on one
runtime shape while making their differences explicit in validated config.

The implementation lives in:

- `worker_agents.runtime_boundary`
- `worker_agents.runtime_facade`

It prepares runtime input only. It does not call models, execute tools, spawn
processes, write long-term memory, route chat messages, or finalize task state.

## Roles

`AgentRuntimePersona` describes the identity overlay for one runtime session.

- `main_agent`: governed user entry point. It can carry governance flags but
  must not bind worker private memory or task parent identity.
- `managed_worker`: durable WorkerAgent task identity. It must bind a valid
  `worker_id` and cannot enable main-agent governance actions.
- `temporary_child`: short-lived child task created under a parent worker and
  task. It must bind parent ids and cannot bind a durable `worker_id`, private
  memory access, governance actions, or durable registry capabilities.

These roles are runtime configuration boundaries, not separate agent loops.
The shared runtime entrypoint must continue to reuse the existing agent loop,
tool dispatch, context compression, prompt caching, and message handling paths.

## Session Config

`AgentRuntimeSessionConfig` groups the inputs allowed to reach a shared runtime
invocation:

- `RuntimeProfileSummary`: low-sensitivity profile references and summary refs.
- `RuntimePermissionSnapshot`: concrete tool, toolset, workspace, and outbound
  communication permissions for this session.
- `RuntimeBudgetSnapshot`: model, token, cost, and wall-time ceilings.
- `RuntimeContextBundle`: task instruction, compact task summary, summary refs,
  and selected excerpts.

The session config rejects broad or sensitive inputs such as wildcard tool
grants, full transcripts, raw private memory text, and temporary child sessions
that try to attach a durable profile.

Budgets are immutable snapshots. A runtime session may receive less than the
worker or parent policy allows, but it must not expand beyond the inherited
ceiling.

## Facade

`SharedAgentRuntimeFacade` exposes the common preparation entrypoint:

```python
invocation = SharedAgentRuntimeFacade().prepare_invocation(session_config)
```

The returned `AgentRuntimeInvocation` has the same shape for all runtime roles.
It is safe to inspect in tests and future adapter code because it contains only
validated runtime input, not live process handles, credentials, raw transcripts,
or long-term memory content.

`run()` currently delegates to `prepare_invocation()`. The later runtime
contract layer should own execution states, events, result records, and adapter
errors.

## Boundaries

This layer intentionally does not:

- create or update WorkerTask state;
- register or create durable WorkerAgents;
- execute tools or model calls;
- spawn external agents;
- bypass the Message Router;
- copy private memory or complete chat transcripts into runtime input;
- write memory proposals, artifact manifests, or audit summaries.

Runtime result routing, resource accounting, external adapter process control,
and temporary child cleanup are separate layers built on top of this boundary.

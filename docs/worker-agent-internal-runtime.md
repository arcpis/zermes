# Worker Agent Internal Runtime

Internal worker runtime code connects durable WorkerAgent records and clearable
WorkerTask state to the shared runtime facade. It is the native Zermes worker
adapter path; it does not create workers, spawn external agents, or route final
messages to chat threads.

The implementation lives in:

- `worker_agents.internal_runtime_context`
- `worker_agents.internal_runtime_runner`
- `worker_agents.internal_runtime_task_integration`

## Context Builder

`build_internal_worker_runtime_context()` reads one enabled worker, its durable
profile, and one task assigned to that worker. The output is split into the two
runtime boundary shapes that already exist:

- `RuntimeRequestContext` for the adapter contract.
- `RuntimeContextBundle`, `RuntimeProfileSummary`,
  `RuntimePermissionSnapshot`, and `RuntimeBudgetSnapshot` for the shared
  runtime facade.

The builder only carries task input, summaries, references, tool descriptions,
workspace policy references, and budget limits. It does not include complete
transcripts, raw private memory, unrelated workers, environment variables, or
credentials.

## Runner

`InternalWorkerRuntimeRunner` prepares a `RuntimeRequest` with
`runtime_type=internal_worker`, creates an `AgentRuntimeSessionConfig`, and
passes that config to `SharedAgentRuntimeFacade`.

The facade currently returns a prepared invocation. This keeps the internal
runner testable without network calls, model calls, tool execution, or process
management. Future live execution should replace the facade implementation
without widening the runner's authority.

## Task State Integration

Runtime state is reflected back into the task service through
`worker_agents.internal_runtime_task_integration`.

- `mark_internal_runtime_started()` moves a queued task to running and records
  the runtime request id.
- `record_internal_runtime_event()` appends low-sensitive runtime events to the
  task event JSONL and updates the rolling summary for user-relevant events.
- `finalize_internal_runtime_result()` saves a compact task result and maps
  runtime terminal states to WorkerTask terminal states.

Cancellation follows the existing task lifecycle by recording a cancelling
state before the final cancelled state. Timeout maps to expired task state.
Failed runtime results map to failed task state.

## Boundaries

This internal runtime layer intentionally does not:

- bypass WorkerTask lifecycle validation;
- write durable worker memory or department assets;
- save full transcripts into long-term assets;
- call external Agent adapters;
- create temporary child agents;
- send final messages through the Message Router.

Downstream result routing owns chat delivery, approval cards, manifest
promotion, memory proposals, and department asset proposals.

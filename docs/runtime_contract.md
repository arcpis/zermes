# Runtime Adapter Contract

The runtime adapter contract is the stable JSON boundary between managed worker
task state and any adapter that can execute a task. It is intentionally narrower
than the shared agent runtime session config: session config prepares identity,
permissions, context, and budget for a role, while this contract records what an
adapter receives, emits, and returns.

## Request

`RuntimeRequest` is the only input an adapter should need to start work. It
contains:

- `contract_version`, `request_id`, `task_id`, `worker_id`, and `runtime_type`
- `RuntimeRequestContext`, which carries the input message plus summary and
  manifest references
- `RuntimeExecutionBudget`, which carries policy-derived execution limits
- optional session and parent request references for temporary adapters

Request context must stay small and low-sensitive. It may include summaries,
references, allowed tool descriptions, workspace policy references, and short
redacted excerpts. It must not include complete transcripts, private memory text,
credentials, raw adapter output, or environment data.

## State And Events

`RuntimeState` describes one adapter invocation, not the durable WorkerTask
lifecycle. Runtime states are:

`queued`, `starting`, `running`, `cancelling`, `succeeded`, `failed`,
`timed_out`, and `cancelled`.

Use `validate_runtime_state_transition()` before recording a state move. Events
are emitted as `RuntimeEvent` records. Event payloads should contain low-sensitive
summaries, references, or counters only. Raw stdout, stderr, transcripts, tool
credentials, and private memory are rejected by the contract.

## Result And Errors

`RuntimeResult` is terminal. It can contain:

- a user-facing public message that still must be routed through Message Router
- an internal summary
- artifact manifest references
- memory or department asset proposals
- safety requests
- an audit summary
- a structured `RuntimeErrorInfo`

Runtime results do not write long-term memory, department assets, artifacts, or
messages directly. They only return references and proposals for later routing
and review.

`RuntimeErrorInfo` separates retryable, non-retryable, permission, budget,
adapter health, output parsing, cancellation, and timeout failures. Inline raw
errors are not allowed; use `raw_error_ref` to point at middle-data logs.

## Adapter Checklist

1. Accept a validated `RuntimeRequest`.
2. Emit ordered `RuntimeEvent` records with safe payloads.
3. Return one terminal `RuntimeResult`.
4. Keep full transcripts and raw adapter logs in clearable runtime data.
5. Never write durable assets or bypass Message Router from inside the adapter.

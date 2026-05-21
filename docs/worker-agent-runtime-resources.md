# Worker Agent Runtime Resource Controls

Runtime resource controls are the outer safety layer for managed worker
execution. Internal worker runtime, external adapters, and temporary subagents
should consume already-resolved controls instead of inventing local limits inside
each adapter.

## Budget Snapshot

`RuntimeBudgetPolicy` represents one narrowing layer, such as worker profile,
organization policy, task request, parent runtime, adapter definition, or system
defaults. `resolve_runtime_budget()` applies the strictest effective value from
all layers and returns an immutable `RuntimeBudgetSnapshot`.

Adapters should treat this snapshot as read-only. A child or adapter-specific
policy may only reduce limits; it must not increase token, cost, wall-time,
output, transcript, retry, or child-concurrency limits.

`RuntimeResourceUsage` records counters only. Use
`runtime_resource_usage_to_audit_summary()` for task events and audit records; it
does not carry prompts, transcript text, private memory, credentials, stdout, or
stderr.

## Cancellation And Timeout

`RuntimeCancellationToken` records the first cancellation request and preserves
later requests as audit notes. Cancellation reasons distinguish user requested,
parent runtime requested, timeout, budget exhausted, system shutdown, and safety
stop.

`RuntimeDeadline` uses an injected monotonic clock so timeout behavior is
testable without sleeping. `RuntimeControlScope` groups budget, usage, optional
deadline, and cancellation token. Callers can check deadline and budget before
or between adapter operations, then convert the cancellation into a
low-sensitive runtime error or terminal event with `runtime_cancellation_error()`
and `runtime_cancellation_event()`.

## Concurrency Gate

`RuntimeConcurrencyGate` is an in-process gate for early enforcement. It is not
a distributed scheduler or durable lock. It acquires a `RuntimeConcurrencyLease`
for the active buckets on a `RuntimeConcurrencyRequest` and must be released on
success, failure, timeout, or cancellation.

Supported dimensions are user, organization node, worker, adapter, runtime type,
and parent runtime session. The parent runtime session dimension is the boundary
used to limit active temporary child agents.

## Transcript Boundary

`RuntimeTranscriptSink` writes runtime transcript text only under
`WorkerAgentRuntimeDataStore` task storage. It returns `RuntimeTranscriptRef`
records for raw logs, tool logs, external output, and compact summaries.

Raw runtime transcript remains clearable middle data. Long-term assets and result
routing should consume refs and `RuntimeTranscriptAuditSummary`, not full text.
The sink rejects durable-looking file names and sensitive labels such as private
memory, raw stdout/stderr, credentials, API keys, and full transcript markers.

This boundary is deliberately simple. It is a hard storage and label guard, not a
complete semantic DLP engine.

## Adapter Checklist

1. Resolve an effective budget before starting runtime work.
2. Acquire any needed concurrency lease before starting a runner or backend.
3. Check deadline, cancellation, and budget at controlled points.
4. Store raw transcript and external output through `RuntimeTranscriptSink`.
5. Release concurrency leases on every terminal path.
6. Route only low-sensitive events, summaries, refs, and counters onward.

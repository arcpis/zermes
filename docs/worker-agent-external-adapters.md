# Worker Agent External Adapters

External adapters let managed WorkerAgents use non-native execution backends such
as coding agents, document tools, research services, and media generators. They
are runtime adapters, not direct access paths to the user, other workers, or
long-term assets.

The implementation lives in:

- `worker_agents.external_adapters`
- `worker_agents.external_adapter_runner`
- `worker_agents.external_adapter_output`

## Adapter Contract

`ExternalAdapterDefinition` declares what an adapter can do before it is ever
started:

- stable adapter id, provider, display name, and capability family
- supported low-sensitive input and normalized output types
- health check declaration
- security level and permission requirements
- transcript policy

The registry is intentionally small and in-memory for this phase. It supports
registration, lookup, listing, and capability filtering. It does not load
arbitrary plugins, store credentials, or execute commands.

`validate_external_adapter_request()` checks that a `RuntimeRequest` uses
`runtime_type=external_adapter`, carries only the existing runtime contract
fields, and does not request permissions the adapter did not declare.

## Runner

`ExternalAdapterRunner` turns a validated request into an
`ExternalAdapterInputBundle` and passes it to an injected backend. The backend
interface is deliberately narrow:

- `health_check()`
- `start()`
- `cancel()`
- `poll()`

The runner does not accept a command string and does not act as a general shell
runner. Concrete CLI or service adapters should implement the backend protocol
behind this facade and keep process or network details local to that adapter.

Input bundles contain task summaries, summary references, manifest references,
workspace policy references, permission instructions, and redaction policy
references. Full transcripts, private memory text, environment variables,
stdout, stderr, and credentials must stay out of the bundle.

## Output Normalization

`normalize_external_adapter_output()` converts backend output into a terminal
`RuntimeResult`. Raw adapter output is represented by middle-data references,
while result payloads contain only public messages, internal summaries, artifact
manifest refs, proposal candidates, safety requests, and low-sensitive audit
summaries.

Use `failed_external_adapter_parse_result()` when parsing fails after a backend
has produced output. The failed result uses `RuntimeErrorCode.OUTPUT_PARSE_ERROR`
and points at the middle-data raw output reference instead of embedding raw
content.

## Storage Boundary

External adapter stdout, stderr, transcripts, logs, and raw outputs belong in the
clearable install-data tree under `data/worker_agents/`. Long-term assets receive
only retained manifest refs, review candidates, and low-sensitive summaries
through later result routing.

This phase does not promote artifacts, write worker memory, update department
assets, send chat messages, or perform resource accounting. Those remain owned
by retention, result routing, and resource-control layers.

## Checklist For A Real Adapter

1. Define an `ExternalAdapterDefinition` with narrow capabilities and explicit
   permissions.
2. Implement the backend protocol without exposing arbitrary command execution.
3. Build input bundles only from summaries, refs, and approved instructions.
4. Store raw logs and transcripts as middle-data refs.
5. Normalize every terminal outcome into `RuntimeResult`.
6. Let result routing handle chat delivery, approvals, memory proposals, and
   manifest promotion.

# Worker Agent Department Context Injection

Department context injection is the final summary-only boundary between accepted department assets and a managed worker runtime session.

## Code Path

- `worker_agents.department_context_bundle` defines the bundle contract and rejects raw sensitive field names.
- `worker_agents.department_context_selection` ranks safe candidate summaries by department, task type, worker role, explicit refs, freshness, accepted state, and sensitivity.
- `worker_agents.department_context_builder` applies hard item, summary, inheritance, asset kind, and sensitivity limits before constructing a bundle.
- `worker_agents.department_context_rendering` renders a validated bundle into short runtime sections.
- `AgentRuntimeSessionConfig.department_context` is optional. Existing runtime sessions are unchanged when it is omitted.

## Bundle Contract

`DepartmentAssetContextBundle` contains only selected memory summaries, skill guidance summaries, a tool policy summary, source refs, selection reasons, excluded summaries, sensitivity summary, limit summary, audit summary, and creation time. Every persisted or audited bundle payload carries `schema_version`.

Memory views must come from accepted department memory summaries. Skill guidance views must come from accepted, guardrail-safe guidance summaries. Tool policy views carry allowed, denied, approval-required, denial reason, approval status ref, and policy ref summaries only.

## Selection Input And Output

Selection receives prebuilt `DepartmentContextCandidate` objects. It does not read department memory stores, skill binding stores, tool policy stores, transcripts, adapter output, or Hermes home paths.

Selection rejects unaccepted proposals, missing source refs, sensitivity above the ceiling, stale candidates, unsupported asset kinds, out-of-scope departments, and candidates unrelated to the task or worker. Explicit thread or organization refs can improve priority, but they cannot override sensitivity or accepted-state checks.

## Builder Limits

`DepartmentContextInjectionLimits` controls memory count, skill count, total count, per-item summary length, total summary length, inheritance depth, sensitivity ceiling, and allowed asset kinds. The builder repeats accepted-state, sensitivity, source ref, and inheritance checks even when selection already ran.

Truncated or rejected items are recorded as `DepartmentContextExcludedAsset` summaries. Raw content is never copied into excluded summaries.

## Runtime Boundary

`render_department_context_bundle` validates the bundle before producing a `RenderedDepartmentContext`. The rendered block uses stable sections for department memory notes, department skill guidance, effective tool policy summary, excluded or approval notes, and selection reasons.

External agent adapters may receive only the rendered summary and references. They must not receive raw skill instructions, complete department memories, full transcripts, credentials, local sensitive path contents, raw stdout or stderr, or external raw output.

## Default Behavior

Runtime/session config callers that do not provide `department_context` keep their previous behavior. The optional field accepts only `RenderedDepartmentContext`, not arbitrary strings or raw dictionaries.

## Prohibited Inputs

Context injection must not read or inject:

- Full transcripts or raw transcript fragments.
- Employee private memory text or private skill experience text.
- Unaccepted proposal bodies.
- Secrets, credentials, tokens, cookies, environment dumps, or raw adapter output.
- Complete active department records when a redacted or guardrail-safe view is available.
- Tool call history or executable authorization beyond the effective worker policy summary.

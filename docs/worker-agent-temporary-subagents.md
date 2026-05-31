# Temporary Subagents

Temporary subagents are task-scoped runtime sessions created by a managed
WorkerAgent. They are useful for clean-context exploration, narrow parallel
analysis, external adapter wrapping, and delegate-task style execution.

They are not durable WorkerAgents. A temporary subagent must not create a
worker registry entry, durable profile, private memory store, department
membership, or default chat thread.

## Runtime Boundary

`TemporarySubagentRequest` records the parent worker, parent task, purpose,
requested runtime type, short-lived profile overlay, requested tools,
workspace roots, budget, timeout, and result return policy.

The profile overlay is intentionally smaller than a WorkerAgent profile. It can
name a temporary role, task instructions, output contract, tool guidance, and
context limits. It rejects durable identity, private memory, department,
registry, chat, transcript, credential, and persistent skill binding fields.

Runtime requests generated from a temporary subagent request use the parent
worker id for audit ownership and keep `parent_request_id` populated so the run
cannot be confused with a standalone worker task.

## Delegation Policy

`evaluate_temporary_subagent_policy` compares the request with the parent
WorkerAgent profile and returns a decision:

- delegation must be enabled on the parent profile.
- requested tools must be a subset of the parent tools and child-tool policy.
- requested model must be allowed by the parent and child-model policy.
- read and write roots must stay inside the parent workspace policy.
- token, cost, timeout, and active-child count must stay within parent limits.

Allowed decisions produce a `TemporarySubagentEffectivePolicy`. The runner must
use this snapshot directly instead of re-inferring permissions from the parent
profile.

## Runner Behavior

`TemporarySubagentRunner` supports three managed execution paths:

- shared runtime facade for native temporary sessions.
- external adapter runner for managed external tools.
- delegate-task adapter protocol for existing delegate-task style execution.

The runner writes only task-scoped audit records under
`data/worker_agents/tasks/<task_id>/temporary-subagents/<delegation_id>/`.
Results are returned as `TemporarySubagentResultEnvelope` objects to the parent
WorkerAgent. Final user-visible routing remains a later result-routing concern.

## Non-Goals

- no durable WorkerAgent creation.
- no organization structure changes.
- no automatic writes to worker memory or department assets.
- no direct messages to users or other workers.
- no full transcript, private memory text, credentials, or raw external output
  in the request or result boundary.

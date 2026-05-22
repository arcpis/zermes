# Worker Agent Department Tool Policies

Department tool policies are durable department guidance for tool availability,
workspace scope, budget hints, and approval requirements. They are not tool
execution, worker profile mutation, global toolset changes, or approval UI.

## Storage

Department tool policy assets live under the profile-safe worker agent home:

```text
worker_agents/organization/departments/<department_id>/policies/tools/
```

The current implementation defines the contract and pure resolution helpers. A
future store can use `proposals/`, `active/`, and `history/` below that path,
matching the department memory and skill stores.

## Contract

`DepartmentToolPolicyRecord` expresses approved or active policy data:

- tool references.
- allow, deny, requires approval, or requires user confirmation.
- risk level.
- inheritance visibility.
- workspace read/write templates.
- token and cost budget hints.
- approval requirement.
- source references and audit summary.

`DepartmentToolPolicyProposal` is separate from active policy. Pending proposals
are not consumed by policy resolution.

`DepartmentToolPolicySnapshot` is the runtime-facing safe view. It contains only
allowed, denied, approval-required, and user-confirmation-required tools,
workspace summaries, budget hints, policy refs, denial reasons, and audit
summary. It does not contain credentials, tokens, cookies, raw transcripts,
environment variables, or external adapter raw output.

## Inheritance

Policy resolution is conservative:

- `deny` wins over `allow`.
- disabled active policies resolve as deny.
- child departments can tighten inherited policy directly.
- child departments cannot relax inherited policy without an approved relaxation
  reference.
- workspace expansion, budget increases, risk lowering, and approval removal are
  treated as relaxations.

`resolve_department_tool_policies` is a pure helper. It does not read stores,
call tools, update worker profiles, or create approval requests.

## Worker Profile Cross-Check

Department policy never grants a worker permissions that are absent from the
worker profile. `cross_check_department_tool_policy_with_worker` intersects a
resolved department policy with `WorkerToolPermissionSnapshot`:

- department allow plus worker allow becomes effective allow.
- worker approval-required tools remain approval-required.
- any department or worker deny stays denied.
- workspace roots are limited to the worker profile roots.
- budget hints are clipped to worker profile limits.
- external runtimes are marked summary-only.

The result is `WorkerEffectiveToolPolicy`, which is safe for later context
builders and audit views.

## Approval Requests

`build_tool_approval_requests` turns effective policy items into structured
approval requests for high-risk cases such as write access, network access,
external execution, sensitive path access, budget increase, policy relaxation,
and external runtime access.

Approval requests do not approve anything by themselves and do not execute tools.
`approved_tool_policy_refs_from_decisions` only returns refs for matching,
approved decisions with the same profile snapshot hash.

## Boundaries

This module deliberately avoids broad integration:

- no tool calls.
- no changes to `tools/registry.py` or tool dispatch.
- no runtime session mutation.
- no worker profile writes.
- no storage implementation beyond the path helper.
- no approval UI.

Later context injection should consume `WorkerEffectiveToolPolicy` and approval
summaries only. It should not read raw policy proposals or use department policy
to bypass worker profile permissions.

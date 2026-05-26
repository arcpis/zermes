# Worker Agent Organization Contract

The organization contract describes departments, teams, leaders, and individual
worker positions above the worker registry. It is implemented in
`worker_agents.organization`.

The organization layer references workers by `worker_id`. It does not own,
copy, create, delete, or mutate worker profiles, private memory, skill bindings,
tool policies, budgets, task state, runtime adapter state, or raw transcripts.

## Nodes

`OrgNode` supports four node types:

- `root`: the top-level organization node, normally led by the Zermes main agent.
- `department`: a durable business or capability group.
- `team`: a narrower sub-group inside a department.
- `individual`: a position bound to one existing WorkerAgent.

Leaders are represented by `OrgLeaderRef`:

- `main_agent`
- `worker`
- `none`

Worker leaders and members store only worker ids. A caller can validate those ids
against the registry with `validate_org_tree_references`.

## Trees

`OrgTree` stores a validated tree snapshot:

- one root node
- a root node id
- node records keyed by node id
- a revision for later store-level concurrency checks

Tree validation rejects missing parents, mismatched parent/child links,
unreachable nodes, cycles, duplicate sibling names, and archived nodes configured
as default chat targets.

## Reference Validation

`validate_org_tree_references(tree, worker_lookup)` accepts a read-only lookup:

- a set of worker ids
- a mapping from worker id to status, registry record, or status-like dict
- a callable that returns one of those values

The organization contract does not open registry files itself. Archived and
deleted workers are rejected as unavailable organization references.

## Low-Sensitivity Summaries

Use `summarize_org_node` and `summarize_org_tree` for chat context, audit
records, and UI lists. Summaries include ids, names, node type, lifecycle,
parent id, child count, member count, leader reference, responsibility summary,
task type hints, and aggregate counts.

Summaries intentionally exclude full worker profiles, private memory, skill
binding details, tool credentials, raw transcripts, runtime environment, and
task-local state.

## Example

```python
from worker_agents.organization import (
    OrgLeaderKind,
    OrgLeaderRef,
    OrgLifecycleState,
    OrgNode,
    OrgNodeType,
    OrgTree,
    summarize_org_tree,
)

root = OrgNode(
    org_node_id="root",
    name="Zermes",
    node_type=OrgNodeType.ROOT,
    child_ids=("engineering",),
    leader=OrgLeaderRef(kind=OrgLeaderKind.MAIN_AGENT),
    lifecycle=OrgLifecycleState.ACTIVE,
)
engineering = OrgNode(
    org_node_id="engineering",
    name="Engineering",
    node_type=OrgNodeType.DEPARTMENT,
    parent_id="root",
    member_worker_ids=("engineering_lead",),
    lifecycle=OrgLifecycleState.ACTIVE,
)
tree = OrgTree(
    tree_id="default",
    root_node_id="root",
    nodes={"root": root, "engineering": engineering},
)
summary = summarize_org_tree(tree)
```

Long-term storage, proposal history, message routing, department chat binding,
department memory, and department skill or tool policy are implemented by later
worker-agent layers.

Department chat binding is implemented in `worker_agents.department_chats` and
documented in `docs/worker-agent-department-chats.md`. It binds active
department or team nodes to user-present group threads without copying worker
profiles or private memory.

## Durable Store

`OrganizationStore` in `worker_agents.storage.organization_store` persists
organization records under profile home:

```text
<zermes_home>/worker_agents/organization/
  active.json
  proposals/
    <proposal_id>.json
  history/
    <change_id>.json
```

`load_active_organization()` returns `None` when `active.json` has not been
created. `save_active_organization(tree, expected_revision=...)` validates the
tree through the organization contract, checks the expected revision when one is
provided, and writes with atomic JSON replacement. A revision conflict or
invalid tree leaves the previous active file intact.

Proposal summaries are stored with `save_proposal_summary()` and loaded with
`load_proposal_summary()` or `list_proposal_summaries()`. A proposal summary is
only a low-sensitivity record of a suggested organization change: id, creation
time, submitter, optional target node, status, and short summary. Saving a
proposal does not update `active.json` and does not execute the proposal.

History summaries are stored with `save_history_summary()` and loaded with
`load_history_summary()` or `list_history_summaries()`. They capture audit
summaries for accepted organization changes, including affected node ids and
previous/new revisions when known.

The durable organization store intentionally excludes full worker profiles,
private memory, skill bindings, tool credentials, raw chat transcripts,
department assets, runtime task state, and proposal execution state. Runtime
organization caches and detailed transcripts belong under
`<install_dir>/data/worker_agents/organization/`.

## Evolution Proposals

Long-term organization changes use the proposal-first contract in
`worker_agents.organization_evolution`. The supported proposal types are:

- `create_child_agent`
- `delete_child_agent`
- `merge_department`
- `transfer_assets`
- `archive_org_node`

Each `OrganizationEvolutionProposal` records the initiator, target nodes,
affected workers, reason, before/after summaries, rollback summary reference,
asset and chat disposition references, risk flags, approval policy, and audit
source references. The schema rejects path-like ids and sensitive raw fields
such as transcripts, stdout/stderr, credentials, secrets, and private memory
text. Runtime results, management commands, and agents may submit proposals,
but proposal generation must not write `active.json`, mutate the WorkerAgent
registry, or update department assets.

Risk policy helpers classify permission expansion, budget or model-tier
increase, external Agent involvement, sensitive memory movement, active tasks,
pending high-risk approvals, group-chat closure, and responsibility changes.
Permission expansion, budget/model increases, external Agent changes, and
sensitive memory movement require user approval. Active tasks and unfinished
high-risk approvals are blockers and must be resolved before execution.

`EvolutionProposalStore` in
`worker_agents.storage.organization_evolution_store` persists full proposal
records under:

```text
<zermes_home>/worker_agents/organization/proposals/
  <proposal_id>.json
```

The store supports create, read, list filtering, and explicit status
transitions with actor, timestamp, previous status, next status, and reason.
Rejected, expired, executed, and failed proposals are terminal. The store only
manages proposal files; accepted or approved proposals still require a later
controlled executor before any active organization tree, registry lifecycle, or
department asset write occurs.

## Evolution Execution

Approved organization changes are executed through
`worker_agents.organization_evolution_executor`. This executor is the controlled
write boundary for active organization tree updates, WorkerAgent registry
lifecycle changes, chat binding status markers, asset disposition markers, and
execution audit records. It is not a generic organization tree patch runner.

`begin_evolution_execution()` only starts an execution for an approved proposal
with no blocking flags and a non-expired plan. The execution state records the
proposal id, actor, locked organization node ids, locked worker ids, completed
steps, failed step, failure reason, and manual recovery hint. Locks are stored
under profile-home organization storage, so tests and profiles use the same
profile-safe path rules as the rest of worker-agent durable storage.

`apply_approved_evolution_plan()` accepts a `ControlledEvolutionPlan`, not an
arbitrary patch. The plan must stay inside the proposal's target nodes and
affected workers. Before writing, the executor reloads the active organization
tree and registry and checks the expected tree revision. It then records each
completed step after registry precheck, registry lifecycle update, organization
tree update, chat binding update, and asset disposition update. Revision
mismatches or out-of-scope writes stop execution and leave a recoverable failed
state with the last completed step.

`finalize_evolution_execution()` writes an `EvolutionExecutionAuditRecord`
before marking a successful execution completed. If audit persistence fails,
the execution is not marked completed. Failed executions can also produce a
failed audit record with the completed steps, failed step, failure reason, and
manual recovery hint. The audit record stores only summaries and references:
proposal id, execution id, initiator, approvers, affected nodes and workers,
before/after summaries, disposition report refs, chat refs, asset refs, rollback
summary ref, and terminal status. Raw transcripts, credentials, stdout/stderr,
secrets, and private memory text are rejected.

Execution records are stored under:

```text
<zermes_home>/worker_agents/organization/
  executions/
    <execution_id>.json
  execution-locks.json
  chat-binding-status.json
  asset-disposition-markers.json
  history/
    evolution-executions/
      <change_id>.json
```

Failures are intentionally not rolled back automatically. Operators should use
the failed execution state and final audit record to inspect completed steps,
active organization state, registry lifecycle state, chat status markers, and
asset disposition markers before deciding whether to repair, retry, or supersede
the proposal.

## Department Merge Planning

Department merges are planned by `DepartmentMergeRequest`,
`DepartmentMergePlan`, and `build_department_merge_preflight()` in
`worker_agents.organization_evolution`. The planner accepts compact department
summaries, lifecycle states, task or approval summaries, runtime session
summaries, policy summaries, and asset disposition references. It does not read
full transcripts, private memories, raw policy files, or runtime state directly.

The merge request contract supports one or more source departments and exactly
one target department. The target cannot also be a source, source departments
must be unique, and each source must have a matching low-sensitivity department
summary. The plan records references to the task transfer plan, chat freeze
plan, memory merge report, skill disposition plan, tool disposition plan,
rollback plan, and optional proposal. These are references only; the planner
does not transfer tasks, adopt memory, change skill or tool policy bindings, or
mutate `active.json`.

Preflight blocks approval when source departments still have active high-risk
tasks, pending approvals, running runtime sessions, invalid lifecycle state, or
missing asset disposition references. Responsibility overlap, owner mismatch,
budget or model policy differences, tool policy differences, and department
playbook differences are recorded as conflicts with manual decision summaries.
Conflicts require review but do not themselves execute any resolution.

Memory merge planning is represented by `MemoryMergeReport` in
`worker_agents.organization_memory_merge`. The report records low-sensitive
summaries, source references, candidate counts, adopted items, rejected items,
archived items, duplicate groups, conflicts, redaction items, manual decisions,
approval status, reviewer, and the proposal asset disposition plan reference.
It is an audit contract only: it does not copy a source department's complete
raw memory store into the target department and it does not write active
department memory. Source private memory is not read by this flow. Private
memory-derived assets default to archive unless a separate low-sensitive,
redacted proposal summary is explicitly reviewed for adoption. Pending
conflicts, redactions, or manual decisions keep executor-facing adopted refs
empty until review resolves them.

Skill and tool disposition planning is represented by
`worker_agents.organization_asset_disposition`. These plans classify source
department skill bindings, private skill experience, and tool policy records
before merge execution. They do not install skills, copy active bindings, grant
tools, expand workspace permissions, raise budgets, change worker profiles, or
approve external adapter access. Missing skill dependencies, unavailable tools,
profile denials, parent policy denials, governance denials, and high-risk
approval gaps stay blocked or review-only. Only reviewed candidate refs can be
passed forward to the normal department skill or tool proposal flow.

Before a merge can be handed to a future executor, the approved plan must be
paired with a `DepartmentChatFreezePlan` and an `EvolutionRollbackPlan`.
The freeze plan closes source department chats to new tasks and records final
summary, archive manifest, and audit references; it does not close chat threads.
The rollback plan preserves original parent/child references, chat binding
references, original asset adoption status, and a task transfer snapshot
reference. Actual execution still depends on dedicated memory merge,
skill/tool disposition, chat, and organization executor components.

## Child Agent Lifecycle Plans

Durable child agents are organization members. Creating an internal WorkerAgent,
an external Agent, or an organization-only team node must start as a
`ChildAgentCreatePlan` attached to an evolution proposal. The plan records the
target parent node, responsibility boundary, permission ceiling, budget limit,
model policy, profile template or profile reference, and chat policy. It does
not create a registry record, start runtime, provision an adapter, write
`active.json`, or bind a group chat.

Temporary subagents are task-local delegations. They do not enter the active
organization tree, do not receive durable WorkerAgent registry lifecycle state,
and must not be referenced by durable child-agent plan ids, worker ids, node ids,
or profile refs.

Deleting a durable child agent uses `ChildAgentDeletePlan`. The plan may record
active tasks, unfinished approvals, downstream child nodes, running sessions,
and missing asset or chat disposition references. These are preflight blockers:
they keep the plan from entering approval or execution, but they remain
representable so review can show the full cleanup work. Private assets default
to archive disposition unless a separate transfer proposal is supplied.

After a deletion plan changes the shape of a department, use
`DepartmentContractionPlan` to describe the resulting collaboration surface.
Departments with multiple remaining workers can keep a department group chat.
Single-worker departments keep the node with direct worker chat, or explicitly
rebind collaboration to the parent group chat. Empty departments with no
remaining responsibilities require asset and chat disposition refs before they
can be archived or removed from the active tree.
## Management Dashboard Read Models

The management dashboard models live under `worker_agents.management`. They are
read-only projections over already-loaded worker registry, organization,
department, chat, health, and policy summaries. They do not open profile-home
files and do not mutate registry or organization stores.

The dashboard snapshot deliberately keeps low-sensitivity fields only:

- worker identity, lifecycle status, runtime type, department ids, health
  status, policy summary, and controlled links into approval or operations
  consoles;
- organization node identity, lifecycle, parent/child references, leader refs,
  member refs, collaboration mode, read-only state, and risk badges;
- department summary counts and policy summaries, with private memory,
  transcript, credential, token, secret, and raw content keys removed.

Single-worker departments do not expose an independent department group chat
entry. They are shown as `private_or_parent_chat` so any later action still
routes through the governed chat or approval flow.

## Approval Center Read Models

The approval center models in `worker_agents.management` aggregate low-sensitive
proposal summaries from organization evolution, department memory, department
skill, tool policy, budget, and external-agent requests. Queue rows carry source
refs, requester, recommended approver, deadline, impact summary, blockers,
warnings, and risk badges.

Approval action helpers validate actor eligibility, terminal states, blockers,
and explicit confirmation for high-risk approvals before callers invoke the
underlying proposal service. They produce audit records with actor, decision,
reason, timestamp, risk summary, and source refs, but they do not execute
organization changes or bypass underlying approval policy.

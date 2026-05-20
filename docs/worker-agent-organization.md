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

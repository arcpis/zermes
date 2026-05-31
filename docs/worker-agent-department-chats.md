# Worker Agent Department Chats

Department chats bind organization nodes to user-present group threads. They
are implemented in `worker_agents.department_chats`.

This layer connects the organization contract and message router. It does not
launch workers, create tasks, call runtime adapters, copy WorkerAgent profiles,
read private memory, write department assets, or grant new tool permissions.

## Bindings

`DepartmentChatBinding` stores a low-sensitivity reference from an organization
node to a chat thread:

- `department_default`: default chat for a department node.
- `team_default`: default chat for a team node.
- `project`: minimal cross-department project chat.

Every department or team chat must include the user and the Zermes main agent.
The binding records only ids: organization node id, thread id, owner worker id,
member worker ids, and parent summary targets.

`DepartmentChatBindingService.plan_default_binding()` builds a binding plan from
an active department or team node. It adds the worker leader and direct members,
checks worker lifecycle summaries, and returns an auditable plan instead of
silently rewriting thread history.

Member changes produce `DepartmentChatMemberSyncPlan` items: add, keep, remove,
or review. Closed and archived bindings require explicit review before they are
reopened.

## Single-Worker Departments

A department with fewer than two employee workers does not get its own group
chat. The user and main agent are required participants, but they do not count
as employees for this rule.

When only one worker remains, the planner returns a fallback target:

- use an existing direct thread with that worker
- use the parent group thread with summary-only context
- plan a direct thread if no existing entry is known

If an existing group chat shrinks to one worker, the sync plan asks for review:
close the group entry, preserve summaries and audit references, then migrate to
the fallback. The organization node may continue to exist.

## Hierarchical Summaries

`DepartmentChatSummary` is the only supported upward context boundary between
department chats. A child department can summarize to its parent with summary
types such as decision, deliverable, risk, handoff, periodic summary, or final
archive summary.

Parent chats receive summaries, decisions, deliverable references, and necessary
audit references. They do not receive full child transcripts. Non-parent
department summaries must be marked as project summaries.

`DepartmentProjectChat` keeps only a minimal project structure: project id,
thread id, participating organization nodes, summary targets, and deliverable
manifest references. It is a collaboration entry, not a project asset store.

## Low-Sensitivity Boundary

Department chat bindings and summaries intentionally exclude:

- full worker profiles
- private worker memory
- department memory entries
- skill bindings
- tool credentials
- environment variables
- raw transcripts
- external adapter raw output
- runtime task state

Manifest fields are references only. A manifest reference does not grant extra
read permission and does not copy the underlying artifact into the target
department.

Department chat summaries are not automatically written to worker private
memory, department memory, or global user memory. Later department asset flows
must review and accept them explicitly.

## Storage Boundary

Long-lived organization and chat summaries belong under profile home:

```text
<zermes_home>/worker_agents/organization/
<zermes_home>/worker_agents/threads/
```

Clearable runtime transcripts, detailed event logs, temporary project caches,
and sync-plan caches belong under install data:

```text
<install_dir>/data/worker_agents/organization/
<install_dir>/data/worker_agents/threads/
```

Deleting runtime `data/` must not delete the active organization tree,
department chat binding summaries, important thread summaries, retained
manifest references, or audit summaries.

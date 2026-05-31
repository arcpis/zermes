# Organization Commands Reference

This file is the single reference for the execution-oriented WorkerAgent organization skill. It covers the CLI commands, proposal kinds, approval behavior, dependency ordering, id normalization, and a complete execution example.

## Query Commands

| Command | Purpose |
| --- | --- |
| `zermes worker-agents organization --json` | Current organization tree: node ids, parent-child relationships, lifecycle state. |
| `zermes worker-agents workers --json` | Worker records: status, department, runtime, and risk badges. |
| `zermes worker-agents evolution --json` | Proposal workbench: drafts, status, blockers, and execution readiness. |
| `zermes worker-agents approvals --json` | Approval queue: approval ids, risk levels, and required action. |
| `zermes worker-agents chats --json` | Materialized chat/thread bindings for workers and departments. |
| `zermes worker-agents overview --json` | Dashboard snapshot with summaries and warnings. |

Useful worker filters:

```bash
zermes worker-agents workers --status enabled --json
zermes worker-agents workers --department engineering --json
zermes worker-agents workers --runtime internal --json
zermes worker-agents workers --risk external_unhealthy --json
```

## Proposal Types

| `--proposal-kind` | Effect | Typical approval |
| --- | --- | --- |
| `create_child_agent` | Create a worker or department node under an existing parent. | `POLICY_APPROVED` |
| `delete_child_agent` | Remove a child worker or node; destructive. | `MAIN_AGENT_APPROVAL` |
| `merge_department` | Merge a source department into a destination department. | `USER_APPROVAL` |
| `archive_node` | Archive an organization node without hard deletion. | `MAIN_AGENT_APPROVAL` |

## Draft Command

Drafting validates intent and creates the proposal/approval surface. It does not mutate the active organization.

```bash
zermes worker-agents evolution-draft \
  --proposal-kind <TYPE> \
  --actor main-agent \
  --target-node <NODE_ID> \
  --requested-worker <WORKER_ID> \
  --reason "<business justification>" \
  --json
```

Additional flags by proposal type:

- `create_child_agent`: `--requested-worker <WORKER_ID>` is required. `--target-node` is the parent node under which the worker is created.
- `delete_child_agent`: `--asset-disposition-ref <ref>` is required. `--target-node` is the parent department node. `--requested-worker <WORKER_ID>` is the child node to delete (the org node whose `org_node_id` matches the worker id). If `--requested-worker` is omitted, `--target-node` itself is deleted.
- `merge_department`: `--destination-node <id>` and `--rollback-plan-ref <ref>` are required.
- `archive_node`: `--active-task-ref <ref>` should be supplied if active tasks exist; the draft will block if any are unresolved.

Inspect the draft output before any approval or apply step:

- `blockers`
- `risk_badges`
- `approval_requirement`
- `can_execute`
- `disabled_reason`
- `source_refs`

## Apply Command

Apply executes an approved proposal and mutates managed state. All four proposal kinds are supported: `create_child_agent`, `delete_child_agent`, `merge_department`, and `archive_node`.

```bash
zermes worker-agents evolution-apply-draft \
  --proposal-kind <TYPE> \
  --actor main-agent \
  --target-node <NODE_ID> \
  --requested-worker <WORKER_ID> \
  --destination-node <DEST_ID> \
  --json
```

Use the same operation parameters as the draft. Add `--dry-run` to validate execution readiness without mutation. The `--reason` flag is optional and records the business justification in the audit log.

Kind-specific requirements:

- `create_child_agent`: `--requested-worker` is required. `--target-node` is the parent.
- `delete_child_agent`: removes the node and disables all member workers. `--target-node` is the parent department. `--requested-worker` identifies the child node to delete. If omitted, `--target-node` itself is deleted. Nodes with active children cannot be deleted.
- `merge_department`: `--destination-node` is required; children and members are merged into the destination.
- `archive_node`: sets lifecycle to `archived` and disables all member workers.

## Worker Update Command

Update a worker agent's profile (identity, skills, tools) and sync the management snapshot.

```bash
zermes worker-agents worker-update <WORKER_ID> \
  --display-name "<name>" \
  --description "<description>" \
  --role "<role>" \
  --responsibilities "<responsibilities>" \
  --allowed-tools "<tools>" \
  --approval-required-tools "<tools>" \
  --allowed-skills "<skills>" \
  --default-model "<model>" \
  --json
```

All fields are optional; only provided fields are updated. Comma-separate multiple values for `--responsibilities`, `--allowed-tools`, `--approval-required-tools`, and `--allowed-skills`. Add `--dry-run` to validate without mutation.

### Change a worker display name

Worker ids are immutable. Use `worker-update --display-name` to change the display name:

```bash
zermes worker-agents worker-update <WORKER_ID> \
  --display-name "New Display Name" \
  --json
```

## Approval Commands

Auto-approval is allowed only for `POLICY_APPROVED` and `MAIN_AGENT_APPROVAL`.

```bash
zermes worker-agents approval approve <approval_id> \
  --actor main-agent \
  --reason "Auto-approved per user request" \
  --json
```

High-risk approval requires explicit user confirmation first:

```bash
zermes worker-agents approval approve <approval_id> \
  --actor main-agent \
  --reason "<confirmed user reason>" \
  --confirm-high-risk \
  --json
```

Other review actions:

```bash
zermes worker-agents approval reject <approval_id> \
  --actor main-agent \
  --reason "<reason>" \
  --json

zermes worker-agents approval request-changes <approval_id> \
  --actor main-agent \
  --reason "<required changes>" \
  --json

zermes worker-agents approval delegate <approval_id> \
  --actor main-agent \
  --delegate-to <reviewer-id> \
  --reason "<reason>" \
  --json
```

## Approval Levels And Risk Flags

| Level | Triggers | Agent behavior |
| --- | --- | --- |
| `POLICY_APPROVED` | Low-risk create with no high-risk flags. | Auto-approve and apply. |
| `MAIN_AGENT_APPROVAL` | Group chat closure, responsibility change, delete, archive, or transfer operations. | Auto-approve and apply. |
| `USER_APPROVAL` | Permission expansion, budget increase, model tier increase, external agent, or sensitive memory. | Ask user first. |

| Risk flag | Meaning | Behavior |
| --- | --- | --- |
| `PERMISSION_EXPANSION` | New tools or permissions granted. | User approval required. |
| `BUDGET_INCREASE` | Spending limits raised. | User approval required. |
| `MODEL_TIER_INCREASE` | Higher-capability model requested. | User approval required. |
| `EXTERNAL_AGENT` | External system or runtime involved. | User approval required. |
| `SENSITIVE_MEMORY` | Sensitive memory or data migration involved. | User approval required. |
| `GROUP_CHAT_CLOSURE` | Existing chat will be closed or rerouted. | Main-agent approval. |
| `RESPONSIBILITY_CHANGE` | Role ownership or department responsibility changes. | Main-agent approval. |
| `ACTIVE_TASKS` | Ongoing work would be affected. | Blocker; resolve first. |
| `PENDING_HIGH_RISK_APPROVALS` | Related high-risk approvals are unfinished. | Blocker; resolve first. |

## Wave Ordering Rules

1. Parent before child: never create a child under a node that does not exist yet.
2. Transfer before delete: move assets out before removing or archiving a node.
3. Same-level siblings may be handled in the same wave.
4. Verify between waves with `zermes worker-agents organization --json`.

Example:

```text
User: "Create team-lead under engineering, with frontend and backend under it."

Wave 1:
  create_child_agent team-lead under engineering

Wave 2:
  create_child_agent frontend under team-lead
  create_child_agent backend under team-lead
```

## ID Normalization

- Convert display names to stable kebab-case ids: `Frontend Dev` becomes `frontend-dev`.
- Use lowercase ASCII letters, digits, and hyphens.
- Remove filler words that do not define identity, such as `worker` when the remaining role is clear.
- Do not rename an existing id just because a display name changed.

## Complete Execution Example

User request: "Create a QA worker under engineering."

```bash
zermes worker-agents organization --json

zermes worker-agents evolution-draft \
  --proposal-kind create_child_agent \
  --actor main-agent \
  --target-node engineering \
  --requested-worker qa-engineer \
  --reason "Add QA specialist to engineering team" \
  --json

zermes worker-agents approval approve <approval_id> \
  --actor main-agent \
  --reason "Auto-approved: POLICY_APPROVED and user requested creation" \
  --json

zermes worker-agents evolution-apply-draft \
  --proposal-kind create_child_agent \
  --actor main-agent \
  --target-node engineering \
  --requested-worker qa-engineer \
  --json

zermes worker-agents organization --json
zermes worker-agents workers --json
zermes worker-agents chats --json
```

Expected result: `qa-engineer` is visible under `engineering`, appears in worker listings, and any required chat bindings are materialized when the product flow supports them.

## Additional Operation Examples

### Delete a worker or department

Delete a specific child worker under a parent department:

```bash
zermes worker-agents evolution-draft \
  --proposal-kind delete_child_agent \
  --actor main-agent \
  --target-node <PARENT_NODE_ID> \
  --requested-worker <CHILD_WORKER_ID> \
  --asset-disposition-ref <REF> \
  --reason "Remove deprecated worker" \
  --json

zermes worker-agents evolution-apply-draft \
  --proposal-kind delete_child_agent \
  --actor main-agent \
  --target-node <PARENT_NODE_ID> \
  --requested-worker <CHILD_WORKER_ID> \
  --json
```

Delete a department node directly (no `--requested-worker`):

```bash
zermes worker-agents evolution-draft \
  --proposal-kind delete_child_agent \
  --actor main-agent \
  --target-node <NODE_ID> \
  --asset-disposition-ref <REF> \
  --reason "Remove deprecated department" \
  --json

zermes worker-agents evolution-apply-draft \
  --proposal-kind delete_child_agent \
  --actor main-agent \
  --target-node <NODE_ID> \
  --json
```

### Merge departments

```bash
zermes worker-agents evolution-draft \
  --proposal-kind merge_department \
  --actor main-agent \
  --target-node <SOURCE_NODE> \
  --destination-node <DEST_NODE> \
  --rollback-plan-ref <REF> \
  --reason "Consolidate into parent department" \
  --json

zermes worker-agents evolution-apply-draft \
  --proposal-kind merge_department \
  --actor main-agent \
  --target-node <SOURCE_NODE> \
  --destination-node <DEST_NODE> \
  --json
```

### Archive a node

```bash
zermes worker-agents evolution-draft \
  --proposal-kind archive_node \
  --actor main-agent \
  --target-node <NODE_ID> \
  --active-task-ref <TASK_REF> \
  --reason "Department no longer active" \
  --json

zermes worker-agents evolution-apply-draft \
  --proposal-kind archive_node \
  --actor main-agent \
  --target-node <NODE_ID> \
  --json
```

### Update a worker profile

```bash
zermes worker-agents worker-update <WORKER_ID> \
  --display-name "Senior QA Engineer" \
  --role "quality_engineer" \
  --allowed-skills "testing,code-review" \
  --json
```

Expected result: profile is updated and dashboard state is synced with new values.

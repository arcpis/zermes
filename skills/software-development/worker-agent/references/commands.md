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
| `transfer_assets` | Move assets or ownership references between nodes. | `MAIN_AGENT_APPROVAL` |
| `archive_org_node` | Archive an organization node without hard deletion. | `MAIN_AGENT_APPROVAL` |

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

- `delete_child_agent`: `--asset-disposition-ref <ref>` is required.
- `merge_department`: `--destination-node <id>` and `--rollback-plan-ref <ref>` are required.
- `transfer_assets`: `--destination-node <id>` is required.
- `archive_org_node`: no extra flag is required unless draft output asks for one.

Inspect the draft output before any approval or apply step:

- `blockers`
- `risk_badges`
- `approval_requirement`
- `can_execute`
- `disabled_reason`
- `source_refs`

## Apply Command

Apply executes an approved proposal and mutates managed state.

```bash
zermes worker-agents evolution-apply-draft \
  --proposal-kind <TYPE> \
  --actor main-agent \
  --target-node <NODE_ID> \
  --requested-worker <WORKER_ID> \
  --json
```

Use the same operation parameters as the draft. Add `--dry-run` only when validating execution readiness without mutation.

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

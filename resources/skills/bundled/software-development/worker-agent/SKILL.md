---
name: worker-agent
description: "WorkerAgent organization operations: create, delete, merge, archive workers/departments, update worker profiles, query org state. Load for any worker-agent or organization-structure task — renaming, restructuring, membership changes, status queries, or approval handling."
license: MIT
metadata:
  hermes:
    tags: [worker-agents, organization, evolution, execution]
    related_skills: [self-evolution, worker-agent-task-delegation]
---

# WorkerAgent Organization Executor

Use this skill to execute organization changes, not to hand users command templates. Run the product CLI yourself, keep every change proposal-first, and report the final verified state.

For task dispatch through existing workers, use `worker-agent-task-delegation` instead. Use this organization skill first only when a worker, department, profile, or chat binding change is required before dispatch.

## Execution Flow

1. Intent: parse `proposal_kind`, `target_node`, `worker_id`, dependencies, and reason from the user's request.
2. Query: run `zermes worker-agents organization --json` before planning so the current tree is the source of truth.
3. Plan: split multi-node changes into waves; parents are created before children, and assets move before deletion.
4. Execute: for each atomic change, run draft, inspect blockers and approval requirement, approve when allowed, then apply.
5. Verify: rerun `zermes worker-agents organization --json`; use `workers --json` or `chats --json` when membership or materialized chats matter.

## Smart Approval

| Approval level | Action |
| --- | --- |
| `POLICY_APPROVED` | Auto-approve and apply immediately; this is zero-risk by policy. |
| `MAIN_AGENT_APPROVAL` | Auto-approve and apply; the user already requested the operation. |
| `USER_APPROVAL` | Stop, explain the risk and affected nodes, then wait for explicit user confirmation. |

## Execution Rules

- Always query first; never assume root ids, existing departments, or worker ids.
- Use one draft per atomic operation. Do not combine parent and child creation in a single proposal.
- If a requested id already exists in the intended place, skip that atomic change and report it as already satisfied.
- If `blockers` is non-empty or `can_execute` is false, stop that change and report the required resolution.
- Apply only after approval is satisfied. Draft output alone never means the worker exists.
- Verify after each dependency wave before drafting children that depend on newly created parents.

## Capability Boundaries

Map user requests to these operations only. If a request has no matching operation, inform the user — do not guess or invent proposal kinds.

Task delegation is out of scope here. If the user asks to split requirements, send work to workers, wait for replies, or summarize WorkerAgent results, switch to `worker-agent-task-delegation`.

| User intent | Command | Key parameters |
| --- | --- | --- |
| Create a worker/department | `evolution-draft --proposal-kind create_child_agent` | `--target-node` = parent, `--requested-worker` = new worker id |
| Delete a worker/department | `evolution-draft --proposal-kind delete_child_agent` | `--target-node` = parent, `--requested-worker` = child to delete (omit to delete target itself), `--asset-disposition-ref` required |
| Merge two departments | `evolution-draft --proposal-kind merge_department` | `--target-node` = source, `--destination-node` = target, `--rollback-plan-ref` required |
| Archive a node | `evolution-draft --proposal-kind archive_node` | `--target-node` = node to archive |
| Change display name | `worker-update <WORKER_ID> --display-name "<name>"` | Worker id is immutable; only display name changes |

After drafting, approve and apply. See `references/commands.md` for full syntax.

## Command Reference

Read `references/commands.md` when you need syntax, proposal kinds, approval commands, risk flags, or wave examples.

Core commands:

```bash
zermes worker-agents organization --json
zermes worker-agents workers --json
zermes worker-agents evolution --json
zermes worker-agents approvals --json
zermes worker-agents chats --json

zermes worker-agents evolution-draft \
  --proposal-kind <TYPE> \
  --actor main-agent \
  --target-node <NODE_ID> \
  --requested-worker <WORKER_ID> \
  --reason "<REASON>" \
  --json

zermes worker-agents approval approve <approval_id> \
  --actor main-agent \
  --reason "Auto-approved per user request" \
  --json

zermes worker-agents evolution-apply-draft \
  --proposal-kind <TYPE> \
  --actor main-agent \
  --target-node <NODE_ID> \
  --requested-worker <WORKER_ID> \
  --json
```

## Safety

- Never bypass `USER_APPROVAL` for permission expansion, budget increase, model tier increase, external-agent access, sensitive memory, or comparable high-risk changes.
- Never edit organization, registry, thread, memory, or dashboard JSON files directly.
- Never expose secrets, credentials, private memory, raw transcripts, or unredacted stdout/stderr.
- On failures, report the exact failed phase and stop; do not repeatedly retry mutating operations.

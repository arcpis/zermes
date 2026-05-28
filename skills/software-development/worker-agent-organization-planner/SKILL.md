---
name: worker-agent-organization-planner
description: "Execute WorkerAgent organization changes end-to-end. Use when users ask to create, delete, merge, archive, or restructure workers, departments, teams, or reporting relationships; query current state, draft proposals, auto-approve safe changes, apply them, verify results, and only stop for user confirmation on high-risk operations."
license: MIT
metadata:
  hermes:
    tags: [worker-agents, organization, evolution, execution]
    related_skills: [self-evolution]
---

# WorkerAgent Organization Executor

Use this skill to execute organization changes, not to hand users command templates. Run the product CLI yourself, keep every change proposal-first, and report the final verified state.

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

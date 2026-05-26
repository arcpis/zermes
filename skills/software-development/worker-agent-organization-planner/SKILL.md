---
name: worker-agent-organization-planner
description: "Use when a user asks Zermes to create WorkerAgent employees, sub-agents, departments, teams, reporting structures, or to adjust WorkerAgent organization topology from natural language. Guides the main agent to parse staffing intent, normalize ids, split multi-node changes into proposal-first command flows, submit drafts, explain approval/execution checkpoints, and verify results without directly editing active organization or registry state."
license: MIT
metadata:
  hermes:
    tags: [worker-agents, organization, staffing, evolution, proposal, approval, cli, dashboard]
    related_skills: [self-evolution, writing-plans, test-driven-development]
---

# WorkerAgent Organization Planner

Use this skill to turn natural-language organization requests into a safe WorkerAgent evolution workflow. The main agent should guide the user and produce concrete command flows. Do not directly modify active organization trees, worker registries, department assets, tool policies, memory stores, or retention state.

## Operating Order

Do not start by reading source code. First use the product interface and documented commands:

1. Plan the requested organization change in text.
2. Inspect current product state with `zermes worker-agents ... --json` only if current state is needed.
3. Convert the plan into a command flow.
4. Run or present the draft/action commands according to the user's instruction.
5. Verify with read-only `zermes worker-agents` commands.

Read repository code only when a documented command is missing, fails unexpectedly, or the user explicitly asks to modify the implementation. For normal organization planning, the CLI/API product surface is the source of truth.

## Information Sources

Prefer these sources in order:

1. `zermes worker-agents ... --json` commands for current workers, organization, chats, proposals, approvals, assets, import/export, and retention state.
2. Dashboard API `/api/worker-agents/*` when working inside the local dashboard context.
3. Product state files only for read-only inspection or troubleshooting:
   - `<HERMES_HOME>/worker_agents/management/dashboard_state.json`
   - `<HERMES_HOME>/worker_agents/threads/<thread_id>/messages.jsonl`
4. Source code only when product commands/API are unavailable or need implementation changes.

Do not edit product state files directly. Use commands/action endpoints so validation, approvals, and audit output stay intact.

## Required Behavior

Always produce a proposal-first plan. For creation, deletion, merge, archive, or restructuring requests:

1. Restate the user intent.
2. Extract the requested organization tree.
3. Normalize display names into stable ids.
4. Identify the existing parent node where the first new node should attach.
5. Split changes into execution waves, creating parents before children.
6. Generate `zermes worker-agents evolution-draft` commands.
7. Explain approval requirements and blocker handling.
8. Provide verification commands.
9. State safety boundaries.

If the existing parent node is missing or ambiguous, ask for it before emitting final commands. You may still show a command template with `<existing-parent-node>`.

## Load References

Read only the references needed for the current request:

- `references/command-reference.md`: exact CLI commands and argument meanings.
- `references/information-sources.md`: product commands, API endpoints, state file locations, and source-code fallback locations.
- `references/natural-language-to-command-flow.md`: how to parse natural language into waves and commands.
- `references/approval-and-execution.md`: how to handle approval, blockers, execution availability, and verification.
- `references/scenarios.md`: examples for creation, deletion, merge, archive, and restructuring.

## Output Template

Use this structure:

```text
Intent summary:
[what the user asked for]

Assumptions / missing inputs:
[existing parent node, actor id, naming assumptions, unresolved questions]

Proposed organization tree:
[ASCII tree]

Normalized ids:
[display name -> id mapping]

Command flow:
Wave 1:
[commands]

Wave 2:
[commands]

Approval and execution:
[approval commands and checkpoints]

Verification:
[commands to inspect evolution, approvals, organization, chats]

Safety notes:
[what is not directly modified or exposed]
```

## Available Commands

Use `zermes`, not `hermes`, in user-facing instructions. These are the main commands this skill should know without reading code:

```bash
zermes worker-agents overview --json
zermes worker-agents workers --json
zermes worker-agents organization --json
zermes worker-agents chats --json
zermes worker-agents chat-history <thread_id> --limit 50 --json
zermes worker-agents evolution --json
zermes worker-agents evolution-draft --proposal-kind create_child_agent --actor <actor> --target-node <parent> --requested-worker <worker-id> --reason "<reason>" --json
zermes worker-agents approvals --json
zermes worker-agents approval approve <approval_id> --actor <actor> --reason "<reason>" --confirm-high-risk --json
zermes worker-agents approval reject <approval_id> --actor <actor> --reason "<reason>" --json
zermes worker-agents approval request-changes <approval_id> --actor <actor> --reason "<reason>" --json
zermes worker-agents approval delegate <approval_id> --actor <actor> --delegate-to <reviewer> --reason "<reason>" --json
zermes worker-agents assets --json
zermes worker-agents asset reject <proposal_id> --actor <actor> --reason "<reason>" --json
zermes worker-agents cleanup-plan --json
zermes worker-agents import-dry-run --manifest <manifest.json> --json
```

Read `references/command-reference.md` for parameter meanings and additional draft kinds.
Read `references/information-sources.md` for where the current product state lives and how to inspect it safely.

## Safety Rules

- Never say the draft command has created the worker. It only produces a draft or validation result.
- Never combine parent and child creation into the same execution wave when the child depends on a newly created parent.
- Never bypass approval for high-risk, destructive, permission-expanding, external-agent, or asset-moving changes.
- Never instruct the user to edit JSON store files directly.
- Never expose or request raw transcript, stdout, stderr, private memory text, secrets, tokens, credentials, API keys, or passwords.


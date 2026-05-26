# Approval And Execution Workflow

WorkerAgent organization changes are proposal-first. The CLI draft commands create validation output and action requests; they are not direct execution.

## Draft Review

After each `evolution-draft`, inspect:

- `blockers`
- `risk_badges`
- `approval_requirement`
- `user_approval_required`
- `source_refs`

If `blockers` is non-empty, do not approve or proceed. Explain what must be resolved first.

Common blockers:

- Missing requested worker id.
- Missing asset disposition plan for deletion.
- Missing destination node for merge.
- Missing rollback plan for merge.
- Active tasks blocking archive.
- Unknown or inactive parent node.

## Approval Queue

Use:

```bash
zermes worker-agents approvals --json
```

Find approval items related to the generated proposal. Explain to the user which proposal each approval corresponds to.

## Approval Actions

Approve safe or reviewed proposals:

```bash
zermes worker-agents approval approve <approval_id> \
  --actor <actor-id> \
  --reason "<review summary>" \
  --json
```

Approve high-risk proposals:

```bash
zermes worker-agents approval approve <approval_id> \
  --actor <actor-id> \
  --reason "<review summary>" \
  --confirm-high-risk \
  --json
```

Reject:

```bash
zermes worker-agents approval reject <approval_id> \
  --actor <actor-id> \
  --reason "<why rejected>" \
  --json
```

Request changes:

```bash
zermes worker-agents approval request-changes <approval_id> \
  --actor <actor-id> \
  --reason "<what must change>" \
  --json
```

Delegate:

```bash
zermes worker-agents approval delegate <approval_id> \
  --actor <actor-id> \
  --delegate-to <reviewer-id> \
  --reason "<why delegated>" \
  --json
```

## Execution Availability

Use:

```bash
zermes worker-agents evolution --json
```

Only proposals with:

- `status` equal to `approved`
- no `blockers`
- `can_execute` true

should be described as execution-ready.

If `disabled_reason` is present, report it and do not proceed.

## Parent-Child Checkpoint

Before generating child commands for newly created parents, verify that parent is active:

```bash
zermes worker-agents organization --json
```

Look for the parent node id. If it is missing, still pending, archived, deprecated, or read-only, do not attach children yet.

## Destructive Or Boundary-Changing Changes

For deletion, merge, archive, permission expansion, external-agent runtime changes, or asset movement:

- Require explicit user confirmation.
- Require needed refs such as asset disposition or rollback plan.
- Show risk and blockers.
- Prefer `--dry-run` where available.
- Do not instruct direct file edits.

## Final Verification

After approved execution has completed through the governed executor, verify:

```bash
zermes worker-agents workers --json
zermes worker-agents organization --json
zermes worker-agents chats --json
zermes worker-agents evolution --json
zermes worker-agents approvals --json
```

Report the final organization tree, remaining blockers, and any pending approvals.


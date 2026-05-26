# WorkerAgent CLI Command Reference

Use the commands in this file to guide users through organization creation and adjustment. These commands are product entrypoints; they do not directly edit active files.

## Inspect Current State

```bash
zermes worker-agents overview --json
```

Shows dashboard snapshot: worker summaries, organization nodes, departments, risk badges, and warnings.

```bash
zermes worker-agents workers --json
```

Shows worker rows. Useful filters:

```bash
zermes worker-agents workers --status enabled --json
zermes worker-agents workers --department engineering --json
zermes worker-agents workers --runtime internal --json
zermes worker-agents workers --risk external_unhealthy --json
```

Arguments:

- `--status`: filter lifecycle status.
- `--department`: filter workers attached to a department.
- `--runtime`: filter runtime type.
- `--risk`: filter by risk badge code.

```bash
zermes worker-agents organization --json
```

Shows organization tree view. Use it to find valid parent node ids before creating children.

```bash
zermes worker-agents evolution --json
```

Shows evolution proposal workbench: proposal ids, kinds, status, blockers, can-execute status, disabled reason, and next required action.

```bash
zermes worker-agents approvals --json
```

Shows approval queue. Use it to find approval ids and whether high-risk confirmation is required.

## Create A WorkerAgent Draft

```bash
zermes worker-agents evolution-draft \
  --proposal-kind create_child_agent \
  --actor <actor-id> \
  --target-node <existing-parent-node-id> \
  --requested-worker <new-worker-id> \
  --reason "<why this worker is needed>" \
  --json
```

Arguments:

- `--proposal-kind create_child_agent`: request a new child WorkerAgent.
- `--actor`: user or agent requesting the draft.
- `--target-node`: existing active parent organization node.
- `--requested-worker`: id for the requested new WorkerAgent.
- `--reason`: responsibility and business reason.

The command returns blockers, risk badges, approval requirement, and user approval requirement. It does not create the active worker.

## Delete A WorkerAgent Draft

```bash
zermes worker-agents evolution-draft \
  --proposal-kind delete_child_agent \
  --actor <actor-id> \
  --target-node <worker-or-node-id> \
  --asset-disposition-ref <asset-disposition-plan-ref> \
  --reason "<why deletion is needed>" \
  --json
```

Deletion is destructive. Require an asset disposition plan and explicit user confirmation during approval.

## Merge Department Draft

```bash
zermes worker-agents evolution-draft \
  --proposal-kind merge_department \
  --actor <actor-id> \
  --target-node <source-department-node-id> \
  --destination-node <destination-node-id> \
  --rollback-plan-ref <rollback-plan-ref> \
  --reason "<why merge is needed>" \
  --json
```

Merges change ownership and routing boundaries. Require a rollback plan and user confirmation.

## Archive Node Draft

```bash
zermes worker-agents evolution-draft \
  --proposal-kind archive_node \
  --actor <actor-id> \
  --target-node <node-id> \
  --reason "<why archive is needed>" \
  --json
```

Archiving may be blocked by active tasks. Resolve blockers before approval/execution.

## Approve A Proposal

```bash
zermes worker-agents approval approve <approval_id> \
  --actor <actor-id> \
  --reason "<review summary>" \
  --json
```

For high-risk approvals:

```bash
zermes worker-agents approval approve <approval_id> \
  --actor <actor-id> \
  --reason "<review summary>" \
  --confirm-high-risk \
  --json
```

Other approval actions:

```bash
zermes worker-agents approval reject <approval_id> --actor <actor-id> --reason "<reason>" --json
zermes worker-agents approval request-changes <approval_id> --actor <actor-id> --reason "<changes needed>" --json
zermes worker-agents approval delegate <approval_id> --actor <actor-id> --delegate-to <reviewer-id> --reason "<why delegate>" --json
```

## Verify After Each Wave

```bash
zermes worker-agents evolution --json
zermes worker-agents approvals --json
zermes worker-agents organization --json
zermes worker-agents workers --json
```

Proceed to the next wave only after parent nodes are approved, executed, and visible in organization output.


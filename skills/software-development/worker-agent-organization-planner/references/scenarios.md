# WorkerAgent Organization Scenarios

Use these examples as patterns. Adjust ids, actor, parent node, and reasons to match the user's request.

## Multi-Level Staff Creation

User:

```text
Create an employee responsible for code implementation. It has two subordinates:
frontend implementation and backend implementation. Frontend has three employees:
web UI, app, and WeChat mini program.
```

Proposed tree:

```text
code-implementation
├─ frontend-implementation
│  ├─ web-interface
│  ├─ app-client
│  └─ wechat-mini-program
└─ backend-implementation
```

Ask for the existing parent node if unknown:

```text
Which existing organization node should code-implementation be created under?
For example: engineering, product, or root.
```

Wave 1:

```bash
zermes worker-agents evolution-draft \
  --proposal-kind create_child_agent \
  --actor user \
  --target-node <existing-parent-node> \
  --requested-worker code-implementation \
  --reason "Create a worker responsible for code implementation" \
  --json
```

After Wave 1 is approved and active, Wave 2:

```bash
zermes worker-agents evolution-draft \
  --proposal-kind create_child_agent \
  --actor user \
  --target-node code-implementation \
  --requested-worker frontend-implementation \
  --reason "Create a worker responsible for frontend implementation" \
  --json
```

```bash
zermes worker-agents evolution-draft \
  --proposal-kind create_child_agent \
  --actor user \
  --target-node code-implementation \
  --requested-worker backend-implementation \
  --reason "Create a worker responsible for backend implementation" \
  --json
```

After frontend is approved and active, Wave 3:

```bash
zermes worker-agents evolution-draft \
  --proposal-kind create_child_agent \
  --actor user \
  --target-node frontend-implementation \
  --requested-worker web-interface \
  --reason "Create a worker responsible for web UI implementation" \
  --json
```

```bash
zermes worker-agents evolution-draft \
  --proposal-kind create_child_agent \
  --actor user \
  --target-node frontend-implementation \
  --requested-worker app-client \
  --reason "Create a worker responsible for app implementation" \
  --json
```

```bash
zermes worker-agents evolution-draft \
  --proposal-kind create_child_agent \
  --actor user \
  --target-node frontend-implementation \
  --requested-worker wechat-mini-program \
  --reason "Create a worker responsible for WeChat mini program implementation" \
  --json
```

## Add One Specialist Under Existing Department

```bash
zermes worker-agents evolution-draft \
  --proposal-kind create_child_agent \
  --actor user \
  --target-node engineering \
  --requested-worker database-specialist \
  --reason "Create a database specialist worker for schema and query optimization" \
  --json
```

## Archive An Inactive Worker

```bash
zermes worker-agents evolution-draft \
  --proposal-kind archive_node \
  --actor user \
  --target-node old-frontend-worker \
  --reason "Archive inactive frontend worker after replacement" \
  --json
```

If blockers mention active tasks, tell the user to complete or reassign those tasks first.

## Delete A Worker

```bash
zermes worker-agents evolution-draft \
  --proposal-kind delete_child_agent \
  --actor user \
  --target-node obsolete-worker \
  --asset-disposition-ref disposition-obsolete-worker-001 \
  --reason "Delete obsolete worker after asset disposition review" \
  --json
```

Deletion is destructive. Require explicit user confirmation and an asset disposition plan.

## Merge Departments

```bash
zermes worker-agents evolution-draft \
  --proposal-kind merge_department \
  --actor user \
  --target-node frontend-team \
  --destination-node engineering \
  --rollback-plan-ref rollback-frontend-merge-001 \
  --reason "Merge frontend team into engineering after organization consolidation" \
  --json
```

Department merge changes ownership and chat boundaries. Require rollback plan, approval, and final verification.

## Rename Or Responsibility Change

If the user asks to rename a worker or change responsibility, first determine whether the current system has a rename/update proposal kind. If not available, do not invent a direct file edit. Offer a safe plan:

1. Create a new worker with the desired responsibility.
2. Migrate or review assets through asset proposals.
3. Archive the old worker after verification.

Use creation plus archive drafts instead of direct mutation.


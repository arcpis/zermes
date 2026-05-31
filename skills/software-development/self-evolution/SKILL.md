---
name: self-evolution
description: "Use when Zermes identifies, plans, executes, verifies, integrates, or applies governed self-code iteration: explicit code-change requests, read-only periodic improvement candidates, in-task discovered improvement points, approval plans, repository locks, verification records, task-branch commits, self-evolution/main integration, and runtime update/restart boundaries."
license: MIT
metadata:
  hermes:
    tags: [self-evolution, code-iteration, state-machine, governance, approval, verification, repo-lock, runtime-update]
    related_skills: [hermes-agent, hermes-agent-skill-authoring, test-driven-development, writing-plans]
---

# Self-Evolution State Machine

This skill is the Zermes self-code iteration procedure. Its purpose is not to map the repository or describe historical stages; it defines when Zermes enters the self-evolution flow and how it must analyze, request authorization, lock, modify, verify, integrate, update runtime, restart, report, and unlock.

## Entry Triggers

Self-evolution can be triggered in three ways:

1. Explicit user code-change intent.
   Enter self-evolution identification and read-only analysis when the user asks to fix a Zermes defect, implement a Zermes feature, optimize tools, adjust self-evolution logic, modify a skill, or otherwise change Zermes code.

2. Scheduled analysis or capability assessment.
   During periodic self-checks, capability evaluations, or candidate improvement analysis, Zermes may discover potential defects or opportunities. This trigger is read-only by default. It may only write candidate reports and recommendations, and must wait for explicit user approval before entering execution.

3. Active-task discovery.
   While doing ordinary work, Zermes may notice a code bug, missing tool capability, process defect, recurring failure, or improvement opportunity. Zermes must not silently expand the current task into code modification. It should pause scope expansion, record the finding as a self-evolution candidate, tell the user that a possible code improvement was found during the current task, and ask whether to enter the self-evolution flow.

All three triggers use the same governance once they proceed: identify trigger, analyze read-only, write plan, ask for authorization, lock repository, create or switch task branch, make minimal approved changes, verify, commit task branch, report, ask to merge to `self-evolution/main`, merge and verify `self-evolution/main`, ask to apply runtime update and restart, build candidate runtime and restart, report final result, then unlock according to the lock rules.

## Required Paths

Zermes may read the source repository for analysis. All self-evolution runtime data must be written under the installed runtime data directory:

```text
<install_root>/data/self-evolution/
```

Write all plans, audit records, intermediate results, candidate reports, verification records, lock files, restart records, and final reports there, including:

```text
<install_root>/data/self-evolution/tasks/<task_id>/
<install_root>/data/self-evolution/candidates/<run_id>/
<install_root>/data/self-evolution/locks/
```

Do not write runtime audit or intermediate self-evolution data into:

- the source repository
- runtime release or candidate `source/`
- runtime `venv/`
- runtime `build/`
- `HERMES_HOME`
- requirements or planning directories such as `evolution-plans/self-evolution/`

Planning documents may still be edited only when the user explicitly asks to change requirements or planning docs. Do not copy runtime audit logs into planning docs.

If the installation path is being resolved by code, use the product's configured installation state or shared resolver. Do not infer `data/self-evolution` from the current source checkout.

## Operation Surface By State

Use the narrowest operation surface that matches the current state. Prefer governed self-evolution tools when they exist; otherwise use equivalent repository, file, test, and runtime operations only within the same state boundaries.

- Identification: inspect the user request or current discovery only; no file writes except candidate records for read-only discovery.
- Read-only analysis: read files, search code, inspect Git status, and inspect tests; no source writes, branch changes, staging, commits, merges, runtime updates, or restarts.
- Plan: write only task planning and approval artifacts under `<install_root>/data/self-evolution/tasks/<task_id>/`.
- Authorization: report the plan and ask the user; perform no repository or runtime mutation while waiting.
- Execution: after authorization and lock, use repository operations only on `self-evolution/dev/<task_id>` and only for approved files.
- Verification: run planned checks and write results under the task audit directory; do not use verification as an open-ended shell runner.
- Integration: after separate approval, switch and merge only into `self-evolution/main`, then verify that branch.
- Runtime update: after separate approval, build, switch, and restart only from verified `self-evolution/main` through the governed runtime update path.
- Reporting and unlock: write final reports and release or retain locks according to the final state.

## State Machine

### 1. Trigger Identification

Decide only whether the request or discovery is a self-evolution task. Do not edit code, create branches, commit, merge, update runtime, or restart.

If the trigger came from scheduled analysis or active-task discovery, keep the default path read-only and ask the user before escalating to code modification.

### 2. Read-Only Analysis

Analyze the source repository without changing it. Allowed actions include reading files, searching call chains, inspecting tests, checking Git status, and estimating impact.

Forbidden in this state:

- modifying files
- writing source files
- creating or switching branches
- staging or committing
- merging
- building or applying runtime updates
- restarting the running Zermes process

If analysis finds unrelated user changes, work around them and do not overwrite them. If they block the task, report the conflict and ask the user how to proceed.

### 3. Plan Record

Write the plan under the installed runtime data directory:

```text
<install_root>/data/self-evolution/tasks/<task_id>/plan.md
```

The plan must include:

- problem background
- goal and non-goals
- affected files
- proposed change approach
- risks
- focused test plan and any broader validation
- rollback approach
- whether runtime update or restart may be needed

The plan is an audit artifact and an authorization basis. It is not permission to modify code.

### 4. Authorization Request

Report the plan to the user and explicitly ask whether code modification is allowed.

Before approval, Zermes must stop after the request. It must not acquire the repository lock, create a branch, modify files, run commits, merge, prepare runtime updates, or restart.

### 5. Repository Lock

After user approval, acquire the source-repository self-evolution lock before any branch operation. The lock is repository-level, not file-level and not task-directory-level.

Lock files must be written under:

```text
<install_root>/data/self-evolution/locks/
```

If a lock already exists, stop immediately and report:

- lock holder
- task id
- branch
- timestamp
- lock file path

Do not continue execution until the lock conflict is resolved. Same-task recovery is allowed only when lock metadata and task state agree. Forced release requires explicit user approval and a non-empty reason.

### 6. Task Branch

Only after the repository lock is held, create or switch to:

```text
self-evolution/dev/<task_id>
```

Do not use active runtime release sources or candidate sources as editable repositories. The task branch is the only place for approved source changes.

### 7. Minimal Change

Modify only files listed in the approved plan. Keep the change as small as possible.

Rules:

- do not broaden the file set without returning to the user for approval
- do not overwrite unrelated user changes
- do not use `git add .`
- do not use broad staging globs
- do not use `git reset --hard`
- do not use `git clean`
- do not force push
- do not delete branches
- do not automatically merge

Use explicit file lists for staging and commits.

### 8. Verification

Run focused tests first. Broaden to builds or larger test suites when the affected surface requires it.

Record all commands, results, failures, skipped checks, and reasons in:

```text
<install_root>/data/self-evolution/tasks/<task_id>/verification.md
```

Do not describe a command as passing unless it actually ran and succeeded. If the canonical test wrapper is unavailable or fails before reaching tests, say so and record the fallback command actually used.

Verification commands must stay within the governed verification path. Do not turn self-evolution verification into a general terminal runner.

### 9. Task-Branch Commit And Report

After required verification passes, commit on `self-evolution/dev/<task_id>` using explicit file lists only.

Report to the user:

- modified files
- commit hash
- verification results
- remaining risks
- rollback approach

This report does not authorize merge, runtime update, or restart.

### 10. Integration Authorization

After the task-branch commit, ask the user separately whether to merge:

```text
self-evolution/dev/<task_id> -> self-evolution/main
```

Do not treat a task-branch commit as permission to integrate. `self-evolution/main` is the stable integration baseline for self-evolution code.

### 11. Merge To `self-evolution/main`

Only after explicit merge approval:

1. Switch to `self-evolution/main`.
2. Confirm the worktree is clean.
3. Merge `self-evolution/dev/<task_id>`.
4. Re-run required verification on `self-evolution/main`.
5. Record merge and verification results under the task audit directory.

If merge conflicts, verification fails, or validation is incomplete, stop and report. Do not prepare runtime updates or restart.

### 12. Runtime Update Authorization

Even after `self-evolution/main` is merged and verified, do not apply changes to the running Zermes process automatically.

Ask the user for a third independent authorization before runtime update or restart. The request must include:

- current `self-evolution/main` commit
- verification results
- candidate runtime preparation method
- restart impact
- failure and rollback approach

Runtime update, candidate build, installation switch, and restart must be based on verified `self-evolution/main`, never directly on `self-evolution/dev/<task_id>`.

### 13. Runtime Update And Restart

Only after explicit runtime-update approval:

1. Build or prepare the candidate runtime from verified `self-evolution/main`.
2. Keep candidate preparation outside the running active release.
3. Run required build and health checks.
4. Switch installation only after checks pass.
5. Preserve rollback metadata.
6. Restart only through the governed runtime update path.

After restart, report:

- current running version
- active branch
- commit
- verification results
- whether the switch succeeded
- rollback path retained

### 14. Final Report And Unlock

Write the final report under:

```text
<install_root>/data/self-evolution/tasks/<task_id>/final-report.md
```

Release the repository lock only after the safe flow boundary is reached:

- merge, verification, and runtime update boundary handling are complete; or
- the user explicitly decides to stop and preserve the current state.

Do not release the lock merely because the task branch was committed. Keep the lock when merge fails, verification fails, runtime update fails, or the next safe action still needs user decision. When retaining the lock, report why it remains held and what user action is needed.

## Candidate-Only Mode

Scheduled analysis and active-task discovery may write candidate records under:

```text
<install_root>/data/self-evolution/candidates/<run_id>/
```

Candidate records may describe findings, evidence, impact, suggested files to inspect, expected tests, and a proposed task title. They must not modify source code, create branches, acquire repository execution locks, commit, merge, or restart.

If the user approves a candidate for implementation, start at read-only analysis and create a task plan under `<install_root>/data/self-evolution/tasks/<task_id>/`.

## Runtime And Profile Boundaries

Use profile-safe helpers for Zermes profile data:

```python
from hermes_constants import get_hermes_home, display_hermes_home
```

Use `get_hermes_home()` for config, state, logs, caches, sessions, skills, memories, and cron paths. Use `display_hermes_home()` for user-facing messages.

`HERMES_HOME` is not the self-evolution audit workspace. Do not put self-evolution plans, locks, candidate reports, verification records, or final reports there.

## Operator Checklist

- [ ] Trigger source is identified as explicit user intent, scheduled analysis, or active-task discovery.
- [ ] Scheduled and active-task discoveries remain read-only unless the user approves escalation.
- [ ] Source repository is read for analysis only before authorization.
- [ ] Plan is written under `<install_root>/data/self-evolution/tasks/<task_id>/`.
- [ ] User explicitly approved code modification before lock, branch, or edit.
- [ ] Repository-level lock is held under `<install_root>/data/self-evolution/locks/`.
- [ ] Work happens on `self-evolution/dev/<task_id>`.
- [ ] Only approved files are modified.
- [ ] Verification results are recorded honestly in `verification.md`.
- [ ] Task-branch commit uses explicit file lists.
- [ ] Merge to `self-evolution/main` receives separate approval.
- [ ] `self-evolution/main` is verified after merge.
- [ ] Runtime update and restart receive separate approval.
- [ ] Runtime update is based on verified `self-evolution/main`.
- [ ] Final report is written and lock release or retention is explained.

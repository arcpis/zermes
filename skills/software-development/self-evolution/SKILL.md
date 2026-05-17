---
name: self-evolution
description: "Use when planning, reviewing, implementing, verifying, or documenting governed Hermes Agent self-evolution work: complete_code_task approval plans, approved code task execution, self-evolution audit records, repo-lock safety, self-update application, requirement docs under evolution-plans/self-evolution, or any change to code_modification self-evolution tools."
license: MIT
metadata:
  hermes:
    tags: [self-evolution, code-modification, governance, approval, verification, repo-lock]
    related_skills: [hermes-agent, hermes-agent-skill-authoring, test-driven-development, writing-plans]
---

# Self-Evolution

## Use This Skill For

Use this skill when the task involves Hermes self-evolution:

- planning or updating `evolution-plans/self-evolution`
- creating or reviewing `complete_code_task` approval plans
- executing approved self-evolution code tasks
- handling self-evolution task audit records
- managing repository locks
- verifying, finalizing, or reporting self-evolution work
- applying a finalized self-update to a running installation
- changing `code_modification` self-evolution tools

## Workspace Map

```text
<outer>/hermes-agent/        # product code repository
<outer>/evolution-plans/     # requirements and planning workspace
<outer>/evolution-plans/self-evolution/
                            # planning source of truth
<install_prefix>/data/self-evolution/
                            # installed runtime audit and intermediate data
<project_root_parent>/self-evolution/
                            # development/uninstalled fallback audit data
```

Key product modules:

```text
code_modification/governance.py
code_modification/approval.py
code_modification/git_workflow.py
code_modification/executor.py
code_modification/verifier.py
code_modification/thinking.py
code_modification/token_strategy.py
code_modification/self_update.py
code_modification/runtime_update.py
tools/code_modification_tool.py
toolsets.py
```

## First Decide The Task Type

1. If the user asks to plan or update requirements, edit `evolution-plans/self-evolution/` only.
2. If the user asks to improve Hermes code, create an approval plan first. Do not edit product code yet.
3. If the user has explicitly approved a task, follow the approved execution flow.
4. If the user asks for periodic thinking or candidates, keep it read-only and write candidate reports only.
5. If the user asks to apply finalized code to the running agent, use the runtime update flow. Finalize is not activation.

## Path Rules

For runtime audit and intermediate data, resolve the self-evolution workspace in this order:

1. Explicit workspace path supplied by the tool or test.
2. `self_evolution_data_dir` from installer `active.json` or `install-state.json`.
3. `<install_prefix>/data/self-evolution/`.
4. Development fallback: `<project_root_parent>/self-evolution/`.

Write these under the resolved self-evolution workspace:

- `tasks/<task_id>/plan.md`
- `tasks/<task_id>/approval.md`
- `tasks/<task_id>/change-log.md`
- `tasks/<task_id>/verification.md`
- `tasks/<task_id>/final-report.md`
- `candidates/<run_id>/thinking-report.md`
- `candidates/<run_id>/candidates.json`
- `locks/repositories/<repo_key>.lock`

Do not write runtime audit data into:

- `evolution-plans/self-evolution/`
- `HERMES_HOME`
- active release or candidate `source/`
- release `venv/` or `build/`

Code must use the shared self-evolution workspace resolver. Do not hand-build audit roots in individual modules.

## Approval Planning Flow

Before product code changes:

1. Resolve the development source repository. Do not use a runtime release/candidate source copy.
2. Build the task audit layout with the shared resolver.
3. Write the approval plan and approval request.
4. Ask for explicit user approval.
5. Stop. Do not create branches, edit code, run commits, or apply updates.

The plan must include:

- requirement understanding
- affected areas
- implementation approach
- task breakdown
- risks
- test plan
- explicit approval request

## Approved Execution Flow

1. Resolve and validate the development source repository. Never default to an active release or candidate runtime source copy.
2. Acquire or verify the repository-level self-evolution lock.
3. Create or switch to the dedicated branch `self-evolution/dev/<task_id>`.
4. Make only the approved code changes.
5. Update required tests and docs.
6. Plan verification with allow-listed commands.
7. Run verification and record results.
8. Record safety review when required.
9. Commit with explicit file lists only.
10. Finalize only after required verification passes.
11. Release the repository lock after successful finalize.
12. Report paths, commits, verification, and remaining risks.
13. Ask separately before applying the update to the running runtime.

## Repository Lock Rules

1. Lock by development source repository, not file, branch, or task directory.
2. Acquire the lock before branch creation or branch switching.
3. Check lock ownership before commit, verification, safety review, and finalize.
4. On conflict, stop and report locked project root, task id, branch, lock time, and lock file.
5. Allow same-task recovery only when lock data and `execution-state.json` agree.
6. Release the lock after successful finalize.
7. Keep the lock after failed verification or blocked finalize.
8. Forced release requires explicit user approval and a non-empty reason.
9. Use atomic JSON file creation for lock acquisition; do not use read-then-write locking.

## Verification Rules

1. Use focused tests first.
2. Broaden tests when the changed surface requires it.
3. Prefer the repository canonical wrapper when it works:

```bash
scripts/run_tests.sh
```

Known WSL focused command:

```bash
cd /mnt/e/Users/30411/Desktop/agent/hermes-agent/hermes-agent
source venv/bin/activate
python -m pytest \
  tests/self_evolution \
  tests/test_model_tools.py \
  tests/test_toolsets.py \
  -q
```

Do not claim `scripts/run_tests.sh` passed unless Bash actually ran it and reached pytest. If a tool is unavailable, say so.

## Git and Commit Rules

- Never use `git reset --hard`, `git clean`, force push, or branch deletion unless the user explicitly asks.
- Never overwrite unrelated user changes.
- Use explicit file lists for commits.
- Do not stage with `git add .` or broad globs in self-evolution execution.
- Keep task commits small and auditable.
- Do not auto-merge into main or master.
- Finalize to the self-evolution integration branch is not runtime update activation.

## Runtime Update Boundary

1. Require explicit user approval before preparing or activating a runtime update.
2. Prepare candidate source and environment outside the running active release.
3. Run allow-listed build and health checks.
4. Promote and activate only after verification.
5. Use the runtime update lock for runtime pointer changes.
6. Do not mix runtime update locks with repository-level code-iteration locks.
7. Preserve rollback metadata and restart intent records.

## Profile-Safe Paths

Use:

```python
from hermes_constants import get_hermes_home, display_hermes_home
```

Use `get_hermes_home()` for config, state, logs, caches, sessions, skills, memories, and cron paths. Use `display_hermes_home()` for user-facing messages.

`HERMES_HOME` is not the self-evolution audit workspace. Tests that mock `Path.home()` must also set `HERMES_HOME`.

## Requirement Docs

When changing self-evolution requirements:

1. Add or update `需求/需求N/README.md`.
2. Add `需求/需求N/实现方案.md` when implementation details matter.
3. Update `README.md`, `架构.md`, `实现计划.md`, and `进度.md`.
4. Update this Skill when the workflow, path rules, or safety rules change.
5. Keep planning docs concise. Do not copy runtime audit logs into planning docs.

Current phase index:

```text
1 workspace/audit/Git governance
2 approval-before-change planning
3 approved execution and Git flow
4 verification and safety review
5 prompt-triggered routing
6 read-only scheduled thinking
7 low-token analysis context
8 development source repository resolution
9 self-update application and safe restart
10 self-evolution test directory organization
11 repository-level serial lock
12 self-evolution Skill
13 runtime data directory alignment
```

## Do Not

- Do not modify product code before explicit approval.
- Do not resolve active runtime release source as the editable repository.
- Do not start a second execution task for a locked repository.
- Do not treat scheduled thinking as an executor.
- Do not turn the verifier into a general command runner.
- Do not use broad Git staging.
- Do not apply runtime updates as part of finalize.
- Do not write audit data to planning docs, `HERMES_HOME`, or runtime source copies.

## Verification Checklist

- [ ] Task type is clear: planning, approval, approved execution, verification, finalize, thinking, or runtime update.
- [ ] Product code was not changed before explicit approval.
- [ ] The development source repository is validated and is not a runtime copy.
- [ ] Runtime audit paths use the shared resolver.
- [ ] Installed runtime audit paths resolve to `<install_prefix>/data/self-evolution/`.
- [ ] Development fallback audit paths resolve to `<project_root_parent>/self-evolution/`.
- [ ] Repository lock rules are respected for approved execution.
- [ ] Commits use explicit file lists only.
- [ ] Verification results are recorded honestly.
- [ ] Runtime update approval is separate from code finalize.
- [ ] Planning docs and product docs agree with the implemented behavior.

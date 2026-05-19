# Worker Agent Retention And Cleanup

Worker-agent cleanup separates durable profile assets from clearable runtime
data. The cleanup code must never delete worker identity, private memory, skill
bindings, registry records, policies, durable manifests, or audit summaries.

Durable retention policy is stored under the active profile home:

```text
<zermes_home>/worker_agents/shared/retention-policy.json
```

Runtime cleanup plans and execution records live under installation data:

```text
<install_dir>/data/worker_agents/cleanup-runs/<cleanup_run_id>/result.json
```

## Policy

`RetentionPolicyStore` loads a conservative default policy when no policy file
exists. The default keeps active tasks and protected long-term data forever,
requires review for orphaned runtime directories and unretained candidates, and
allows short-window cleanup for rebuildable caches, logs, transcripts, and old
terminal task runtime.

The policy is a durable configuration input. It does not contain private memory,
raw transcripts, credentials, stdout, stderr, or task artifacts.

## Planning

`CleanupPlanner` scans only `<install_dir>/data/worker_agents/` and creates a
dry-run `CleanupPlan`. It classifies task runtime by current task status,
update time, pending requests, and result candidates.

The planner does not delete files. Damaged task directories, schema mismatches,
unknown runtime folders, and task results with unretained manifest, memory, or
audit candidates are marked for review instead of automatic deletion.

## Execution

`CleanupExecutor` executes only a previously generated plan. Before deleting it
checks that the plan belongs to the current runtime root, every item path is
relative to that root, the item is marked deletable, and the task still has a
terminal status with no pending requests or unretained candidates.

Execution writes a compact result record with deleted, skipped, and failed item
lists. It does not store raw transcript content, stdout, stderr, or credentials.

## Manifest Retention

`TaskResultRetentionService` explicitly promotes `manifest_candidates` and
`audit_summary_candidates` from task `result.json` into durable profile storage:

```text
<zermes_home>/worker_agents/manifests/<manifest_id>.json
<zermes_home>/worker_agents/shared/audit-summaries/<audit_summary_id>.json
```

Manifests store low-sensitivity artifact references and summaries, not artifact
contents. Audit summaries store compact decisions and risk conclusions, not raw
transcripts or process output.

Memory and learning candidates remain candidates. They are not written to
long-term worker memory or skill experience by the retention service.

Background scheduling, UI approval cards, message-router transcript management,
and memory personalization are separate later stages.

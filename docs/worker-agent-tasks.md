# Worker Agent Tasks

Worker task state is clearable runtime data. It lives under the installation
data directory, not under the active profile home:

```text
<install_dir>/data/worker_agents/tasks/<task_id>/
  state.json
  events.jsonl
  requests.jsonl
  rolling-summary.md
  result.json
  artifacts/
```

`state.json` is the current task snapshot. It stores the task id, worker id,
status, title, objective, compact input summary, task-local budgets, workspace
summary, progress, cancellation or failure details, result summary, artifact
references, request references, tags, and metadata.

The snapshot may include a low-sensitivity worker profile summary, such as
schema version, role, runtime type, adapter name, model name, and budget limits.
It must not copy private memory, skill bindings, full tool permissions, runtime
secrets, credentials, or raw transcripts from the durable worker profile.

## Lifecycle

Task lifecycle status is implemented in `worker_agents.task_state`.

- `draft`: created but not yet queued.
- `queued`: ready for a future scheduler or adapter.
- `running`: execution is in progress.
- `waiting_for_input`: paused for user or main-agent input.
- `waiting_for_approval`: paused for approval of risk, cost, or permission.
- `cancelling`: cancellation has been requested and cleanup is pending.
- `cancelled`: cancellation is complete.
- `failed`: task failed with a readable reason.
- `succeeded`: task completed with a compact result.
- `expired`: task timed out or stale runtime data was marked expired.

Terminal statuses are `cancelled`, `failed`, `succeeded`, and `expired`.
Terminal tasks cannot be restarted by the lifecycle helper.

## Service API

Use `WorkerTaskService` for registry-aware task operations:

```python
task_service = WorkerTaskService.from_registry_service(registry_service)
task = task_service.create_task(
    task_id="task-1",
    worker_id="researcher",
    title="Survey",
    objective="Summarize the current state.",
    created_by="main-agent",
    queue=True,
)
```

The service provides:

- `create_task`
- `get_task`
- `list_tasks`
- `queue_task`
- `start_task`
- `wait_for_input`
- `wait_for_approval`
- `request_cancel_task`
- `cancel_task`
- `fail_task`
- `complete_task`
- `expire_task`

Only `enabled` workers can receive new tasks. Other worker lifecycle statuses
remain queryable, but new task creation is rejected. The service does not start
runtime adapters, execute work, create chat threads, or write long-term memory.

## Events And Results

`events.jsonl` is an append-only task-local timeline. `requests.jsonl` records
task-local requests for approval, input, or coordinator action. These files are
not a replacement for the later message router transcript.

`rolling-summary.md` is regenerable intermediate data. `result.json` stores a
compact result summary, task-local artifact references, and optional
`manifest_candidates`, `memory_candidates`, or `audit_summary_candidates`.
Those candidates are markers only. Writing durable manifests, memories, learning
records, or audit summaries belongs to later retention and personalization
flows.

Artifact paths in task results must be relative to the task directory. Absolute
paths and `..` escapes are rejected.

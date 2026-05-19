# Worker Agent Registry

The worker registry is the durable lifecycle index for managed worker agents.
It lives in the active profile home:

```text
<zermes_home>/worker_agents/registry.json
```

`registry.json` is intentionally lightweight. It stores list and lifecycle
metadata such as worker id, display name, role, runtime type, status, profile
path, tags, timestamps, and status reason. The full identity, permissions,
model settings, budgets, memory policy, skill bindings, and delegation limits
remain in each worker's `worker.json` profile.

## Lifecycle

Worker lifecycle status is implemented in `worker_agents.registry`.

- `registered`: recorded in the registry, but not available for scheduling.
- `enabled`: available for future selection and scheduling.
- `disabled`: retained but unavailable, usually for pause or review.
- `archived`: hidden from normal lists and unavailable.
- `deleted`: soft-deleted registry tombstone.

Allowed transitions are deliberately narrow:

```text
registered -> enabled | disabled | archived | deleted
enabled    -> disabled | archived | deleted
disabled   -> enabled | archived | deleted
archived   -> disabled
deleted    -> terminal
```

Archived workers cannot jump directly back to enabled. Restore them to disabled
first so later callers can re-check profile validity and permissions before
enabling.

## Delete Behavior

Deletion is soft by default. `delete_worker` marks the registry record as
`deleted`, writes `deleted_at`, and records `delete_mode` as `soft_delete`.
It does not remove:

- `workers/<worker_id>/worker.json`
- private memory
- skill bindings
- manifests
- audit summaries

Physical removal of long-term assets belongs to a later retention or explicit
administrative workflow.

## Service API

Use `WorkerRegistryService` for profile-aware lifecycle operations:

```python
service = WorkerRegistryService(WorkerAgentProfileStore())
record = service.register_worker(
    worker_id="researcher",
    display_name="Researcher",
    description="Finds and summarizes information.",
    role="research",
)
service.enable_worker(record.worker_id, updated_by="main-agent")
```

The service provides:

- `register_worker`
- `get_worker`
- `list_workers`
- `enable_worker`
- `disable_worker`
- `archive_worker`
- `delete_worker`
- `refresh_worker_index`

`register_worker` creates or saves the worker profile and then writes a registry
record in `registered` status. It does not enable the worker automatically.

`enable_worker` reloads and validates `worker.json` before changing status. If
the profile is missing, invalid, or has a mismatched `worker_id`, the registry
record is left unchanged.

`list_workers` returns lightweight registry records and hides deleted records by
default. It can filter by status, runtime type, and tags.

## Boundaries

The registry does not start runtime adapters, perform health checks, create chat
threads, route messages, write task state, store transcripts, or clean runtime
data. Those responsibilities belong to later runtime, message router, task
state, and retention layers.

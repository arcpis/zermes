# Worker Agent Profiles

Managed worker profiles are durable configuration records for long-lived worker
agents. They live in the active profile home and are intended to migrate with
the user's Zermes profile.

```text
<zermes_home>/worker_agents/workers/<worker_id>/worker.json
```

`worker.json` is the machine-readable contract. Optional human-facing files
such as `identity.md` can describe the worker in richer prose, but runtime code
must use `worker.json` for identity and policy decisions.

## Contract

The profile contract is implemented in `worker_agents.profile`.

Required identity fields:

- `worker_id`: stable worker id and durable directory name.
- `schema_version`: profile contract version. The initial version is `1`.
- `display_name`: user-facing worker name.
- `description`: short capability summary.
- `role`: concise responsibility label.

Policy fields:

- `responsibilities`: durable responsibility list.
- `runtime`: runtime type, adapter name, and optional configuration reference.
- `memory`: private memory enablement and write policy.
- `skills`: allowed skill ids and skill injection policy.
- `tools`: allowed tools and tools requiring approval.
- `workspace`: read roots, write roots, and temporary directory policy.
- `communication`: direct chat, group chat, report target, and approval policy.
- `model`: default model, allowed models, context window, and costly model approval.
- `budgets`: per-task token, per-turn token, and task cost ceilings.
- `limits`: concurrency, timeout, retry, and queue limits.
- `cost_policy`: cost owner and over-budget behavior.
- `delegation`: limits for temporary child agents.
- `metadata`: portable audit notes.

## Defaults

Defaults are intentionally conservative. A minimal profile grants no tools, no
workspace write roots, no direct user chat, no group chat, no temporary child
agent creation, and zero token budget. Later lifecycle or management code must
explicitly grant additional capability.

Runtime settings may reference external configuration, but profiles must not
store plaintext credentials or live process state.

## Store API

Use `WorkerAgentProfileStore` instead of joining profile paths manually:

```python
store = WorkerAgentProfileStore()
profile = store.create_default_worker_profile(
    "researcher",
    display_name="Researcher",
    description="Finds and summarizes information.",
    role="research",
)
store.save_worker_profile(profile)
loaded = store.load_worker_profile("researcher")
```

Saving a profile writes only `worker.json` and preserves sibling durable assets
such as `memory/`, `skills/`, or future policy files.

## Boundaries

Profiles do not register, enable, disable, archive, or delete workers. They also
do not launch runtime adapters, route messages, store task state, or decide
whether an approval request is satisfied. Those checks belong to later worker
registry, runtime, message routing, and execution layers.

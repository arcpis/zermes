# Worker Agent Department Skills

Department skill bindings are durable department guidance. They are not skill
installation, runtime execution, worker profile authorization, or tool-policy
approval.

## Storage

Department skill assets live under the profile-safe worker agent home:

```text
worker_agents/organization/departments/<department_id>/skills/
  proposals/
  active/
  history/
```

`proposals/` contains pending or reviewed candidates. `active/` contains only
approved bindings. `history/` stores superseded revisions.

## Lifecycle

Workers, department leads, the main agent, or routing services can create a
`DepartmentSkillBindingProposal` from low-sensitivity input. Private skill
experience can be converted with `proposal_from_skill_experience_input`, but the
conversion only carries summary, applicability, limits, risks, tool assumptions,
and source references.

Only `DepartmentSkillReviewService.approve` writes active bindings. Reject,
request changes, and expire update proposal state without writing active records.

## State Semantics

- `recommended`: eligible as a candidate when profile and permissions allow it.
- `default`: department default guidance, still subject to profile and permission
  checks.
- `restricted`: requires owner review before context policy may use it.
- `deprecated`: old guidance is withheld; replacement references may be shown.
- `disabled`: blocked.

Department defaults never modify worker profiles and never grant tools, workspace
paths, budget, or external adapter access.

## Inheritance

Only `inheritable_guidance` and `organization_guidance` can be inherited by child
departments. Child departments can override inherited guidance with stricter
rules. Conflict resolution is conservative: disabled, deprecated, and restricted
states win over default or recommended guidance.

## Runtime Boundary

Context injection must consume `DepartmentSkillSafeCandidate` through
`guard_department_skill_usage`. It must not read active binding records directly.
The safe candidate view contains only skill id, binding id, display title,
low-sensitive guidance summary, constraints, audit refs, and optional replacement
skill id. It does not include skill source code, full prompts, raw transcripts,
secrets, credentials, or external adapter logs.

# Zermes Unreleased

This document tracks unreleased changes for the Zermes codebase. It is separate
from the historical Hermes Agent release notes so older Hermes releases remain
accurate.

## Highlights

- Added a governed self-evolution workflow for repository improvements across
  planning, approval, execution, verification, thinking, and documentation sync.
- Added repository-local low-token analysis context under `.hermes-analysis-cache/`.
- Documented the self-evolution workflow across repository and website docs.

## Self-Evolution Workflow

Zermes now supports a conservative self-evolution flow:

- `complete_code_task` creates pre-change plans and approval requests without
  modifying product code.
- Approved implementation starts on dedicated task branches.
- Commits use explicit file lists instead of broad staging.
- Verification records gate finalization.
- `self_evolution_thinking` creates advisory candidate reports only.
- Final reports include documentation sync status for user-visible changes.

## Low-Token Analysis

- Added `code_modification/token_strategy.py`.
- Analysis input is limited to files inside the repository root.
- Reusable task context, documentation summaries, and context state are written
  under `.hermes-analysis-cache/`.
- Generated analysis cache files are ignored by git.

## Documentation

- Updated top-level repository docs for the self-evolution workflow.
- Updated website user, developer, security, tools, and toolset reference pages.
- Kept historical Hermes release notes unchanged.

## Verification

Focused self-evolution regression passed:

```bash
python -m pytest \
  tests/self_evolution \
  tests/test_model_tools.py \
  tests/test_toolsets.py \
  -q
```

Result:

```text
99 passed
```


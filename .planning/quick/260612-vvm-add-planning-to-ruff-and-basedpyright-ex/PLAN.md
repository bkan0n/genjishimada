---
quick_id: 260612-vvm
slug: add-planning-to-ruff-and-basedpyright-ex
status: planned
---

# Quick Task: Exclude `.planning` from local lint/type-check runs

## Goal

Make local and editor Ruff + BasedPyright runs ignore the `.planning/` directory.
The CI lint workflow (`.github/workflows/lint.yml`) already excludes `.planning`
because every step is invoked with explicit paths (`apps/api apps/bot libs/sdk`
for Ruff, per-app dirs for BasedPyright) — so **no workflow change is needed**.
The only gap is whole-repo invocations (e.g. `just lint-all`, editor integrations),
which is fixed at the config level in `pyproject.toml`.

## Changes

### `pyproject.toml`

1. `[tool.ruff].extend-exclude` (lines ~23-28) — add `".planning"` to the list.
2. `[tool.basedpyright].exclude` (lines ~78-83) — add `".planning"` to the list.

## Verification

- `grep -n '.planning' pyproject.toml` shows the entry in both `extend-exclude`
  and `exclude`.
- `uv run ruff check .` and `uv run basedpyright .` (if available) no longer
  traverse `.planning/`.

## Out of scope

- `.github/workflows/lint.yml` — already correct, do not modify.

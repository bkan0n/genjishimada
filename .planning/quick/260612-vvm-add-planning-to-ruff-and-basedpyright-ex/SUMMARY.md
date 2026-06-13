---
quick_id: 260612-vvm
slug: add-planning-to-ruff-and-basedpyright-ex
status: complete
---

# Summary: Exclude `.planning` from local lint/type-check runs

## What changed

Added `".planning"` to two arrays in `pyproject.toml`:

1. `[tool.ruff].extend-exclude` — added as the first entry (line 24).
2. `[tool.basedpyright].exclude` — added as the first entry (line 80).

This makes whole-repo Ruff and BasedPyright invocations (`just lint-all`, editor
integrations) skip the `.planning/` directory. The CI lint workflow
(`.github/workflows/lint.yml`) was already correct and was not modified.

No other lines in `pyproject.toml` were touched. The pre-existing modified
`uv.lock` was deliberately left untouched and unstaged.

## Verification

```
$ grep -n '.planning' pyproject.toml
24:    ".planning",
80:    ".planning",
```

`.planning` now appears in both the `extend-exclude` (line 24) and `exclude`
(line 80) arrays, as required.

## Commit

SHA: f24e6ed0a207a7fcccdbc94a93e92086c5af0a44

# Phase 09 — Deferred Items

Out-of-scope discoveries logged during plan execution (not fixed; not caused by this plan's changes).

| Discovered During | File | Issue | Disposition |
|-------------------|------|-------|-------------|
| 09-03 Task 2 | `apps/bot/extensions/tournaments.py` | Pre-existing `ruff format` drift (one comprehension wraps differently than the formatter wants). `just lint-bot` reformats it every run. Authored in Phase 10. | Defer — out of scope for 09-03 (touches only rabbit.py + definitions.json + new test). Resolve in a formatting/lint sweep or the owning Phase-10 plan. |
| 09-03 Task 2 | `apps/bot/utilities/transformers.py` | Pre-existing `ruff format` drift (CategoryTransformer comprehension line-length). `just lint-bot` reformats it every run. Authored in Phase 10. | Defer — out of scope for 09-03. |

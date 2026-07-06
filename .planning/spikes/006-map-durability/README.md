---
spike: 006
name: map-durability
type: standard
validates: "Given maps added only to the live DB, when the DB is rebuilt from migrations alone, then they vanish — and an exported idempotent seed (kept in the repo, regenerated from the DB by a separate job) makes them survive while keeping the endpoint instant"
verdict: VALIDATED
related: [004, 005]
tags: [maps, migrations, durability, seed]
---

# Spike 006: map-durability

## What This Validates

> **Given** maps are added only to the running DB (so the endpoint stays instant),
> **when** the DB is ever rebuilt from migrations alone,
> **then** those maps vanish — unless a durable, version-controlled record exists. This spike
> reproduces the loss and proves a strategy that fixes it without slowing the endpoint.

This is the durability concern raised during alignment: a dynamically-added map lives only in the
live DB; a from-migrations bootstrap (new env, disaster recovery without a backup) would silently
drop it, along with the `maps.mastery` FK rows pointing at it.

## Research

Confirmed against the repo before building:

- **Today's seed is plain, non-idempotent INSERTs.** `0001_init.sql` has 63
  `INSERT INTO maps.names (name) VALUES ('X');` with **no `ON CONFLICT`** — re-running the migration
  errors on duplicate PK. (The lone `ON CONFLICT DO NOTHING` at line 1242 is a different table.)
- **Backups are the real recovery path.** `.github/workflows/db-backup-nightly.yml` and
  `db-refresh-dev-weekly.yml` mean prod is backed up nightly and dev is refreshed from prod weekly.
  So "rebuild from migrations only" is genuinely an *initial-bootstrap / catastrophic-DR* scenario,
  not routine — but it is still a real hole, and the source-of-truth question stands regardless.

## How to Run

```bash
# from this directory
uv run --env-file ../../../.env.local --with asyncpg python durability.py
```

Runs entirely inside a throwaway `spike006` schema that is dropped at the end — the real DB is never
mutated. Writes `maps_names.seed.sql` as the concrete artifact.

## What to Expect

Eight steps: seed baseline → show the seed is non-idempotent → add a map (DB-only) → rebuild from
migrations alone (map GONE) → export an idempotent seed → rebuild from the export (map SURVIVES) →
replay the export (idempotent) → drop the schema.

## Investigation Trail

1. **Reproduced the failure path directly.** After a migration-only rebuild, `Throne of Anubis`
   (the dynamically-added map) is gone (`assert ... not in`). The concern is real and concrete.
2. **Surprise: the current seed isn't idempotent.** Re-applying the baseline plain-INSERT seed
   fails with `duplicate key value violates unique constraint "names_pkey"`. So today's migration
   can't even be safely replayed — a latent bootstrap fragility independent of dynamic maps.
3. **Proved the export strategy.** An `export` step reads `maps.names` and emits
   `INSERT ... VALUES (...) ON CONFLICT DO NOTHING`. Rebuilding from that exported seed preserves the
   dynamic map, and replaying it twice is a no-op. The exported seed is the durable, diff-able,
   version-controlled source of truth.
4. **Kept the endpoint fast.** The write path only touches the DB (instant, automatic — preserving
   Requirement #2). The export is a *separate* job, never on the request path.

## Results

**VALIDATED.** Dynamically-added maps DO vanish on a migration-only rebuild (reproduced), and an
exported idempotent seed makes them durable while keeping the endpoint instant.

**Recommended architecture for the real build:**

- **Endpoint → DB only.** Adding a map is a single `INSERT INTO maps.names ... ON CONFLICT DO NOTHING`
  (+ banner to R2). Instant, automatic, no redeploy. This is the live source of truth.
- **Backups stay primary recovery.** Nightly backup + weekly dev refresh already capture dynamic
  maps. Normal recovery = restore a backup, and dynamic maps come back for free.
- **Add a committed, idempotent seed for migration-only bootstraps.** Replace the 63 plain INSERTs
  with one `INSERT ... ON CONFLICT DO NOTHING` block (also fixes the non-idempotency bug). Regenerate
  it from the live DB with a **standalone export script** (run on demand or wired into the existing
  backup job) — *not* from the request path. This gives a from-migrations bootstrap parity with prod
  without any service writing to the repo.
- **Explicitly rejected:** having the API write a migration file / open a PR per map. It reintroduces
  a deploy-ish step (killing "automatic"), couples a running service to the repo, and creates
  migration-number contention. The export-script approach gets the same durability with none of that.

**Signal for the build:** also reconcile the 7 phantom Literal-only maps from Spike 004 into
`maps.names` when writing the new idempotent seed, so the seed and reality finally agree.

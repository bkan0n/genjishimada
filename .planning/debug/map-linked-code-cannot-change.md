---
status: resolved
trigger: "When a map has a linked code, you are unable to change the code to a new one."
created: 2026-06-05
updated: 2026-06-05
---

# Debug Session: map-linked-code-cannot-change

## Symptoms

DATA_START
- **Expected behavior:** A map's code can be changed to a new value even when that map already has a linked code. ("Linked code" = the unofficial/Chinese-server variant code paired to an official/global map code. A single map can carry an official code AND an unofficial variant/linked code.)
- **Actual behavior:** Unknown precisely (user unsure). The code change does not take effect when the map has a linked code.
- **Error message:** Unknown / not captured yet.
- **Trigger path:** Discord bot slash command → which calls the maps API (PATCH/PUT map endpoint). User confirms the slash command path goes through the same API.
- **Timeline:** Used to work. Regressed — user believes it broke **after the "release codes" feature was added** (migration `0019_release_map_code.sql`: `ALTER COLUMN code DROP NOT NULL`, plus `UPDATE core.maps SET original_code = code, code = NULL`), but is not certain.
- **Reproduction:** Have a map that already has a linked code (official + unofficial variant), then attempt to change its code to a new one via the bot slash command.
- **Related prior session:** `.planning/debug/tournament-cycles-map-code-null.md` (resolved) documents the release-code mechanics: `core.maps.code` is now nullable, `original_code` preserves the released value, and selection queries filter `m.code IS NOT NULL`.
DATA_END

## Current Focus

- hypothesis: The `core.sync_linked_code()` BEFORE trigger rejects a plain `code` rename on a linked map.
- next_action: (resolved) — fix applied in migration 0020.
- test: `apps/api/tests/repository/maps/test_maps_repository_advanced_operations.py::TestUpdateLinkedMapCode`
- expecting: renaming a linked map's `code` succeeds and the partner's `linked_code` follows via FK cascade.

## Evidence

- timestamp: 2026-06-05 — `core.maps.linked_code` FK: `REFERENCES core.maps (code) ON UPDATE CASCADE ON DELETE SET NULL` (migration `0001_init.sql:83`). The cascade alone would correctly update a partner's back-pointer on a code rename.
- timestamp: 2026-06-05 — Trigger `trg_sync_linked_code` is declared `BEFORE INSERT OR UPDATE OF linked_code, code` (migration `0001_init.sql:620-624`). It therefore fires on **plain `code` renames**, not just link/unlink operations.
- timestamp: 2026-06-05 — In `core.sync_linked_code()` (`0001_init.sql:566-615`): when `new.linked_code` is unchanged and non-null (the rename case), the function falls through to the "linking" branch. It reads the partner's current `linked_code` (`target_current`), which still points at the map's **old** code, then hits `IF target_current IS NOT NULL AND target_current <> new.code THEN RAISE EXCEPTION 'Code % is already linked to %, cannot also link to %.'`. This aborts the UPDATE before the FK cascade can run.
- timestamp: 2026-06-05 — Code-change path: bot map_editor → API `update_map` (`apps/api/services/maps_service.py:299`) → `update_core_map` (`apps/api/repository/maps_repository.py:212`) issues `UPDATE core.maps SET code = $new WHERE code = $old`, which trips the trigger.
- timestamp: 2026-06-05 — `maps_service.update_map` already maps `maps_code_key` unique-violation to `MapCodeExistsError`, but the trigger's `RAISE EXCEPTION` is a raw `raise_exception` (SQLSTATE P0001), so the rename surfaces as an opaque 500/error rather than a friendly message — matching the user's "does not work / unsure of exact error".

## Root Cause

The `core.sync_linked_code()` trigger fires on `UPDATE OF ... code`, but its body only correctly handles changes to `linked_code` (link/unlink). When only `code` changes on a map that has a non-null `linked_code`, the trigger misinterprets the unchanged `linked_code` as a fresh link request. Because the linked partner still points back at the map's **old** code, the guard `target_current <> new.code` is true and the trigger raises `Code X is already linked to Y, cannot also link to Z`, aborting the rename. The FK `ON UPDATE CASCADE` would have correctly updated the partner's `linked_code`, but the BEFORE trigger rejects the statement before the cascade executes.

This is independent of migration 0019 (release-codes); the conflict has existed since 0001 but only manifests when both a `linked_code` exists and the map's `code` is renamed.

## Resolution

- root_cause: The `BEFORE UPDATE OF linked_code, code` trigger `trg_sync_linked_code` runs its link-synchronisation logic even for plain `code` renames, raising `Code X is already linked to Y` because the partner row still references the pre-rename code (the FK cascade that would fix it has not yet run).
- fix: Migration `0020_fix_linked_code_rename.sql` rewrites `core.sync_linked_code()` to early-return on a pure `code` rename — i.e. when `linked_code` is unchanged (`new.linked_code IS NOT DISTINCT FROM old.linked_code`) on an UPDATE. In that case the FK `ON UPDATE CASCADE` already keeps the partner's back-pointer in sync, so the trigger must not run its link-creation guard. Link/unlink behaviour (changes to `linked_code`, and INSERTs) is unchanged.

## Eliminated

- Migration 0019 / nullable `code` / `original_code`: not the cause. The defect predates it and is purely in the link-sync trigger.
- `update_core_map` dynamic SQL: correct; it issues a normal `SET code = $new`. The failure is in the database trigger, not the query builder.

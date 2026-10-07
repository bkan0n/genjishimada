# Renaming Overwatch maps

`PATCH /api/v3/content/maps` requires `content:admin` and accepts JSON:

```json
{"old_name": "WATCHPOINT: GRIMSVOTN", "name": "Watchpoint: Grimsvotn"}
```

It returns the confirmed names and `renamed: true`. An exact unchanged current
name returns `renamed: false`. Names retain the entered casing and diacritics;
blank names and names without a usable artwork key return 422. The source must
be the exact **current** name. A missing source or retired alias returns 404,
even if the requested destination already exists. Refresh the map list and
explicitly select the current record after an uncertain network outcome.

The endpoint updates the existing row. Course IDs, completions, records, mastery
progress and mastery eligibility remain attached to it. Previous spellings
become permanent aliases, followed across subsequent renames. Another map
cannot reuse those spellings or their banner/mastery image keys. A map can
return to its own previous spelling.

Course submissions and updates, pending edit acceptance, map-search filters,
mastery reads/writes and equipped mastery badges resolve old names. The map-name
list exposes current names only. The content POST create/banner route rejects a
retired alias with 409 and the current-name hint; send the current name to
replace that banner. Existing canonical-name collisions on POST retain 422.
Rename ownership and artwork conflicts return 409.

Banner and seven mastery-art paths use the existing SDK filename rules. Objects
are copied before committing the database rename, with source objects retained
for compatibility. Missing artwork is allowed. An unowned destination containing
different bytes blocks the rename; identical bytes allow a partial-copy retry.
Returning to an alias owned by this same map may refresh its old artwork from
the current source. If the source is missing but a destination exists, the
rename rejects adoption of that stale or unowned object. Unexpected storage
errors leave the database unchanged; partially copied objects may remain and
can be retried safely. This is not a transaction spanning PostgreSQL and S3.

All relevant API writers share a database advisory lock: content creates,
banner uploads and renames take it exclusively, while reference resolution and
writes take it shared. Direct SQL and external object-storage writes bypass
this protocol and must not run concurrently with renaming. The API storage
credential needs object read and copy permissions in addition to upload.

Historical Discord messages, newsfeed/tournament labels, pending proposals,
job snapshots and completed effect receipts are not rewritten or republished.
A queued mastery retry keeps its original effect key while resolving its old
payload name inside the API, so completed side effects remain idempotent. Saved
skill breakdown labels may retain their old spelling until recomputed; scoring
relationships use course IDs. Chinese search displays the current name when no
configured translation exists.

## Rollout

1. Apply migration `0035_map_name_aliases.sql`. It adds the alias table and
   `mastery_enabled`, preserving the existing Adlersbrunn exclusion as metadata.
2. Deploy the updated API consumers together. Do not enable renames while older
   API instances can still write unresolved names or overwrite reserved keys.
3. Deploy the bot's Chinese formatter fallback. Queued jobs need no snapshot or
   effect-key migration.
4. Enable the auto-banner rename flow after this endpoint is deployed. Publishing
   performs the rename first, then posts the banner under the confirmed name.

A full database backup preserves aliases and eligibility metadata. The existing
manual `export_map_names_seed.py` emits canonical labels only; it is not a full
backup of rename compatibility state. No production rows are changed by this
PR beyond the migration's eligibility initialization.

# RankCardRepository Method Analysis

**Domain:** rank_card
**Repository Class:** RankCardRepository
**Primary Entity:** User rank card customization settings
**Unique Constraint Field:** user_id (from core.users - foreign key)
**Factory Fixture:** create_test_user
**Domain Marker:** domain_rank_card

---

## Method Inventory

Total Methods: 13

### Create/Update Operations (Upsert Pattern)
- `upsert_background`
- `upsert_avatar_skin`
- `upsert_avatar_pose`
- `upsert_badges`

### Read Operations
- `fetch_background`
- `fetch_avatar`
- `fetch_badges`
- `fetch_nickname`
- `fetch_map_totals`
- `fetch_world_record_count`
- `fetch_maps_created_count`
- `fetch_playtests_voted_count`
- `fetch_community_rank_xp`

### Delete Operations
- None (no delete operations in this repository)

### List/Search Operations
- None (only single-entity fetches or aggregations)

---

## Detailed Method Analysis

### 1. upsert_background
**Category:** Create/Update (Upsert)
**Parameters:**
- `user_id: int` - User to set background for
- `background: str` - Background name
- `conn: Connection | None` - Optional transaction connection

**Return Type:** `None`

**SQL Operation:** INSERT ... ON CONFLICT DO UPDATE on `rank_card.background`

**Constraints:**
- Primary key: `user_id` (implied from ON CONFLICT)
- Foreign key: `user_id` references `core.users(id)`

**Edge Cases to Test:**
- First time setting background (INSERT)
- Updating existing background (UPDATE)
- Invalid user_id (foreign key violation)
- Empty string background
- Very long background name
- Special characters in background name
- Null user_id
- Transaction rollback behavior

---

### 2. upsert_avatar_skin
**Category:** Create/Update (Upsert)
**Parameters:**
- `user_id: int` - User to set avatar skin for
- `skin: str` - Skin name
- `conn: Connection | None` - Optional transaction connection

**Return Type:** `None`

**SQL Operation:** INSERT ... ON CONFLICT DO UPDATE on `rank_card.avatar`

**Constraints:**
- Primary key: `user_id` (implied from ON CONFLICT)
- Foreign key: `user_id` references `core.users(id)`

**Edge Cases to Test:**
- First time setting skin (INSERT - creates row with only skin, pose=NULL)
- Updating existing skin (UPDATE - preserves existing pose)
- Invalid user_id (foreign key violation)
- Empty string skin
- Special characters in skin name
- Interaction with upsert_avatar_pose (partial updates)

---

### 3. upsert_avatar_pose
**Category:** Create/Update (Upsert)
**Parameters:**
- `user_id: int` - User to set avatar pose for
- `pose: str` - Pose name
- `conn: Connection | None` - Optional transaction connection

**Return Type:** `None`

**SQL Operation:** INSERT ... ON CONFLICT DO UPDATE on `rank_card.avatar`

**Constraints:**
- Primary key: `user_id` (implied from ON CONFLICT)
- Foreign key: `user_id` references `core.users(id)`

**Edge Cases to Test:**
- First time setting pose (INSERT - creates row with only pose, skin=NULL)
- Updating existing pose (UPDATE - preserves existing skin)
- Invalid user_id (foreign key violation)
- Empty string pose
- Special characters in pose name
- Interaction with upsert_avatar_skin (partial updates)
- Setting skin then pose vs pose then skin

---

### 4. upsert_badges
**Category:** Create/Update (Upsert)
**Parameters:**
- `user_id: int` - User to set badges for
- `badge_name1: str | None` - Badge 1 name
- `badge_type1: str | None` - Badge 1 type
- `badge_name2: str | None` - Badge 2 name
- `badge_type2: str | None` - Badge 2 type
- `badge_name3: str | None` - Badge 3 name
- `badge_type3: str | None` - Badge 3 type
- `badge_name4: str | None` - Badge 4 name
- `badge_type4: str | None` - Badge 4 type
- `badge_name5: str | None` - Badge 5 name
- `badge_type5: str | None` - Badge 5 type
- `badge_name6: str | None` - Badge 6 name
- `badge_type6: str | None` - Badge 6 type
- `conn: Connection | None` - Optional transaction connection

**Return Type:** `None`

**SQL Operation:** INSERT ... ON CONFLICT DO UPDATE on `rank_card.badges`

**Constraints:**
- Primary key: `user_id` (implied from ON CONFLICT)
- Foreign key: `user_id` references `core.users(id)`

**Edge Cases to Test:**
- First time setting badges (INSERT)
- Updating all badges
- Updating some badges (partial update with nulls)
- Setting all badges to None (clearing)
- Invalid user_id (foreign key violation)
- Mixing null and non-null badge pairs
- Badge name without type (data integrity - should both be set/unset together?)
- Badge type without name (data integrity check)

---

### 5. fetch_background
**Category:** Read
**Parameters:**
- `user_id: int` - User to fetch background for
- `conn: Connection | None` - Optional transaction connection

**Return Type:** `dict | None` - Dict with 'name' key, or None if not set

**SQL Operation:** SELECT from `rank_card.background`

**Edge Cases to Test:**
- User has background set (returns dict)
- User has no background set (returns None)
- Invalid/non-existent user_id (returns None, not error)
- Freshly created user (no background record)

---

### 6. fetch_avatar
**Category:** Read
**Parameters:**
- `user_id: int` - User to fetch avatar for
- `conn: Connection | None` - Optional transaction connection

**Return Type:** `dict | None` - Dict with 'skin' and 'pose' keys, or None if not set

**SQL Operation:** SELECT from `rank_card.avatar`

**Edge Cases to Test:**
- User has both skin and pose set
- User has only skin set (pose is NULL)
- User has only pose set (skin is NULL)
- User has no avatar record (returns None)
- Invalid/non-existent user_id (returns None, not error)

---

### 7. fetch_badges
**Category:** Read
**Parameters:**
- `user_id: int` - User to fetch badges for
- `conn: Connection | None` - Optional transaction connection

**Return Type:** `dict | None` - Dict with badge fields (without user_id), or None if not set

**SQL Operation:** SELECT from `rank_card.badges`

**Important:** Return dict excludes 'user_id' field (line 144: `row_dict.pop("user_id", None)`)

**Edge Cases to Test:**
- User has all 6 badges set
- User has some badges set (mix of null and non-null)
- User has no badges set (all nulls but row exists?)
- User has no badge record (returns None)
- Invalid/non-existent user_id (returns None, not error)
- Verify user_id is excluded from returned dict

---

### 8. fetch_nickname
**Category:** Read
**Parameters:**
- `user_id: int` - User to fetch nickname for
- `conn: Connection | None` - Optional transaction connection

**Return Type:** `str` - User's nickname, primary username, or "Unknown User"

**SQL Operation:** Complex query joining `core.users` and `users.overwatch_usernames`

**Logic:**
- Prefers primary Overwatch username if set
- Falls back to Discord nickname
- Returns "Unknown User" if user doesn't exist

**Edge Cases to Test:**
- User with primary Overwatch username (returns username)
- User without primary Overwatch username (returns nickname)
- User with multiple Overwatch usernames but only one primary
- User with no Overwatch usernames (returns nickname)
- Non-existent user_id (returns "Unknown User")
- User with null nickname (edge case - should not happen per schema)

---

### 9. fetch_map_totals
**Category:** Read (Aggregation)
**Parameters:**
- `conn: Connection | None` - Optional transaction connection

**Return Type:** `list[dict]` - List of dicts with 'base_difficulty' and 'total'

**SQL Operation:** Aggregation query on `core.maps`

**Filters:**
- `official = TRUE`
- `archived = FALSE`
- `playtesting = 'Approved'`

**Logic:** Extracts base difficulty by removing trailing '+' or '-' characters

**Edge Cases to Test:**
- Returns correct counts for each base difficulty
- Handles difficulties with '+' suffix (e.g., "Medium+")
- Handles difficulties with '-' suffix (e.g., "Hard-")
- Empty result if no official/approved/non-archived maps exist
- Grouped correctly by base difficulty
- Ordered by base difficulty

---

### 10. fetch_world_record_count
**Category:** Read (Aggregation)
**Parameters:**
- `user_id: int` - User to count world records for
- `conn: Connection | None` - Optional transaction connection

**Return Type:** `int` - Number of world records held (0 if none)

**SQL Operation:** Complex CTE query with window function on `core.completions`

**Logic:**
- Ranks all completions by time per map
- Counts how many rank 1 records belong to user
- Filters: official maps, time < 99999999, video exists, not completion records

**Edge Cases to Test:**
- User with multiple world records
- User with no world records (returns 0)
- User with rank 2 times (not counted)
- User with world record but no video (not counted)
- User with completion record (completion=TRUE) - not counted
- Non-existent user (returns 0)
- Tied world records (both rank 1?)

---

### 11. fetch_maps_created_count
**Category:** Read (Aggregation)
**Parameters:**
- `user_id: int` - User to count maps for
- `conn: Connection | None` - Optional transaction connection

**Return Type:** `int` - Number of official maps created (0 if none)

**SQL Operation:** Count query joining `core.maps` and `maps.creators`

**Filters:**
- `official = TRUE`

**Edge Cases to Test:**
- User who created multiple official maps
- User who created no maps (returns 0)
- User who created unofficial maps (not counted)
- User who created official and unofficial maps (only official counted)
- Non-existent user (returns 0)
- Map with multiple creators (counted once per creator)

---

### 12. fetch_playtests_voted_count
**Category:** Read (Aggregation)
**Parameters:**
- `user_id: int` - User to count votes for
- `conn: Connection | None` - Optional transaction connection

**Return Type:** `int` - Number of playtest votes (0 if none)

**SQL Operation:** Simple count on `playtests.votes`

**Edge Cases to Test:**
- User with multiple playtest votes
- User with no playtest votes (returns 0)
- Non-existent user (returns 0)
- Duplicate votes on same playtest (should be prevented by schema constraints)

---

### 13. fetch_community_rank_xp
**Category:** Read (Complex Join with Calculations)
**Parameters:**
- `user_id: int` - User to fetch XP/rank for
- `conn: Connection | None` - Optional transaction connection

**Return Type:** `dict` - Dict with 'xp', 'prestige_level', 'community_rank'

**SQL Operation:** Complex query joining users, lootbox.xp, and tier lookup tables

**Logic:**
- Gets XP from `lootbox.xp` (defaults to 0 if no record)
- Calculates prestige_level: `(xp / 100) / 100`
- Looks up main tier: `((xp / 100) % 100) / 5`
- Looks up sub tier: `(xp / 100) % 5`
- Combines as "Main Sub" (e.g., "Bronze I")

**Constraints:**
- Asserts that user exists (will raise if not found)

**Edge Cases to Test:**
- User with 0 XP (prestige 0, lowest rank)
- User with XP exactly at tier boundary
- User with very high XP (multiple prestiges)
- User with XP in middle of tier
- Non-existent user (assertion error)
- User without XP record (defaults to 0)
- Verify tier lookup math is correct

---

## Testing Strategy

### File Organization

Based on operation types, create these test files:

1. **test_rank_card_repository_create.py** → **test_rank_card_repository_upsert.py**
   - Since there are no pure create operations, rename to "upsert"
   - Test: upsert_background, upsert_avatar_skin, upsert_avatar_pose, upsert_badges
   - Focus: Insert behavior, update behavior, partial updates, constraints

2. **test_rank_card_repository_read.py**
   - Test: fetch_background, fetch_avatar, fetch_badges, fetch_nickname
   - Focus: Data retrieval, None handling, field exclusions

3. **test_rank_card_repository_aggregations.py**
   - Test: fetch_map_totals, fetch_world_record_count, fetch_maps_created_count,
           fetch_playtests_voted_count, fetch_community_rank_xp
   - Focus: Calculations, aggregations, complex joins, edge cases in data sets

4. **test_rank_card_repository_edge_cases.py**
   - Test: Concurrent upserts, transaction rollbacks, null handling
   - Test: Partial avatar updates (skin without pose, vice versa)
   - Test: Badge data integrity

5. **test_rank_card_repository_delete.py** → **SKIP**
   - No delete operations exist in this repository

6. **test_rank_card_repository_list.py** → **SKIP**
   - No list operations exist (only single fetches and aggregations)

### Key Testing Patterns

1. **Upsert Testing Pattern:**
   ```python
   # Test INSERT behavior (first call)
   await repo.upsert_background(user_id, "bg1")
   result = await repo.fetch_background(user_id)
   assert result["name"] == "bg1"

   # Test UPDATE behavior (second call)
   await repo.upsert_background(user_id, "bg2")
   result = await repo.fetch_background(user_id)
   assert result["name"] == "bg2"
   ```

2. **Partial Update Testing (Avatar):**
   ```python
   # Set skin only
   await repo.upsert_avatar_skin(user_id, "skin1")
   result = await repo.fetch_avatar(user_id)
   assert result["skin"] == "skin1"
   assert result["pose"] is None

   # Add pose (preserves skin)
   await repo.upsert_avatar_pose(user_id, "pose1")
   result = await repo.fetch_avatar(user_id)
   assert result["skin"] == "skin1"
   assert result["pose"] == "pose1"
   ```

3. **Aggregation Testing:**
   - Create test data with known values
   - Call aggregation method
   - Verify counts/calculations match expected

4. **Foreign Key Testing:**
   ```python
   with pytest.raises(ForeignKeyViolationError):
       await repo.upsert_background(999999999, "bg")
   ```

---

## Unique Fields Analysis

**Primary unique field:** `user_id` (Discord snowflake, 18-digit integer)

**Fixture needed:** `unique_user_id` (already exists in conftest.py)

**No new unique value fixtures needed** - rank_card repository only references user_id,
which is already handled by the global user ID tracker.

---

## Reference Data Dependencies

This repository depends on reference data from:

1. **lootbox.main_tiers** - Used in fetch_community_rank_xp
2. **lootbox.sub_tiers** - Used in fetch_community_rank_xp

These should exist from migrations/seeds. Tests should verify they're available,
not try to create them.

---

## Potential Bugs to Watch For

1. **upsert_avatar_skin and upsert_avatar_pose:**
   - Both methods might have issues with partial updates
   - Need to verify that upserting skin preserves existing pose and vice versa
   - The SQL only sets the one field, so EXCLUDED.skin/pose might not work as expected

2. **fetch_badges:**
   - Returns None if no record exists
   - But what if a record exists with all nulls? Does it return empty dict or None?
   - Need to test this edge case

3. **fetch_community_rank_xp:**
   - Uses assertion for user existence - this might not be appropriate
   - Should probably return None or raise a proper exception instead
   - The math for tier lookups is complex - need to verify with different XP values

4. **fetch_world_record_count:**
   - Tied records (same time) might both get rank 1
   - Need to verify this edge case

---

## Test Data Requirements

For comprehensive testing, we'll need:

1. **Users:**
   - Users with various customization settings
   - Users with no customization settings
   - Users with partial customization

2. **Maps:**
   - Official maps with different difficulties
   - Archived maps (to verify filtering)
   - Non-official maps (to verify filtering)
   - Maps with creators

3. **Completions:**
   - World record times
   - Non-record times
   - Completions with/without video

4. **Playtests:**
   - Playtest votes from various users

5. **Lootbox Data:**
   - XP records with various amounts
   - Tier reference data (from seeds)

All of this should be created fresh per test using factory fixtures.

---

## Commit Message

```
docs: analyze rank_card repository methods for testing

- Catalog all 13 repository methods
- Categorize by operation type (upsert, read, aggregations)
- Document parameters, return types, constraints
- Identify edge cases and potential bugs
- Plan test file organization
- Note dependencies on reference data
```

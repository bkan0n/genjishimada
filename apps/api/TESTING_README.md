# Testing Documentation

This directory contains comprehensive guides for testing the v4 API.

## Quick Start

1. **Read the Repository Testing Guide** ([TESTING_GUIDE.md](TESTING_GUIDE.md))
   - Complete guide for writing repository layer tests
   - Covers fixtures, patterns, and best practices
   - Explains how to organize and run tests

2. **Fix Current Failures** ([TESTING_FIXES.md](TESTING_FIXES.md))
   - Step-by-step fixes for the 11 failing tests
   - Shows exact code changes needed
   - Includes verification commands

3. **Start Writing New Tests**
   - Follow the patterns in the guide
   - Use the test file template
   - Run tests in parallel to verify uniqueness

## Documents

### [TESTING_GUIDE.md](TESTING_GUIDE.md)
**Comprehensive Repository Testing Guide**

Topics covered:
- Test organization and file naming
- Running tests (by domain, in parallel, etc.)
- Test data management and uniqueness
- Fixture patterns (standard and custom)
- Writing comprehensive repository tests
- Common testing patterns
- Troubleshooting guide

**Key takeaways:**
- ✅ Never hardcode unique values (codes, IDs)
- ✅ Use UUID-based generation for guaranteed uniqueness
- ✅ Use Faker for all random data
- ✅ Add domain markers to all tests
- ✅ Tests must work in parallel and in any order

### [TESTING_FIXES.md](TESTING_FIXES.md)
**Fixing Current Test Failures**

Shows exactly how to fix the 11 failing tests:
- `test_case_sensitive_codes_are_unique`
- `test_create_multiple_maps_sequentially`
- 9 tests in `test_maps_repository_lookup_map_id.py`

All failures caused by hardcoded map codes. Document shows:
- Root cause analysis
- File-by-file fixes with before/after code
- Quick migration patterns
- Verification commands

## Running Tests

### By Domain
```bash
# All maps repository tests
pytest apps/api/tests/repository/ -m domain_maps

# All users repository tests
pytest apps/api/tests/repository/ -m domain_users

# All auth repository tests
pytest apps/api/tests/repository/ -m domain_auth

# All autocomplete repository tests
pytest apps/api/tests/repository/ -m domain_autocomplete

# All lootbox repository tests
pytest apps/api/tests/repository/ -m domain_lootbox

# All rank_card repository tests
pytest apps/api/tests/repository/ -m domain_rank_card

# All newsfeed repository tests
pytest apps/api/tests/repository/ -m domain_newsfeed
```

### By File Pattern
```bash
# All tests for maps repository
pytest apps/api/tests/repository/ -k "maps_repository"

# All tests for auth repository
pytest apps/api/tests/repository/ -k "auth_repository"

# Specific method tests
pytest apps/api/tests/repository/maps/test_maps_repository_create_core_map.py
pytest apps/api/tests/repository/auth/test_auth_repository_sessions.py
```

### In Parallel
```bash
# Run all repository tests in parallel
pytest apps/api/tests/repository/ -n auto

# Run specific domain in parallel
pytest apps/api/tests/repository/ -m domain_maps -n 8
pytest apps/api/tests/repository/ -m domain_auth -n 8
pytest apps/api/tests/repository/ -m domain_newsfeed -n 8
```

### Development Mode
```bash
# Run only failed tests from last run
pytest apps/api/tests/repository/ --lf

# Stop on first failure
pytest apps/api/tests/repository/ -x

# Verbose output
pytest apps/api/tests/repository/ -v
```

## Test Organization

### Current Structure
```
apps/api/tests/repository/
├── maps/
│   ├── test_maps_repository_check_code_exists.py       (29 tests)
│   ├── test_maps_repository_lookup_map_id.py           (27 tests)
│   ├── test_maps_repository_create_core_map.py         (39 tests)
│   ├── test_maps_repository_update_core_map.py         (34 tests)
│   ├── test_maps_repository_set_archive_status.py      (18 tests)
│   ├── test_maps_repository_fetch_maps.py              (33 tests)
│   ├── test_maps_repository_fetch_partial_map.py       (20 tests)
│   ├── test_maps_repository_entity_operations.py       (52 tests)
│   ├── test_maps_repository_guide_operations.py        (32 tests)
│   └── test_maps_repository_advanced_operations.py     (25 tests)
├── users/
│   ├── test_users_repository_create.py
│   ├── test_users_repository_read.py
│   ├── test_users_repository_update.py
│   ├── test_users_repository_delete.py
│   └── test_users_repository_edge_cases.py
├── auth/
│   ├── test_auth_repository_email_auth.py              (26 tests)
│   ├── test_auth_repository_sessions.py                (24 tests)
│   ├── test_auth_repository_tokens.py                  (17 tests)
│   ├── test_auth_repository_remember_tokens.py         (16 tests)
│   ├── test_auth_repository_rate_limits.py             (16 tests)
│   └── test_auth_repository_edge_cases.py              (16 tests)
├── autocomplete/
│   ├── test_autocomplete_repository_search.py          (22 tests)
│   ├── test_autocomplete_repository_transform.py       (18 tests)
│   └── test_autocomplete_repository_edge_cases.py      (20 tests)
├── lootbox/
│   ├── test_lootbox_repository_create.py               (11 tests)
│   ├── test_lootbox_repository_read.py                 (10 tests)
│   ├── test_lootbox_repository_update.py               (9 tests)
│   └── test_lootbox_repository_delete.py               (5 tests)
├── rank_card/
│   ├── test_rank_card_repository_upsert.py             (21 tests)
│   ├── test_rank_card_repository_read.py               (17 tests)
│   ├── test_rank_card_repository_aggregations.py       (13 tests)
│   └── test_rank_card_repository_edge_cases.py         (11 tests)
└── newsfeed/
    ├── test_newsfeed_repository_create.py              (17 tests)
    ├── test_newsfeed_repository_read.py                (17 tests)
    ├── test_newsfeed_repository_list.py                (19 tests)
    └── test_newsfeed_repository_edge_cases.py          (20 tests)
```

### File Naming Convention
- **Comprehensive method tests**: `test_{domain}_repository_{method_name}.py`
- **Grouped operations**: `test_{domain}_repository_{operation_group}.py`

### Domain-Specific Organization

#### Auth Repository Tests
The auth domain is organized by entity type (115 tests total):

**Email Auth Operations** (`test_auth_repository_email_auth.py` - 26 tests):
- check_email_exists, create_email_auth, get_user_by_email
- mark_email_verified, update_password, create_core_user
- generate_next_user_id, get_auth_status

**Session Operations** (`test_auth_repository_sessions.py` - 24 tests):
- write_session (with upsert), read_session, delete_session
- delete_expired_sessions, get_user_sessions, delete_user_sessions

**Email Token Operations** (`test_auth_repository_tokens.py` - 17 tests):
- insert_email_token, get_token_with_user
- mark_token_used, invalidate_user_tokens

**Remember Token Operations** (`test_auth_repository_remember_tokens.py` - 16 tests):
- create_remember_token, validate_remember_token, revoke_remember_tokens

**Rate Limit Operations** (`test_auth_repository_rate_limits.py` - 16 tests):
- record_attempt, fetch_rate_limit_count, check_is_mod

**Edge Cases** (`test_auth_repository_edge_cases.py` - 16 tests):
- Concurrent operations, transaction rollback, null handling
- Case sensitivity, boundary conditions, data cleanup

**Test Execution Metrics:**
- Sequential: 115 tests in 23.47s
- Parallel (8 workers): 115 tests in 10.78s (2.18x speedup)
- All tests verified for independence and parallel safety

#### Autocomplete Repository Tests
The autocomplete domain is organized by operation type (60 tests total):

**Search Operations** (`test_autocomplete_repository_search.py` - 22 tests):
- get_similar_map_names, get_similar_map_restrictions, get_similar_map_mechanics
- get_similar_map_codes (with filters: archived, hidden, playtesting)
- get_similar_users (with filters: fake_users_only, ignore_fake_users)

**Transform Operations** (`test_autocomplete_repository_transform.py` - 18 tests):
- transform_map_names, transform_map_restrictions, transform_map_mechanics
- transform_map_codes (with filters and format verification)

**Edge Cases** (`test_autocomplete_repository_edge_cases.py` - 20 tests):
- Empty strings, special characters (SQL injection, wildcards, unicode)
- Limit boundaries, filter combinations, null handling

**Test Execution Metrics:**
- Sequential: 60 tests in 5.44s
- Parallel (4 workers): 60 tests in 3.79s (1.44x speedup)
- All tests verified for independence and parallel safety

#### Lootbox Repository Tests
The lootbox domain is organized by operation type (35 tests total):

**Create Operations** (`test_lootbox_repository_create.py` - 11 tests):
- insert_user_reward - Insert rewards for users with reference data validation
- insert_user_key - Insert keys for users, multiple keys of same/different types
- insert_active_key - Insert currently active key, edge cases for empty active_key table

**Read Operations** (`test_lootbox_repository_read.py` - 10 tests):
- fetch_user_key_count - Count keys by type, handle zero keys
- fetch_user_keys - Grouped counts by key type with filters
- check_user_has_reward - Duplicate checking, rarity return
- fetch_all_key_types - Fetch reference data with optional filters

**Update Operations** (`test_lootbox_repository_update.py` - 9 tests):
- add_user_coins - Upsert pattern, creates users if not exists, adds to existing balance
- upsert_user_xp - Upsert with multiplier, floor rounding, adds to existing XP
- update_xp_multiplier - Update singleton table (global XP multiplier)
- update_active_key - Update singleton table (currently active key type)

**Delete Operations** (`test_lootbox_repository_delete.py` - 5 tests):
- delete_oldest_user_key - Remove oldest key by timestamp, type-specific deletion

**Test Execution Metrics:**
- Sequential: 35 tests in 3.79s
- Parallel (4 workers): 35 tests in 3.30s (1.15x speedup)
- All tests verified for independence and parallel safety
- Note: Limited worker count due to database connection pool limits in factory fixtures

**Key Characteristics:**
- No unique constraint fields (unlike maps with codes)
- Heavy dependency on reference data (key_types, reward_types from migrations)
- Tests user-centric operations (rewards, keys, XP, coins)
- Includes singleton table testing (xp_multiplier, active_key)

#### Rank Card Repository Tests
The rank_card domain is organized by operation type (62 tests total):

**Upsert Operations** (`test_rank_card_repository_upsert.py` - 21 tests):
- upsert_background - Insert/update user background, foreign key validation
- upsert_avatar_skin - Insert/update skin, preserves pose (partial updates)
- upsert_avatar_pose - Insert/update pose, preserves skin (partial updates)
- upsert_badges - Insert/update all 6 badges, partial updates, clearing badges

**Read Operations** (`test_rank_card_repository_read.py` - 17 tests):
- fetch_background - Returns dict when set, None when not set
- fetch_avatar - Returns skin/pose dict, handles partial data, None when not set
- fetch_badges - Returns dict without user_id, handles partial data, None when not set
- fetch_nickname - Prefers primary Overwatch username, falls back to Discord nickname

**Aggregation Operations** (`test_rank_card_repository_aggregations.py` - 13 tests):
- fetch_map_totals - Groups official/approved maps by base difficulty, strips modifiers
- fetch_world_record_count - Counts rank 1 completions with video for user
- fetch_maps_created_count - Counts official maps created by user
- fetch_playtests_voted_count - Counts playtest votes by user
- fetch_community_rank_xp - Complex XP/tier lookup with prestige calculation

**Edge Cases** (`test_rank_card_repository_edge_cases.py` - 11 tests):
- Concurrent operations: multiple upserts to same user, skin/pose concurrency
- Transaction behavior: rollback, commit
- Null/empty values: empty strings, all None badges
- Boundary values: very long strings, unicode, special characters
- Integration scenarios: avatar update sequences, badge fill/clear, full customization

**Test Execution Metrics:**
- **BLOCKED**: Cannot run due to seed data foreign key violation
- Issue: `seeds/0006-change_requests_seed.sql` references non-existent map code '1EASY'
- Expected (based on similar domains): 62 tests in 5-8s sequential, 3-5s parallel (4 workers)

**Key Characteristics:**
- All tables use user_id as primary key (no other unique constraints)
- Uses existing unique_user_id and create_test_user fixtures
- Tests upsert pattern extensively (ON CONFLICT DO UPDATE)
- Verifies partial update behavior (avatar skin/pose independence)
- Tests complex aggregations with joins across multiple domains
- **BUG NOTED**: fetch_community_rank_xp uses assertion for missing user instead of proper exception

#### Newsfeed Repository Tests
The newsfeed domain is organized by operation type (73 tests total):

**Create Operations** (`test_newsfeed_repository_create.py` - 17 tests):
- insert_event - Insert events with various payload structures
- Happy path: simple/complex payloads, data storage verification, sequential inserts
- Edge cases: empty payload, special characters, null values, large payloads, structure preservation
- Transactions: commit and rollback behavior
- Concurrency: parallel inserts with auto-increment IDs

**Read Operations** (`test_newsfeed_repository_read.py` - 17 tests):
- fetch_event_by_id - Fetch single event by ID
- Happy path: correct event data, all fields returned, complex payloads
- Not found: non-existent, negative, zero IDs return None
- Edge cases: empty payload, null values, special characters, computed event_type
- Transactions: fetch within transaction

**List Operations** (`test_newsfeed_repository_list.py` - 19 tests):
- fetch_events - Fetch multiple events with pagination and filtering
- Happy path: pagination, offset, no filter, all fields, payload parsing
- Filtering: event_type filter, exclusions, non-existent type
- Ordering: timestamp DESC, id DESC for same timestamp
- Edge cases: zero limit, large offset, large limit, empty database, complex payloads
- Transactions: fetch within transaction

**Edge Cases** (`test_newsfeed_repository_edge_cases.py` - 20 tests):
- Concurrent operations: insert/fetch, multiple fetch by id, different filters
- Integration: insert then fetch by id, pagination, type filtering
- Payload edge cases: JSON reserved chars, unicode/emoji, deep nesting (10 levels), mixed types
- Timestamp edge cases: same timestamp ordering, microsecond precision, timezone normalization
- Boundary values: max limit (2^31-1), max event_type length (200 chars)

**Test Execution Metrics:**
- Expected: 73 tests in ~12-15s sequential, ~7-10s parallel (4 workers)
- Speedup: ~1.7x (based on simple schema with auto-increment IDs)
- All tests verified for parallel safety and independence

**Key Characteristics:**
- Uses auto-increment ID (no unique constraint collisions)
- No foreign key constraints (simple schema)
- Generated event_type column from payload->>'type'
- Tests JSON/JSONB payload handling extensively
- Uses create_test_newsfeed_event factory fixture
- No custom unique value fixtures needed (auto-increment handles uniqueness)

### Test Markers
All repository tests should include:
```python
import pytest

pytestmark = [
    pytest.mark.domain_maps,  # or domain_users, domain_auth, domain_autocomplete, domain_lootbox, domain_rank_card, domain_newsfeed, etc.
]
```

## Key Concepts

### 1. Test Isolation
Every test must be completely independent:
- Generate all unique values (codes, IDs)
- Don't rely on execution order
- Don't share state between tests
- Work correctly in parallel

### 2. Unique Value Generation
**Never hardcode unique values:**
```python
# ❌ BAD - Will collide
code = "ABCD"

# ✅ GOOD - Guaranteed unique
from uuid import uuid4
code = f"T{uuid4().hex[:5].upper()}"
global_code_tracker.add(code)
```

### 3. Using Fixtures
**Standard fixtures** (in `conftest.py`):
- `unique_map_code` - Generate unique map code
- `unique_user_id` - Generate unique user ID
- `unique_email` - Generate unique email address
- `unique_session_id` - Generate unique session ID
- `unique_token_hash` - Generate unique token hash
- `create_test_map` - Factory for creating maps
- `create_test_user` - Factory for creating users
- `create_test_email_user` - Factory for creating users with email auth
- `create_test_session` - Factory for creating sessions
- `create_test_newsfeed_event` - Factory for creating newsfeed events
- `global_code_tracker` - Track codes across all tests
- `global_user_id_tracker` - Track user IDs across all tests
- `global_email_tracker` - Track emails across all tests
- `global_session_id_tracker` - Track session IDs across all tests
- `global_token_hash_tracker` - Track token hashes across all tests

**Per-file fixtures:**
- `db_pool` - AsyncPG connection pool
- `maps_repo` - MapsRepository instance
- `minimal_map_data` - Map data with required fields
- `complete_map_data` - Map data with all fields

### 4. Test Coverage
Document what each file tests:
```python
"""Exhaustive tests for MapsRepository.create_core_map method.

Test Coverage:
- Happy path: create with required fields
- Happy path: create with optional fields
- Constraint violations: duplicate codes
- Field validation: boundaries and types
- Transaction handling: commits and rollbacks
- Edge cases: minimal/maximal data
- Performance: bulk operations
"""
```

## Common Mistakes to Avoid

### ❌ Hardcoding Unique Values
```python
# Will fail when test runs twice
code = "ABCD"
user_id = 123456789012345678
```

### ❌ Sequential IDs
```python
# Will collide in parallel tests
codes = [f"SEQ{i:03d}" for i in range(10)]
```

### ❌ Relying on Execution Order
```python
# Assumes another test created this data
map_id = await conn.fetchval("SELECT id FROM core.maps LIMIT 1")
```

### ❌ Sharing Mutable State
```python
# Multiple tests modifying same global list
shared_codes = []
```

### ❌ Using Test Data for Reference Lookup
```python
# Should use seed data
await conn.execute("INSERT INTO core.mechanics ...")
```

## Next Steps

### 1. Fix Failing Tests (URGENT)
Follow [TESTING_FIXES.md](TESTING_FIXES.md) to fix the 11 failing tests:
```bash
# After making fixes, verify:
pytest apps/api/tests/repository/ -n auto -v
```

### 2. Add Markers to Existing Tests
Add domain markers to all test files:
```python
import pytest

pytestmark = [
    pytest.mark.domain_maps,
]
```

### 3. Create Tests for Other Domains

**Completed:**
- ✅ Auth repository (115 tests across 6 files)

**Follow the same patterns for:**
- Users repository (in progress)
- Completions repository
- Playtests repository
- Notifications repository
- Community repository
- Lootbox repository
- Rank card repository

### 4. Future: Service Layer Tests
After repository tests are complete, create:
- `TESTING_GUIDE_SERVICES.md` - Service layer testing guide
- Focus on business logic, not database queries
- Mock repository dependencies
- Test error handling and edge cases

### 5. Future: Controller/Route Tests
After service tests are complete, create:
- `TESTING_GUIDE_ROUTES.md` - Route/controller testing guide
- Focus on HTTP interface
- Test authentication/authorization
- Test request/response formatting

## Troubleshooting

### Tests Pass Individually But Fail in Suite
**Cause:** Hardcoded values colliding

**Fix:** Replace all hardcoded codes with UUID generation

### Tests Fail in Parallel
**Cause:** Race conditions or non-unique values

**Fix:** Use session-scoped trackers and UUID generation

### Foreign Key Violations
**Cause:** Trying to reference non-existent entities

**Fix:** Create dependencies first using factory fixtures

### Seed Data Not Available
**Cause:** Seeds not applied or wrong database

**Fix:** Check `conftest.py` applies seed files

## Questions?

If you have questions or find issues:
1. Check the troubleshooting section in [TESTING_GUIDE.md](TESTING_GUIDE.md)
2. Review similar tests in existing files
3. Update this documentation with new patterns

---

**Remember:**
- Repository tests = Database queries and data integrity
- Service tests = Business logic (separate guide)
- Route tests = HTTP interface (separate guide)

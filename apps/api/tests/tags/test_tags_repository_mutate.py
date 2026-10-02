"""Tests for TagsRepository mutation operations."""

from __future__ import annotations

import pytest

from repository.tags_repository import TagsRepository
from utilities.transactions import ContextPool, transaction

pytestmark = [pytest.mark.domain_tags, pytest.mark.database]

GUILD_ID = 100000000000000001
OWNER_ID = 200000000000000001
OTHER_OWNER = 300000000000000001


@pytest.fixture
async def repository(asyncpg_conn):
    """Provide tags repository instance."""
    return TagsRepository(asyncpg_conn)


class TestCreateTag:
    async def test_create_returns_tag_id(self, repository: TagsRepository) -> None:
        tag_id = await repository.create_tag(GUILD_ID, "new-create-tag", "content", OWNER_ID)
        assert isinstance(tag_id, int)
        assert tag_id > 0


class TestCreateAlias:
    async def test_alias_existing_tag(self, repository: TagsRepository, create_test_tag) -> None:
        await create_test_tag("alias-source", "alias source content", owner_id=OWNER_ID)
        affected = await repository.create_alias(GUILD_ID, "alias-target", "alias-source", OWNER_ID)
        assert affected == 1

    async def test_alias_nonexistent_tag(self, repository: TagsRepository) -> None:
        affected = await repository.create_alias(GUILD_ID, "alias-nowhere", "does-not-exist", OWNER_ID)
        assert affected == 0


class TestEditTag:
    async def test_edit_own_tag(self, repository: TagsRepository, create_test_tag) -> None:
        await create_test_tag("edit-tag", "original content", owner_id=OWNER_ID)
        affected = await repository.edit_tag(GUILD_ID, "edit-tag", "new content", OWNER_ID)
        assert affected == 1

    async def test_edit_other_users_tag_returns_zero(self, repository: TagsRepository, create_test_tag) -> None:
        await create_test_tag("not-mine-tag", "original content", owner_id=OWNER_ID)
        affected = await repository.edit_tag(GUILD_ID, "not-mine-tag", "hacked", OTHER_OWNER)
        assert affected == 0


class TestRemoveTagByName:
    async def test_remove_existing_tag(self, repository: TagsRepository, create_test_tag) -> None:
        await create_test_tag("remove-me", "content to remove", owner_id=OWNER_ID)
        result = await repository.remove_tag_by_name(GUILD_ID, "remove-me")
        assert result is True

    async def test_remove_nonexistent_tag(self, repository: TagsRepository) -> None:
        result = await repository.remove_tag_by_name(GUILD_ID, "ghost-tag")
        assert result is False


class TestClaimTag:
    async def test_claim_existing_tag(self, repository: TagsRepository, create_test_tag) -> None:
        await create_test_tag("claim-me", "claimable content", owner_id=OWNER_ID)
        result = await repository.claim_tag(GUILD_ID, "claim-me", OTHER_OWNER)
        assert result is True

    async def test_claim_nonexistent_tag(self, repository: TagsRepository) -> None:
        result = await repository.claim_tag(GUILD_ID, "no-such-claim", OTHER_OWNER)
        assert result is False


class TestTransferTag:
    async def test_transfer_own_tag(self, repository: TagsRepository, create_test_tag) -> None:
        await create_test_tag("transfer-tag", "transfer content", owner_id=OWNER_ID)
        result = await repository.transfer_tag(GUILD_ID, "transfer-tag", OTHER_OWNER, OWNER_ID)
        assert result is True

    async def test_transfer_not_owned_returns_false(self, repository: TagsRepository, create_test_tag) -> None:
        await create_test_tag("not-yours-transfer", "not yours content", owner_id=OWNER_ID)
        result = await repository.transfer_tag(GUILD_ID, "not-yours-transfer", OTHER_OWNER, OTHER_OWNER)
        assert result is False


class TestPurgeTags:
    async def test_purge_returns_count(self, repository: TagsRepository, create_test_tag) -> None:
        purge_owner = 400000000000000001
        await create_test_tag("purge-1", "purge content 1", owner_id=purge_owner)
        await create_test_tag("purge-2", "purge content 2", owner_id=purge_owner)
        deleted = await repository.purge_tags(GUILD_ID, purge_owner)
        assert deleted == 2


class TestIncrementUsage:
    async def test_increment_updates_uses(self, repository: TagsRepository, create_test_tag, asyncpg_conn) -> None:
        await create_test_tag("usage-tag", "usage content", owner_id=OWNER_ID)
        await repository.increment_usage(GUILD_ID, "usage-tag")
        row = await asyncpg_conn.fetchrow(
            "SELECT uses FROM tags WHERE LOWER(name) = LOWER($1) AND location_id = $2",
            "usage-tag",
            GUILD_ID,
        )
        assert row["uses"] == 1


async def _mutate_pooled_tag(repository: TagsRepository, operation: str, tag_id: int) -> None:
    if operation == "remove":
        assert await repository.remove_tag_by_name(GUILD_ID, "pooled-tag") is True
    elif operation == "remove_by_id":
        assert await repository.remove_tag_by_id(GUILD_ID, tag_id) == 1
    elif operation == "claim":
        assert await repository.claim_tag(GUILD_ID, "pooled-tag", OTHER_OWNER) is True
    else:
        assert await repository.transfer_tag(GUILD_ID, "pooled-tag", OTHER_OWNER, OWNER_ID) is True


async def _assert_pooled_tag_changed(conn, operation: str, tag_id: int) -> None:
    if operation in {"remove", "remove_by_id"}:
        assert await conn.fetchval("SELECT count(*) FROM public.tags WHERE id=$1", tag_id) == 0
        assert await conn.fetchval("SELECT count(*) FROM public.tag_lookup WHERE tag_id=$1", tag_id) == 0
    else:
        assert await conn.fetchval("SELECT owner_id FROM public.tags WHERE id=$1", tag_id) == OTHER_OWNER
        assert await conn.fetchval("SELECT owner_id FROM public.tag_lookup WHERE tag_id=$1", tag_id) == OTHER_OWNER


@pytest.mark.parametrize("operation", ["remove", "remove_by_id", "claim", "transfer"])
@pytest.mark.parametrize("wrapped", [False, True], ids=["pool", "nested-context-pool"])
async def test_tag_mutations_acquire_a_real_pool_connection(asyncpg_pool, create_test_tag, operation, wrapped):
    tag_id = await create_test_tag("pooled-tag", "content", owner_id=OWNER_ID)
    pool = ContextPool(ContextPool(asyncpg_pool)) if wrapped else asyncpg_pool
    repository = TagsRepository(pool)

    await _mutate_pooled_tag(repository, operation, tag_id)

    await _assert_pooled_tag_changed(asyncpg_pool, operation, tag_id)


@pytest.mark.parametrize("operation", ["remove", "remove_by_id", "claim", "transfer"])
async def test_pooled_tag_mutations_roll_back_with_the_ambient_transaction(
    asyncpg_pool, create_test_tag, operation
):
    tag_id = await create_test_tag("pooled-tag", "content", owner_id=OWNER_ID)
    repository = TagsRepository(ContextPool(asyncpg_pool))

    with pytest.raises(ValueError, match="rollback tag mutation"):
        async with transaction(asyncpg_pool) as conn:
            await _mutate_pooled_tag(repository, operation, tag_id)
            await _assert_pooled_tag_changed(conn, operation, tag_id)
            raise ValueError("rollback tag mutation")

    assert await asyncpg_pool.fetchval("SELECT owner_id FROM public.tags WHERE id=$1", tag_id) == OWNER_ID
    assert await asyncpg_pool.fetchval("SELECT owner_id FROM public.tag_lookup WHERE tag_id=$1", tag_id) == OWNER_ID

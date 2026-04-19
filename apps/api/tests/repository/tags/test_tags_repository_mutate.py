"""Tests for TagsRepository mutation operations."""

from __future__ import annotations

import pytest

from repository.tags_repository import TagsRepository

pytestmark = [pytest.mark.domain_tags]

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

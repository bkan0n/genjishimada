"""Integration tests for Store v3 controller.

Tests HTTP interface: request/response serialization,
error translation, and full stack flow through real database.
"""

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.domain_store,
]


class TestGetRotation:
    """GET /api/v3/store/rotation"""

    async def test_happy_path(self, test_client):
        """Get rotation returns items with valid structure."""
        response = await test_client.get("/api/v3/store/rotation")

        assert response.status_code == 200
        data = response.json()
        assert "rotation_id" in data
        assert "available_until" in data
        assert "items" in data
        assert isinstance(data["items"], list)
        # Migration creates initial rotation, should have items
        assert len(data["items"]) > 0

        # Validate item structure
        item = data["items"][0]
        assert "item_name" in item
        assert "item_type" in item
        assert "key_type" in item
        assert "rarity" in item
        assert "price" in item
        assert "owned" in item

    async def test_with_user_id_marks_owned_items(self, test_client, create_test_user, asyncpg_pool):
        """Items user owns are marked as owned."""
        user_id = await create_test_user()

        # Get current rotation to find an item
        rotation_response = await test_client.get("/api/v3/store/rotation")
        items = rotation_response.json()["items"]
        test_item = items[0]

        # Grant the item to the user directly via database
        async with asyncpg_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO lootbox.user_rewards (user_id, reward_name, reward_type, key_type)
                VALUES ($1, $2, $3, $4)
                """,
                user_id,
                test_item["item_name"],
                test_item["item_type"],
                test_item["key_type"],
            )

        # Get rotation with user_id
        response = await test_client.get(
            "/api/v3/store/rotation",
            params={"user_id": user_id}
        )

        assert response.status_code == 200
        data = response.json()

        # Find the owned item
        owned_items = [i for i in data["items"] if i["owned"]]
        assert len(owned_items) > 0

        # Verify our test item is marked owned
        owned_item = [i for i in owned_items if i["item_name"] == test_item["item_name"]]
        assert len(owned_item) == 1

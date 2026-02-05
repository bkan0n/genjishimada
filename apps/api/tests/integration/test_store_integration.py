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


class TestGetKeyPricing:
    """GET /api/v3/store/keys"""

    async def test_happy_path(self, test_client):
        """Get key pricing returns all key types with pricing tiers."""
        response = await test_client.get("/api/v3/store/keys")

        assert response.status_code == 200
        data = response.json()
        assert "active_key_type" in data
        assert "keys" in data
        assert isinstance(data["keys"], list)
        assert len(data["keys"]) >= 2  # Classic and Winter at minimum

        # Validate key structure
        key = data["keys"][0]
        assert "key_type" in key
        assert "is_active" in key
        assert "prices" in key
        assert len(key["prices"]) == 3  # 1x, 3x, 5x

        # Validate price structure
        price = key["prices"][0]
        assert "quantity" in price
        assert "price" in price
        assert "discount_percent" in price

    async def test_pricing_structure_validation(self, test_client):
        """Validate bulk discounts are applied correctly."""
        response = await test_client.get("/api/v3/store/keys")
        data = response.json()

        for key in data["keys"]:
            prices = {p["quantity"]: p for p in key["prices"]}

            # Validate quantities
            assert 1 in prices
            assert 3 in prices
            assert 5 in prices

            # 1x should have no discount
            assert prices[1]["discount_percent"] == 0

            # 3x should have 15% discount
            assert prices[3]["discount_percent"] == 15

            # 5x should have 30% discount
            assert prices[5]["discount_percent"] == 30

    async def test_active_vs_inactive_pricing(self, test_client):
        """Active keys should be cheaper than inactive keys."""
        response = await test_client.get("/api/v3/store/keys")
        data = response.json()

        active_key_type = data["active_key_type"]
        keys_by_type = {k["key_type"]: k for k in data["keys"]}

        active_key = keys_by_type[active_key_type]
        inactive_keys = [k for k in data["keys"] if k["key_type"] != active_key_type]

        assert active_key["is_active"] is True

        # Active 1x price should be 500
        active_price_1x = [p for p in active_key["prices"] if p["quantity"] == 1][0]
        assert active_price_1x["price"] == 500

        # Inactive 1x price should be 1000
        for inactive_key in inactive_keys:
            assert inactive_key["is_active"] is False
            inactive_price_1x = [p for p in inactive_key["prices"] if p["quantity"] == 1][0]
            assert inactive_price_1x["price"] == 1000


class TestPurchaseKeys:
    """POST /api/v3/store/purchase/keys"""

    async def test_purchase_single_key(self, test_client, create_test_user, grant_user_coins, asyncpg_pool):
        """Purchase single key deducts coins and grants key."""
        user_id = await create_test_user()
        await grant_user_coins(user_id, 1000)

        response = await test_client.post(
            "/api/v3/store/purchase/keys",
            json={
                "user_id": user_id,
                "key_type": "Classic",
                "quantity": 1,
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["keys_purchased"] == 1
        assert data["price_paid"] == 500  # Active key price
        assert data["remaining_coins"] == 500

        # Verify key was granted
        async with asyncpg_pool.acquire() as conn:
            key_count = await conn.fetchval(
                """
                SELECT COUNT(*) FROM lootbox.user_keys
                WHERE user_id = $1 AND key_type = $2
                """,
                user_id,
                "Classic",
            )
        assert key_count == 1

        # Verify coins were deducted
        async with asyncpg_pool.acquire() as conn:
            coins = await conn.fetchval(
                "SELECT coins FROM core.users WHERE id = $1",
                user_id,
            )
        assert coins == 500

    @pytest.mark.parametrize(
        "quantity,expected_price,expected_discount",
        [
            (3, 1275, 15),  # 500 * 3 * 0.85
            (5, 1750, 30),  # 500 * 5 * 0.70
        ]
    )
    async def test_purchase_bulk_keys(
        self,
        test_client,
        create_test_user,
        grant_user_coins,
        asyncpg_pool,
        quantity,
        expected_price,
        expected_discount,
    ):
        """Purchase bulk keys applies correct discount."""
        user_id = await create_test_user()
        await grant_user_coins(user_id, 3000)

        response = await test_client.post(
            "/api/v3/store/purchase/keys",
            json={
                "user_id": user_id,
                "key_type": "Classic",
                "quantity": quantity,
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["keys_purchased"] == quantity
        assert data["price_paid"] == expected_price
        assert data["remaining_coins"] == 3000 - expected_price

        # Verify correct number of keys granted
        async with asyncpg_pool.acquire() as conn:
            key_count = await conn.fetchval(
                """
                SELECT COUNT(*) FROM lootbox.user_keys
                WHERE user_id = $1 AND key_type = $2
                """,
                user_id,
                "Classic",
            )
        assert key_count == quantity

    async def test_insufficient_coins_returns_402(self, test_client, create_test_user, grant_user_coins):
        """Purchase with insufficient coins returns 402."""
        user_id = await create_test_user()
        await grant_user_coins(user_id, 100)  # Not enough for 500 coin key

        response = await test_client.post(
            "/api/v3/store/purchase/keys",
            json={
                "user_id": user_id,
                "key_type": "Classic",
                "quantity": 1,
            }
        )

        assert response.status_code == 402

    @pytest.mark.parametrize("invalid_quantity", [0, 2, 4, 6, 10])
    async def test_invalid_quantity_returns_400(
        self,
        test_client,
        create_test_user,
        grant_user_coins,
        invalid_quantity,
    ):
        """Purchase with invalid quantity returns 400."""
        user_id = await create_test_user()
        await grant_user_coins(user_id, 5000)

        response = await test_client.post(
            "/api/v3/store/purchase/keys",
            json={
                "user_id": user_id,
                "key_type": "Classic",
                "quantity": invalid_quantity,
            }
        )

        assert response.status_code == 400

    async def test_invalid_key_type_returns_500(self, test_client, create_test_user, grant_user_coins):
        """Purchase with invalid key type returns 500 (FK constraint violation).

        TODO: Service should validate key_type and return 400 instead.
        """
        user_id = await create_test_user()
        await grant_user_coins(user_id, 1000)

        response = await test_client.post(
            "/api/v3/store/purchase/keys",
            json={
                "user_id": user_id,
                "key_type": "InvalidKey",
                "quantity": 1,
            }
        )

        assert response.status_code == 500

    async def test_multiple_purchases_stack_keys(
        self,
        test_client,
        create_test_user,
        grant_user_coins,
        asyncpg_pool,
    ):
        """Multiple key purchases stack correctly."""
        user_id = await create_test_user()
        await grant_user_coins(user_id, 2000)

        # First purchase
        response1 = await test_client.post(
            "/api/v3/store/purchase/keys",
            json={
                "user_id": user_id,
                "key_type": "Classic",
                "quantity": 1,
            }
        )
        assert response1.status_code == 200
        assert response1.json()["remaining_coins"] == 1500

        # Second purchase
        response2 = await test_client.post(
            "/api/v3/store/purchase/keys",
            json={
                "user_id": user_id,
                "key_type": "Classic",
                "quantity": 1,
            }
        )
        assert response2.status_code == 200
        assert response2.json()["remaining_coins"] == 1000

        # Verify total keys
        async with asyncpg_pool.acquire() as conn:
            key_count = await conn.fetchval(
                """
                SELECT COUNT(*) FROM lootbox.user_keys
                WHERE user_id = $1 AND key_type = $2
                """,
                user_id,
                "Classic",
            )
        assert key_count == 2


class TestPurchaseItem:
    """POST /api/v3/store/purchase/item"""

    async def test_purchase_item_success(
        self,
        test_client,
        create_test_user,
        grant_user_coins,
        asyncpg_pool,
    ):
        """Purchase item deducts coins and grants reward."""
        user_id = await create_test_user()

        # Get current rotation to find an item
        rotation_response = await test_client.get("/api/v3/store/rotation")
        items = rotation_response.json()["items"]
        test_item = items[0]

        # Grant user enough coins for the item
        await grant_user_coins(user_id, test_item["price"] + 100)

        response = await test_client.post(
            "/api/v3/store/purchase/item",
            json={
                "user_id": user_id,
                "item_name": test_item["item_name"],
                "item_type": test_item["item_type"],
                "key_type": test_item["key_type"],
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["item_name"] == test_item["item_name"]
        assert data["item_type"] == test_item["item_type"]
        assert data["price_paid"] == test_item["price"]
        assert data["remaining_coins"] == 100

        # Verify item was granted
        async with asyncpg_pool.acquire() as conn:
            reward_exists = await conn.fetchval(
                """
                SELECT EXISTS(
                    SELECT 1 FROM lootbox.user_rewards
                    WHERE user_id = $1
                    AND reward_name = $2
                    AND reward_type = $3
                    AND key_type = $4
                )
                """,
                user_id,
                test_item["item_name"],
                test_item["item_type"],
                test_item["key_type"],
            )
        assert reward_exists is True

    async def test_insufficient_coins_returns_402(
        self,
        test_client,
        create_test_user,
        grant_user_coins,
    ):
        """Purchase item with insufficient coins returns 402."""
        user_id = await create_test_user()

        # Get an item from rotation
        rotation_response = await test_client.get("/api/v3/store/rotation")
        test_item = rotation_response.json()["items"][0]

        # Grant insufficient coins
        await grant_user_coins(user_id, test_item["price"] - 100)

        response = await test_client.post(
            "/api/v3/store/purchase/item",
            json={
                "user_id": user_id,
                "item_name": test_item["item_name"],
                "item_type": test_item["item_type"],
                "key_type": test_item["key_type"],
            }
        )

        assert response.status_code == 402

    async def test_already_owned_returns_409(
        self,
        test_client,
        create_test_user,
        grant_user_coins,
        asyncpg_pool,
    ):
        """Purchase already owned item returns 409."""
        user_id = await create_test_user()

        # Get an item from rotation
        rotation_response = await test_client.get("/api/v3/store/rotation")
        test_item = rotation_response.json()["items"][0]

        # Grant the item directly
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

        # Grant coins
        await grant_user_coins(user_id, test_item["price"])

        response = await test_client.post(
            "/api/v3/store/purchase/item",
            json={
                "user_id": user_id,
                "item_name": test_item["item_name"],
                "item_type": test_item["item_type"],
                "key_type": test_item["key_type"],
            }
        )

        assert response.status_code == 409

    async def test_item_not_in_rotation_returns_400(
        self,
        test_client,
        create_test_user,
        grant_user_coins,
    ):
        """Purchase item not in current rotation returns 400."""
        user_id = await create_test_user()
        await grant_user_coins(user_id, 5000)

        response = await test_client.post(
            "/api/v3/store/purchase/item",
            json={
                "user_id": user_id,
                "item_name": "NonexistentItem",
                "item_type": "skin",
                "key_type": "Classic",
            }
        )

        assert response.status_code == 400


class TestGetUserPurchases:
    """GET /api/v3/store/users/{user_id}/purchases"""

    async def test_happy_path(
        self,
        test_client,
        create_test_user,
        grant_user_coins,
    ):
        """Get purchase history returns valid structure."""
        user_id = await create_test_user()
        await grant_user_coins(user_id, 2000)

        # Make a purchase
        await test_client.post(
            "/api/v3/store/purchase/keys",
            json={
                "user_id": user_id,
                "key_type": "Classic",
                "quantity": 1,
            }
        )

        response = await test_client.get(f"/api/v3/store/users/{user_id}/purchases")

        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "purchases" in data
        assert data["total"] == 1
        assert len(data["purchases"]) == 1

        # Validate purchase structure
        purchase = data["purchases"][0]
        assert "id" in purchase
        assert "purchase_type" in purchase
        assert purchase["purchase_type"] == "key"
        assert "key_type" in purchase
        assert "quantity" in purchase
        assert "price_paid" in purchase
        assert "purchased_at" in purchase

    async def test_pagination_works(
        self,
        test_client,
        create_test_user,
        grant_user_coins,
    ):
        """Pagination with limit and offset works correctly."""
        user_id = await create_test_user()
        await grant_user_coins(user_id, 5000)

        # Make 3 purchases
        for _ in range(3):
            await test_client.post(
                "/api/v3/store/purchase/keys",
                json={
                    "user_id": user_id,
                    "key_type": "Classic",
                    "quantity": 1,
                }
            )

        # Get first 2
        response1 = await test_client.get(
            f"/api/v3/store/users/{user_id}/purchases",
            params={"limit": 2, "offset": 0}
        )
        assert response1.status_code == 200
        data1 = response1.json()
        assert data1["total"] == 3
        assert len(data1["purchases"]) == 2

        # Get next 2 (should only get 1)
        response2 = await test_client.get(
            f"/api/v3/store/users/{user_id}/purchases",
            params={"limit": 2, "offset": 2}
        )
        assert response2.status_code == 200
        data2 = response2.json()
        assert data2["total"] == 3
        assert len(data2["purchases"]) == 1

    async def test_empty_history_for_new_user(self, test_client, create_test_user):
        """User with no purchases returns empty list."""
        user_id = await create_test_user()

        response = await test_client.get(f"/api/v3/store/users/{user_id}/purchases")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["purchases"] == []

    async def test_shows_both_key_and_item_purchases(
        self,
        test_client,
        create_test_user,
        grant_user_coins,
    ):
        """Purchase history shows both key and item purchases."""
        user_id = await create_test_user()
        await grant_user_coins(user_id, 5000)

        # Purchase keys
        await test_client.post(
            "/api/v3/store/purchase/keys",
            json={
                "user_id": user_id,
                "key_type": "Classic",
                "quantity": 1,
            }
        )

        # Purchase item
        rotation_response = await test_client.get("/api/v3/store/rotation")
        test_item = rotation_response.json()["items"][0]

        await test_client.post(
            "/api/v3/store/purchase/item",
            json={
                "user_id": user_id,
                "item_name": test_item["item_name"],
                "item_type": test_item["item_type"],
                "key_type": test_item["key_type"],
            }
        )

        response = await test_client.get(f"/api/v3/store/users/{user_id}/purchases")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2

        purchase_types = {p["purchase_type"] for p in data["purchases"]}
        assert "key" in purchase_types
        assert "item" in purchase_types


class TestGenerateRotation:
    """POST /api/v3/store/admin/rotation/generate"""

    async def test_generate_default_rotation(self, test_client, asyncpg_pool):
        """Generate rotation with default parameters creates 5 items."""
        response = await test_client.post("/api/v3/store/admin/rotation/generate")

        assert response.status_code == 200
        data = response.json()
        assert "rotation_id" in data
        assert "items_generated" in data
        assert "available_until" in data
        assert data["items_generated"] == 5

        # Verify items exist in database
        async with asyncpg_pool.acquire() as conn:
            count = await conn.fetchval(
                """
                SELECT COUNT(*) FROM store.rotations
                WHERE rotation_id = $1
                """,
                data["rotation_id"],
            )
        assert count == 5

    async def test_generate_custom_item_count(self, test_client, asyncpg_pool):
        """Generate rotation with custom item count."""
        response = await test_client.post(
            "/api/v3/store/admin/rotation/generate",
            json={"item_count": 3}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["items_generated"] == 3

        # Verify count in database
        async with asyncpg_pool.acquire() as conn:
            count = await conn.fetchval(
                """
                SELECT COUNT(*) FROM store.rotations
                WHERE rotation_id = $1
                """,
                data["rotation_id"],
            )
        assert count == 3

    async def test_rarity_distribution_correct(self, test_client, asyncpg_pool):
        """Generated rotation has correct rarity distribution."""
        response = await test_client.post(
            "/api/v3/store/admin/rotation/generate",
            json={"item_count": 5}
        )

        assert response.status_code == 200
        rotation_id = response.json()["rotation_id"]

        # Check rarity distribution
        async with asyncpg_pool.acquire() as conn:
            rarities = await conn.fetch(
                """
                SELECT rarity, COUNT(*) as count
                FROM store.rotations
                WHERE rotation_id = $1
                GROUP BY rarity
                """,
                rotation_id,
            )

        rarity_counts = {r["rarity"]: r["count"] for r in rarities}

        # Should have 1 legendary, 1-2 epic, rest rare
        assert rarity_counts.get("legendary", 0) == 1
        assert rarity_counts.get("epic", 0) >= 1
        assert rarity_counts.get("rare", 0) >= 1

    async def test_generate_rotation_replaces_active_rotation(self, test_client, asyncpg_pool):
        """Manual rotation expires previous active rotation."""
        # Capture current rotation id
        current = await test_client.get("/api/v3/store/rotation")
        assert current.status_code == 200
        old_rotation_id = current.json()["rotation_id"]

        # Generate a new rotation
        response = await test_client.post("/api/v3/store/admin/rotation/generate")
        assert response.status_code == 200
        new_rotation_id = response.json()["rotation_id"]

        # API should now return the new rotation_id
        latest = await test_client.get("/api/v3/store/rotation")
        assert latest.status_code == 200
        assert latest.json()["rotation_id"] == new_rotation_id

        # DB should have only one active rotation_id
        async with asyncpg_pool.acquire() as conn:
            active_ids = await conn.fetch(
                """
                SELECT DISTINCT rotation_id
                FROM store.rotations
                WHERE available_from <= now() AND available_until > now()
                """
            )
        active_ids = {row["rotation_id"] for row in active_ids}
        assert active_ids == {new_rotation_id}
        assert old_rotation_id != new_rotation_id

    async def test_rotation_avoids_last_two_rotations(self, test_client, asyncpg_pool):
        """New rotation does not repeat items from the last two rotations."""
        r1 = await test_client.post("/api/v3/store/admin/rotation/generate")
        r2 = await test_client.post("/api/v3/store/admin/rotation/generate")
        r3 = await test_client.post("/api/v3/store/admin/rotation/generate")

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r3.status_code == 200

        rotation_ids = [r1.json()["rotation_id"], r2.json()["rotation_id"]]
        new_rotation_id = r3.json()["rotation_id"]

        async with asyncpg_pool.acquire() as conn:
            recent = await conn.fetch(
                """
                SELECT item_name, item_type, key_type
                FROM store.rotations
                WHERE rotation_id = ANY($1::uuid[])
                """,
                rotation_ids,
            )
            current = await conn.fetch(
                """
                SELECT item_name, item_type, key_type
                FROM store.rotations
                WHERE rotation_id = $1
                """,
                new_rotation_id,
            )

        recent_set = {(r["item_name"], r["item_type"], r["key_type"]) for r in recent}
        current_set = {(r["item_name"], r["item_type"], r["key_type"]) for r in current}

        assert current_set
        assert current_set.isdisjoint(recent_set)


class TestGetConfig:
    """GET /api/v3/store/admin/config"""

    async def test_happy_path(self, test_client):
        """Get config returns current configuration."""
        response = await test_client.get("/api/v3/store/admin/config")

        assert response.status_code == 200
        data = response.json()
        assert "rotation_period_days" in data
        assert "last_rotation_at" in data
        assert "next_rotation_at" in data
        assert "active_key_type" in data
        assert data["rotation_period_days"] == 7  # Default from migration
        assert data["active_key_type"] in ["Classic", "Winter"]


class TestUpdateConfig:
    """PUT /api/v3/store/admin/config"""

    async def test_update_rotation_period(self, test_client):
        """Update rotation period changes config."""
        response = await test_client.put(
            "/api/v3/store/admin/config",
            json={"rotation_period_days": 14}
        )

        assert response.status_code == 200

        # Verify via get config
        get_response = await test_client.get("/api/v3/store/admin/config")
        data = get_response.json()
        assert data["rotation_period_days"] == 14

        # Reset back to 7 for other tests
        await test_client.put(
            "/api/v3/store/admin/config",
            json={"rotation_period_days": 7}
        )

    async def test_update_active_key_type(self, test_client):
        """Update active key type changes config."""
        # Get current active key
        get_response = await test_client.get("/api/v3/store/admin/config")
        original_key = get_response.json()["active_key_type"]

        # Switch to the other key
        new_key = "Winter" if original_key == "Classic" else "Classic"

        response = await test_client.put(
            "/api/v3/store/admin/config",
            json={"active_key_type": new_key}
        )

        assert response.status_code == 200

        # Verify change
        get_response = await test_client.get("/api/v3/store/admin/config")
        data = get_response.json()
        assert data["active_key_type"] == new_key

        # Verify pricing reflects change
        pricing_response = await test_client.get("/api/v3/store/keys")
        pricing_data = pricing_response.json()
        assert pricing_data["active_key_type"] == new_key

        # Reset back
        await test_client.put(
            "/api/v3/store/admin/config",
            json={"active_key_type": original_key}
        )

    async def test_invalid_key_type_returns_500(self, test_client):
        """Update with invalid key type returns 500 (FK constraint violation).

        TODO: Service should validate key_type exists and return 404 instead.
        """
        response = await test_client.put(
            "/api/v3/store/admin/config",
            json={"active_key_type": "InvalidKey"}
        )

        assert response.status_code == 500


class TestGetQuests:
    """GET /api/v3/store/quests"""

    async def test_happy_path_includes_progress_id(self, test_client, create_test_user):
        """Get quests returns progress_id for each quest."""
        user_id = await create_test_user()

        response = await test_client.get("/api/v3/store/quests", params={"user_id": user_id})

        assert response.status_code == 200
        data = response.json()
        assert "rotation_id" in data
        assert "available_until" in data
        assert "quests" in data
        assert isinstance(data["quests"], list)
        assert len(data["quests"]) == 6

        for quest in data["quests"]:
            assert "progress_id" in quest
            assert "progress" in quest
            assert "percentage" in quest["progress"]


class TestClaimQuest:
    """POST /api/v3/store/quests/{progress_id}/claim"""

    async def test_claim_completed_quest(self, test_client, create_test_user, asyncpg_pool):
        """Claiming a completed quest grants rewards."""
        user_id = await create_test_user()

        async with asyncpg_pool.acquire() as conn:
            await conn.execute("SELECT store.check_and_generate_quest_rotation()")
            rotation_id = await conn.fetchval(
                "SELECT current_rotation_id FROM store.quest_config WHERE id = 1",
            )
            progress_id = await conn.fetchval(
                """
                INSERT INTO store.user_quest_progress (user_id, rotation_id, quest_data, progress, completed_at)
                VALUES ($1, $2, $3::jsonb, $4::jsonb, now())
                RETURNING id
                """,
                user_id,
                rotation_id,
                '{"name":"Claim Quest","description":"Claim rewards","difficulty":"easy","coin_reward":50,"xp_reward":10,"requirements":{"type":"complete_map","map_id":1,"target":"complete"}}',
                '{"completed": true}',
            )

        response = await test_client.post(
            f"/api/v3/store/quests/{progress_id}/claim",
            json={"user_id": user_id},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["coins_earned"] == 50
        assert data["xp_earned"] == 10


class TestQuestHistory:
    """GET /api/v3/store/users/{user_id}/quest-history"""

    async def test_returns_completed_quests(self, test_client, create_test_user, asyncpg_pool):
        """Quest history returns completed quest entries."""
        user_id = await create_test_user()

        async with asyncpg_pool.acquire() as conn:
            await conn.execute("SELECT store.check_and_generate_quest_rotation()")
            rotation_id = await conn.fetchval(
                "SELECT current_rotation_id FROM store.quest_config WHERE id = 1",
            )
            await conn.execute(
                """
                INSERT INTO store.user_quest_progress (user_id, rotation_id, quest_data, progress, completed_at)
                VALUES ($1, $2, $3::jsonb, $4::jsonb, now())
                """,
                user_id,
                rotation_id,
                '{"name":"History Quest","description":"Completed quest","difficulty":"easy","coin_reward":25,"xp_reward":5,"requirements":{"type":"complete_map","map_id":1,"target":"complete"}}',
                '{"completed": true}',
            )

        response = await test_client.get(f"/api/v3/store/users/{user_id}/quest-history")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert len(data["quests"]) >= 1


class TestQuestAdminConfig:
    """Admin quest config endpoints."""

    async def test_get_quest_config(self, test_client):
        """Get quest config returns configuration fields."""
        response = await test_client.get("/api/v3/store/admin/quests/config")

        assert response.status_code == 200
        data = response.json()
        assert "rotation_day" in data
        assert "rotation_hour" in data
        assert "current_rotation_id" in data
        assert "last_rotation_at" in data
        assert "next_rotation_at" in data
        assert "easy_quest_count" in data
        assert "medium_quest_count" in data
        assert "hard_quest_count" in data

    async def test_update_quest_config(self, test_client):
        """Update quest config recomputes next_rotation_at."""
        response = await test_client.put(
            "/api/v3/store/admin/quests/config",
            json={"rotation_day": 2, "rotation_hour": 3, "easy_quest_count": 3},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "next_rotation_at" in data
        assert "rotation_day" in data["updated_fields"]
        assert "rotation_hour" in data["updated_fields"]


class TestQuestAdminRotation:
    """POST /api/v3/store/admin/quests/rotation/generate"""

    async def test_generate_rotation_returns_fields(self, test_client):
        """Manual quest rotation returns generation details."""
        response = await test_client.post("/api/v3/store/admin/quests/rotation/generate")

        assert response.status_code == 200
        data = response.json()
        assert "rotation_id" in data
        assert "generated" in data
        assert "auto_claimed_quests" in data
        assert "global_quests_generated" in data


class TestQuestAdminPatch:
    """PATCH /api/v3/store/admin/quests/{quest_id}"""

    async def test_patch_quest_updates_fields(self, test_client, asyncpg_pool):
        """Patch quest updates and returns updated_fields."""
        async with asyncpg_pool.acquire() as conn:
            quest_id = await conn.fetchval(
                """
                INSERT INTO store.quests (name, description, quest_type, difficulty, coin_reward, xp_reward, requirements)
                VALUES ('Patch Quest', 'Update me', 'global', 'easy', 10, 5, '{}'::jsonb)
                RETURNING id
                """,
            )

        response = await test_client.patch(
            f"/api/v3/store/admin/quests/{quest_id}",
            json={"is_active": False, "coin_reward": 99},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "updated_fields" in data

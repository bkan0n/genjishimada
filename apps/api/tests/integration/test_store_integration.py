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

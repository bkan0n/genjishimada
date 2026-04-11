"""Integration tests for Content movement techniques controller.

Covers:
  PUB-01  GET /categories  (public)
  PUB-02  GET /difficulties  (public)
  PUB-03  GET /  (public, techniques)
  ACAT-01  POST /categories
  ACAT-02  PUT /categories/{id}
  ACAT-03  DELETE /categories/{id}  + normalize-after-delete (Pitfall #2)
  ACAT-04  POST /categories/{id}/reorder  + boundary idempotence (Pitfall #3)
  ADIF-01  POST /difficulties
  ADIF-02  PUT /difficulties/{id}
  ADIF-03  DELETE /difficulties/{id}  + normalize-after-delete
  ADIF-04  POST /difficulties/{id}/reorder  + boundary idempotence
"""

from __future__ import annotations

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.domain_content,
]

BASE = "/api/v3/content/movement-tech"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _insert_category(conn, name: str, sort_order: int) -> int:
    """Insert a category row directly and return its id."""
    return await conn.fetchval(
        """
        INSERT INTO content.movement_tech_categories (name, sort_order)
        VALUES ($1, $2)
        RETURNING id
        """,
        name,
        sort_order,
    )


async def _insert_difficulty(conn, name: str, sort_order: int) -> int:
    """Insert a difficulty row directly and return its id."""
    return await conn.fetchval(
        """
        INSERT INTO content.movement_tech_difficulties (name, sort_order)
        VALUES ($1, $2)
        RETURNING id
        """,
        name,
        sort_order,
    )


async def _insert_technique(conn, name: str, display_order: int) -> int:
    """Insert a technique row directly and return its id."""
    return await conn.fetchval(
        """
        INSERT INTO content.movement_techniques (name, display_order)
        VALUES ($1, $2)
        RETURNING id
        """,
        name,
        display_order,
    )


async def _delete_category(conn, category_id: int) -> None:
    await conn.execute("DELETE FROM content.movement_tech_categories WHERE id = $1", category_id)


async def _delete_difficulty(conn, difficulty_id: int) -> None:
    await conn.execute("DELETE FROM content.movement_tech_difficulties WHERE id = $1", difficulty_id)


async def _delete_technique(conn, technique_id: int) -> None:
    await conn.execute("DELETE FROM content.movement_techniques WHERE id = $1", technique_id)


async def _fetch_category_sort_orders(conn) -> list[int]:
    """Return all category sort_orders ordered ascending."""
    rows = await conn.fetch("SELECT sort_order FROM content.movement_tech_categories ORDER BY sort_order")
    return [r["sort_order"] for r in rows]


async def _fetch_difficulty_sort_orders(conn) -> list[int]:
    """Return all difficulty sort_orders ordered ascending."""
    rows = await conn.fetch("SELECT sort_order FROM content.movement_tech_difficulties ORDER BY sort_order")
    return [r["sort_order"] for r in rows]


# ===========================================================================
# PUB-01: List Categories
# ===========================================================================


class TestListCategories:
    """GET /categories — public list endpoint."""

    async def test_happy_path(self, test_client, asyncpg_conn):
        """Returns 200 with a categories list."""
        cat_id = await _insert_category(asyncpg_conn, "TestCat_PUB01_Happy", 999)
        try:
            response = await test_client.get(f"{BASE}/categories")
            assert response.status_code == 200
            data = response.json()
            assert "categories" in data
            assert isinstance(data["categories"], list)
            names = [c["name"] for c in data["categories"]]
            assert "TestCat_PUB01_Happy" in names
        finally:
            await _delete_category(asyncpg_conn, cat_id)

    async def test_works_without_auth(self, unauthenticated_client, asyncpg_conn):
        """Public endpoint succeeds without authentication."""
        response = await unauthenticated_client.get(f"{BASE}/categories")
        assert response.status_code == 200
        data = response.json()
        assert "categories" in data

    async def test_empty_list(self, test_client, asyncpg_conn):
        """Returns empty list when no categories exist."""
        # Remove all categories temporarily (should be none from seed anyway)
        existing = await asyncpg_conn.fetch("SELECT id FROM content.movement_tech_categories")
        for row in existing:
            await asyncpg_conn.execute("DELETE FROM content.movement_tech_categories WHERE id = $1", row["id"])
        try:
            response = await test_client.get(f"{BASE}/categories")
            assert response.status_code == 200
            data = response.json()
            assert data["categories"] == []
        finally:
            # Restore any removed rows — in practice seed has none so nothing to restore
            pass


# ===========================================================================
# PUB-02: List Difficulties
# ===========================================================================


class TestListDifficulties:
    """GET /difficulties — public list endpoint."""

    async def test_happy_path(self, test_client, asyncpg_conn):
        """Returns 200 with a difficulties list."""
        dif_id = await _insert_difficulty(asyncpg_conn, "TestDif_PUB02_Happy", 999)
        try:
            response = await test_client.get(f"{BASE}/difficulties")
            assert response.status_code == 200
            data = response.json()
            assert "difficulties" in data
            assert isinstance(data["difficulties"], list)
            names = [d["name"] for d in data["difficulties"]]
            assert "TestDif_PUB02_Happy" in names
        finally:
            await _delete_difficulty(asyncpg_conn, dif_id)

    async def test_works_without_auth(self, unauthenticated_client):
        """Public endpoint succeeds without authentication."""
        response = await unauthenticated_client.get(f"{BASE}/difficulties")
        assert response.status_code == 200
        data = response.json()
        assert "difficulties" in data

    async def test_empty_list(self, test_client, asyncpg_conn):
        """Returns empty list when no difficulties exist."""
        existing = await asyncpg_conn.fetch("SELECT id FROM content.movement_tech_difficulties")
        for row in existing:
            await asyncpg_conn.execute("DELETE FROM content.movement_tech_difficulties WHERE id = $1", row["id"])
        try:
            response = await test_client.get(f"{BASE}/difficulties")
            assert response.status_code == 200
            data = response.json()
            assert data["difficulties"] == []
        finally:
            pass


# ===========================================================================
# PUB-03: List Techniques
# ===========================================================================


class TestListTechniques:
    """GET / — public techniques list endpoint."""

    async def test_happy_path(self, test_client, asyncpg_conn):
        """Returns 200 with a techniques list."""
        tech_id = await _insert_technique(asyncpg_conn, "TestTech_PUB03_Happy", 999)
        try:
            response = await test_client.get(f"{BASE}/")
            assert response.status_code == 200
            data = response.json()
            assert "techniques" in data
            assert isinstance(data["techniques"], list)
            names = [t["name"] for t in data["techniques"]]
            assert "TestTech_PUB03_Happy" in names
        finally:
            await _delete_technique(asyncpg_conn, tech_id)

    async def test_works_without_auth(self, unauthenticated_client):
        """Public endpoint succeeds without authentication."""
        response = await unauthenticated_client.get(f"{BASE}/")
        assert response.status_code == 200
        data = response.json()
        assert "techniques" in data

    async def test_empty_list(self, test_client, asyncpg_conn):
        """Returns empty techniques list when none exist."""
        existing = await asyncpg_conn.fetch("SELECT id FROM content.movement_techniques")
        for row in existing:
            await asyncpg_conn.execute("DELETE FROM content.movement_techniques WHERE id = $1", row["id"])
        try:
            response = await test_client.get(f"{BASE}/")
            assert response.status_code == 200
            data = response.json()
            assert data["techniques"] == []
        finally:
            pass

    async def test_response_contains_nested_structure(self, test_client, asyncpg_conn):
        """Technique objects contain tips and videos arrays."""
        tech_id = await _insert_technique(asyncpg_conn, "TestTech_PUB03_Nested", 998)
        try:
            response = await test_client.get(f"{BASE}/")
            assert response.status_code == 200
            data = response.json()
            tech = next((t for t in data["techniques"] if t["name"] == "TestTech_PUB03_Nested"), None)
            assert tech is not None
            assert "tips" in tech
            assert "videos" in tech
            assert isinstance(tech["tips"], list)
            assert isinstance(tech["videos"], list)
        finally:
            await _delete_technique(asyncpg_conn, tech_id)

    async def test_ordered_by_display_order(self, test_client, asyncpg_conn):
        """Techniques are returned in ascending display_order."""
        tech_ids: list[int] = []
        try:
            tech_ids.append(await _insert_technique(asyncpg_conn, "TestTech_PUB03_Order_B", 2000))
            tech_ids.append(await _insert_technique(asyncpg_conn, "TestTech_PUB03_Order_A", 1000))
            # Remove any other techniques that might interfere
            response = await test_client.get(f"{BASE}/")
            assert response.status_code == 200
            data = response.json()
            orders_returned = [
                t["display_order"]
                for t in data["techniques"]
                if t["name"] in {"TestTech_PUB03_Order_A", "TestTech_PUB03_Order_B"}
            ]
            # A (1000) must come before B (2000)
            assert orders_returned == sorted(orders_returned)
        finally:
            for tid in tech_ids:
                await _delete_technique(asyncpg_conn, tid)

    async def test_instructions_in_list_response(self, test_client, asyncpg_conn):
        """GET / includes instructions field in each technique object."""
        create_resp = await test_client.post(
            f"{BASE}/techniques",
            json={"name": "TestTech_PUB03_InstrList", "instructions": "List test instructions"},
        )
        assert create_resp.status_code == 201
        tech_id = create_resp.json()["id"]
        try:
            response = await test_client.get(f"{BASE}/")
            assert response.status_code == 200
            data = response.json()
            matching = [t for t in data["techniques"] if t["id"] == tech_id]
            assert len(matching) == 1
            assert matching[0]["instructions"] == "List test instructions"
        finally:
            await _delete_technique(asyncpg_conn, tech_id)


# ===========================================================================
# ACAT-01: Create Category
# ===========================================================================


class TestCreateCategory:
    """POST /categories — admin create."""

    async def test_happy_path(self, test_client, asyncpg_conn):
        """Returns 201 with id, name, sort_order."""
        response = await test_client.post(f"{BASE}/categories", json={"name": "TestCat_ACAT01"})
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "TestCat_ACAT01"
        assert "id" in data
        assert "sort_order" in data
        # Cleanup
        await _delete_category(asyncpg_conn, data["id"])

    async def test_requires_auth(self, unauthenticated_client):
        """Unauthenticated request returns 401."""
        response = await unauthenticated_client.post(f"{BASE}/categories", json={"name": "ShouldFail_Auth"})
        assert response.status_code == 401

    async def test_duplicate_name_returns_409(self, test_client, asyncpg_conn):
        """Creating a category with a duplicate name returns 409."""
        cat_id = await _insert_category(asyncpg_conn, "TestCat_ACAT01_Dup", 800)
        try:
            response = await test_client.post(f"{BASE}/categories", json={"name": "TestCat_ACAT01_Dup"})
            assert response.status_code == 409
        finally:
            await _delete_category(asyncpg_conn, cat_id)


# ===========================================================================
# ACAT-02: Update Category
# ===========================================================================


class TestUpdateCategory:
    """PUT /categories/{id} — admin update."""

    async def test_happy_path(self, test_client, asyncpg_conn):
        """Returns 200 with updated name."""
        cat_id = await _insert_category(asyncpg_conn, "TestCat_ACAT02_Before", 900)
        try:
            response = await test_client.put(f"{BASE}/categories/{cat_id}", json={"name": "TestCat_ACAT02_After"})
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == cat_id
            assert data["name"] == "TestCat_ACAT02_After"
        finally:
            await _delete_category(asyncpg_conn, cat_id)

    async def test_requires_auth(self, unauthenticated_client):
        """Unauthenticated request returns 401."""
        response = await unauthenticated_client.put(f"{BASE}/categories/999999", json={"name": "x"})
        assert response.status_code == 401

    async def test_nonexistent_returns_404(self, test_client):
        """Updating a non-existent category returns 404."""
        response = await test_client.put(f"{BASE}/categories/999999999", json={"name": "x"})
        assert response.status_code == 404

    async def test_duplicate_name_returns_409(self, test_client, asyncpg_conn):
        """Renaming to an existing name returns 409."""
        cat_a = await _insert_category(asyncpg_conn, "TestCat_ACAT02_DupA", 701)
        cat_b = await _insert_category(asyncpg_conn, "TestCat_ACAT02_DupB", 702)
        try:
            response = await test_client.put(f"{BASE}/categories/{cat_b}", json={"name": "TestCat_ACAT02_DupA"})
            assert response.status_code == 409
        finally:
            await _delete_category(asyncpg_conn, cat_a)
            await _delete_category(asyncpg_conn, cat_b)


# ===========================================================================
# ACAT-03: Delete Category
# ===========================================================================


class TestDeleteCategory:
    """DELETE /categories/{id} — admin delete."""

    async def test_happy_path(self, test_client, asyncpg_conn):
        """Returns 204 and category is gone."""
        cat_id = await _insert_category(asyncpg_conn, "TestCat_ACAT03_Del", 850)
        response = await test_client.delete(f"{BASE}/categories/{cat_id}")
        assert response.status_code == 204
        # Verify it's gone
        row = await asyncpg_conn.fetchrow("SELECT id FROM content.movement_tech_categories WHERE id = $1", cat_id)
        assert row is None

    async def test_requires_auth(self, unauthenticated_client):
        """Unauthenticated request returns 401."""
        response = await unauthenticated_client.delete(f"{BASE}/categories/999999")
        assert response.status_code == 401

    async def test_nonexistent_returns_404(self, test_client):
        """Deleting a non-existent category returns 404."""
        response = await test_client.delete(f"{BASE}/categories/999999999")
        assert response.status_code == 404

    async def test_normalize_sort_order_after_delete(self, test_client, asyncpg_conn):
        """Pitfall #2: deleting middle item renormalizes remaining sort_orders to [1, 2]."""
        # Clear any existing categories to control sort_orders precisely
        existing = await asyncpg_conn.fetch("SELECT id FROM content.movement_tech_categories")
        for row in existing:
            await asyncpg_conn.execute("DELETE FROM content.movement_tech_categories WHERE id = $1", row["id"])

        # Insert 3 with contiguous sort_orders
        cat_a = await _insert_category(asyncpg_conn, "TestCat_ACAT03_Norm_A", 1)
        cat_b = await _insert_category(asyncpg_conn, "TestCat_ACAT03_Norm_B", 2)
        cat_c = await _insert_category(asyncpg_conn, "TestCat_ACAT03_Norm_C", 3)

        try:
            # Delete the middle one
            response = await test_client.delete(f"{BASE}/categories/{cat_b}")
            assert response.status_code == 204

            # Remaining sort_orders should be contiguous [1, 2]
            remaining = await _fetch_category_sort_orders(asyncpg_conn)
            assert remaining == [1, 2], f"Expected [1, 2] after normalize, got {remaining}"
        finally:
            await _delete_category(asyncpg_conn, cat_a)
            # cat_b already deleted
            await _delete_category(asyncpg_conn, cat_c)


# ===========================================================================
# ACAT-04: Reorder Category
# ===========================================================================


class TestReorderCategory:
    """POST /categories/{id}/reorder — admin reorder."""

    async def test_happy_path_swap(self, test_client, asyncpg_conn):
        """Moving item down swaps sort_orders with next neighbour."""
        existing = await asyncpg_conn.fetch("SELECT id FROM content.movement_tech_categories")
        for row in existing:
            await asyncpg_conn.execute("DELETE FROM content.movement_tech_categories WHERE id = $1", row["id"])

        cat_a = await _insert_category(asyncpg_conn, "TestCat_ACAT04_A", 1)
        cat_b = await _insert_category(asyncpg_conn, "TestCat_ACAT04_B", 2)
        try:
            response = await test_client.post(f"{BASE}/categories/{cat_a}/reorder", json={"direction": "down"})
            assert response.status_code == 201
            data = response.json()
            assert "categories" in data
            items = {c["id"]: c["sort_order"] for c in data["categories"]}
            # A should now have sort_order 2, B should have sort_order 1
            assert items[cat_a] == 2
            assert items[cat_b] == 1
        finally:
            await _delete_category(asyncpg_conn, cat_a)
            await _delete_category(asyncpg_conn, cat_b)

    async def test_requires_auth(self, unauthenticated_client):
        """Unauthenticated request returns 401."""
        response = await unauthenticated_client.post(f"{BASE}/categories/999999/reorder", json={"direction": "up"})
        assert response.status_code == 401

    async def test_nonexistent_returns_404(self, test_client):
        """Reordering a non-existent category returns 404."""
        response = await test_client.post(f"{BASE}/categories/999999999/reorder", json={"direction": "up"})
        assert response.status_code == 404

    async def test_boundary_reorder_up_first_item(self, test_client, asyncpg_conn):
        """Pitfall #3: reordering first item up returns 201 with unchanged order."""
        existing = await asyncpg_conn.fetch("SELECT id FROM content.movement_tech_categories")
        for row in existing:
            await asyncpg_conn.execute("DELETE FROM content.movement_tech_categories WHERE id = $1", row["id"])

        cat_a = await _insert_category(asyncpg_conn, "TestCat_ACAT04_Bound_A", 1)
        cat_b = await _insert_category(asyncpg_conn, "TestCat_ACAT04_Bound_B", 2)
        try:
            response = await test_client.post(f"{BASE}/categories/{cat_a}/reorder", json={"direction": "up"})
            assert response.status_code == 201
            data = response.json()
            items = {c["id"]: c["sort_order"] for c in data["categories"]}
            # Order unchanged — first item can't go further up
            assert items[cat_a] == 1
            assert items[cat_b] == 2
        finally:
            await _delete_category(asyncpg_conn, cat_a)
            await _delete_category(asyncpg_conn, cat_b)

    async def test_boundary_reorder_down_last_item(self, test_client, asyncpg_conn):
        """Pitfall #3: reordering last item down returns 201 with unchanged order."""
        existing = await asyncpg_conn.fetch("SELECT id FROM content.movement_tech_categories")
        for row in existing:
            await asyncpg_conn.execute("DELETE FROM content.movement_tech_categories WHERE id = $1", row["id"])

        cat_a = await _insert_category(asyncpg_conn, "TestCat_ACAT04_BoundD_A", 1)
        cat_b = await _insert_category(asyncpg_conn, "TestCat_ACAT04_BoundD_B", 2)
        try:
            response = await test_client.post(f"{BASE}/categories/{cat_b}/reorder", json={"direction": "down"})
            assert response.status_code == 201
            data = response.json()
            items = {c["id"]: c["sort_order"] for c in data["categories"]}
            # Order unchanged — last item can't go further down
            assert items[cat_a] == 1
            assert items[cat_b] == 2
        finally:
            await _delete_category(asyncpg_conn, cat_a)
            await _delete_category(asyncpg_conn, cat_b)


# ===========================================================================
# ADIF-01: Create Difficulty
# ===========================================================================


class TestCreateDifficulty:
    """POST /difficulties — admin create."""

    async def test_happy_path(self, test_client, asyncpg_conn):
        """Returns 201 with id, name, sort_order."""
        response = await test_client.post(f"{BASE}/difficulties", json={"name": "TestDif_ADIF01"})
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "TestDif_ADIF01"
        assert "id" in data
        assert "sort_order" in data
        await _delete_difficulty(asyncpg_conn, data["id"])

    async def test_requires_auth(self, unauthenticated_client):
        """Unauthenticated request returns 401."""
        response = await unauthenticated_client.post(f"{BASE}/difficulties", json={"name": "ShouldFail_Auth"})
        assert response.status_code == 401

    async def test_duplicate_name_returns_409(self, test_client, asyncpg_conn):
        """Creating a difficulty with a duplicate name returns 409."""
        dif_id = await _insert_difficulty(asyncpg_conn, "TestDif_ADIF01_Dup", 800)
        try:
            response = await test_client.post(f"{BASE}/difficulties", json={"name": "TestDif_ADIF01_Dup"})
            assert response.status_code == 409
        finally:
            await _delete_difficulty(asyncpg_conn, dif_id)


# ===========================================================================
# ADIF-02: Update Difficulty
# ===========================================================================


class TestUpdateDifficulty:
    """PUT /difficulties/{id} — admin update."""

    async def test_happy_path(self, test_client, asyncpg_conn):
        """Returns 200 with updated name."""
        dif_id = await _insert_difficulty(asyncpg_conn, "TestDif_ADIF02_Before", 900)
        try:
            response = await test_client.put(f"{BASE}/difficulties/{dif_id}", json={"name": "TestDif_ADIF02_After"})
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == dif_id
            assert data["name"] == "TestDif_ADIF02_After"
        finally:
            await _delete_difficulty(asyncpg_conn, dif_id)

    async def test_requires_auth(self, unauthenticated_client):
        """Unauthenticated request returns 401."""
        response = await unauthenticated_client.put(f"{BASE}/difficulties/999999", json={"name": "x"})
        assert response.status_code == 401

    async def test_nonexistent_returns_404(self, test_client):
        """Updating a non-existent difficulty returns 404."""
        response = await test_client.put(f"{BASE}/difficulties/999999999", json={"name": "x"})
        assert response.status_code == 404

    async def test_duplicate_name_returns_409(self, test_client, asyncpg_conn):
        """Renaming to an existing name returns 409."""
        dif_a = await _insert_difficulty(asyncpg_conn, "TestDif_ADIF02_DupA", 701)
        dif_b = await _insert_difficulty(asyncpg_conn, "TestDif_ADIF02_DupB", 702)
        try:
            response = await test_client.put(f"{BASE}/difficulties/{dif_b}", json={"name": "TestDif_ADIF02_DupA"})
            assert response.status_code == 409
        finally:
            await _delete_difficulty(asyncpg_conn, dif_a)
            await _delete_difficulty(asyncpg_conn, dif_b)


# ===========================================================================
# ADIF-03: Delete Difficulty
# ===========================================================================


class TestDeleteDifficulty:
    """DELETE /difficulties/{id} — admin delete."""

    async def test_happy_path(self, test_client, asyncpg_conn):
        """Returns 204 and difficulty is gone."""
        dif_id = await _insert_difficulty(asyncpg_conn, "TestDif_ADIF03_Del", 850)
        response = await test_client.delete(f"{BASE}/difficulties/{dif_id}")
        assert response.status_code == 204
        row = await asyncpg_conn.fetchrow("SELECT id FROM content.movement_tech_difficulties WHERE id = $1", dif_id)
        assert row is None

    async def test_requires_auth(self, unauthenticated_client):
        """Unauthenticated request returns 401."""
        response = await unauthenticated_client.delete(f"{BASE}/difficulties/999999")
        assert response.status_code == 401

    async def test_nonexistent_returns_404(self, test_client):
        """Deleting a non-existent difficulty returns 404."""
        response = await test_client.delete(f"{BASE}/difficulties/999999999")
        assert response.status_code == 404

    async def test_normalize_sort_order_after_delete(self, test_client, asyncpg_conn):
        """Pitfall #2: deleting middle item renormalizes remaining sort_orders to [1, 2]."""
        existing = await asyncpg_conn.fetch("SELECT id FROM content.movement_tech_difficulties")
        for row in existing:
            await asyncpg_conn.execute("DELETE FROM content.movement_tech_difficulties WHERE id = $1", row["id"])

        dif_a = await _insert_difficulty(asyncpg_conn, "TestDif_ADIF03_Norm_A", 1)
        dif_b = await _insert_difficulty(asyncpg_conn, "TestDif_ADIF03_Norm_B", 2)
        dif_c = await _insert_difficulty(asyncpg_conn, "TestDif_ADIF03_Norm_C", 3)

        try:
            response = await test_client.delete(f"{BASE}/difficulties/{dif_b}")
            assert response.status_code == 204

            remaining = await _fetch_difficulty_sort_orders(asyncpg_conn)
            assert remaining == [1, 2], f"Expected [1, 2] after normalize, got {remaining}"
        finally:
            await _delete_difficulty(asyncpg_conn, dif_a)
            await _delete_difficulty(asyncpg_conn, dif_c)


# ===========================================================================
# ADIF-04: Reorder Difficulty
# ===========================================================================


class TestReorderDifficulty:
    """POST /difficulties/{id}/reorder — admin reorder."""

    async def test_happy_path_swap(self, test_client, asyncpg_conn):
        """Moving item down swaps sort_orders with next neighbour."""
        existing = await asyncpg_conn.fetch("SELECT id FROM content.movement_tech_difficulties")
        for row in existing:
            await asyncpg_conn.execute("DELETE FROM content.movement_tech_difficulties WHERE id = $1", row["id"])

        dif_a = await _insert_difficulty(asyncpg_conn, "TestDif_ADIF04_A", 1)
        dif_b = await _insert_difficulty(asyncpg_conn, "TestDif_ADIF04_B", 2)
        try:
            response = await test_client.post(f"{BASE}/difficulties/{dif_a}/reorder", json={"direction": "down"})
            assert response.status_code == 201
            data = response.json()
            assert "difficulties" in data
            items = {d["id"]: d["sort_order"] for d in data["difficulties"]}
            assert items[dif_a] == 2
            assert items[dif_b] == 1
        finally:
            await _delete_difficulty(asyncpg_conn, dif_a)
            await _delete_difficulty(asyncpg_conn, dif_b)

    async def test_requires_auth(self, unauthenticated_client):
        """Unauthenticated request returns 401."""
        response = await unauthenticated_client.post(f"{BASE}/difficulties/999999/reorder", json={"direction": "up"})
        assert response.status_code == 401

    async def test_nonexistent_returns_404(self, test_client):
        """Reordering a non-existent difficulty returns 404."""
        response = await test_client.post(f"{BASE}/difficulties/999999999/reorder", json={"direction": "up"})
        assert response.status_code == 404

    async def test_boundary_reorder_up_first_item(self, test_client, asyncpg_conn):
        """Pitfall #3: reordering first item up returns 201 with unchanged order."""
        existing = await asyncpg_conn.fetch("SELECT id FROM content.movement_tech_difficulties")
        for row in existing:
            await asyncpg_conn.execute("DELETE FROM content.movement_tech_difficulties WHERE id = $1", row["id"])

        dif_a = await _insert_difficulty(asyncpg_conn, "TestDif_ADIF04_Bound_A", 1)
        dif_b = await _insert_difficulty(asyncpg_conn, "TestDif_ADIF04_Bound_B", 2)
        try:
            response = await test_client.post(f"{BASE}/difficulties/{dif_a}/reorder", json={"direction": "up"})
            assert response.status_code == 201
            data = response.json()
            items = {d["id"]: d["sort_order"] for d in data["difficulties"]}
            assert items[dif_a] == 1
            assert items[dif_b] == 2
        finally:
            await _delete_difficulty(asyncpg_conn, dif_a)
            await _delete_difficulty(asyncpg_conn, dif_b)

    async def test_boundary_reorder_down_last_item(self, test_client, asyncpg_conn):
        """Pitfall #3: reordering last item down returns 201 with unchanged order."""
        existing = await asyncpg_conn.fetch("SELECT id FROM content.movement_tech_difficulties")
        for row in existing:
            await asyncpg_conn.execute("DELETE FROM content.movement_tech_difficulties WHERE id = $1", row["id"])

        dif_a = await _insert_difficulty(asyncpg_conn, "TestDif_ADIF04_BoundD_A", 1)
        dif_b = await _insert_difficulty(asyncpg_conn, "TestDif_ADIF04_BoundD_B", 2)
        try:
            response = await test_client.post(f"{BASE}/difficulties/{dif_b}/reorder", json={"direction": "down"})
            assert response.status_code == 201
            data = response.json()
            items = {d["id"]: d["sort_order"] for d in data["difficulties"]}
            assert items[dif_a] == 1
            assert items[dif_b] == 2
        finally:
            await _delete_difficulty(asyncpg_conn, dif_a)
            await _delete_difficulty(asyncpg_conn, dif_b)


# ===========================================================================
# Helpers for technique tests
# ===========================================================================


async def _insert_technique_with_cat_dif(
    conn, name: str, display_order: int, category_id: int | None = None, difficulty_id: int | None = None
) -> int:
    """Insert a technique with optional category and difficulty and return its id."""
    return await conn.fetchval(
        """
        INSERT INTO content.movement_techniques (name, display_order, category_id, difficulty_id)
        VALUES ($1, $2, $3, $4)
        RETURNING id
        """,
        name,
        display_order,
        category_id,
        difficulty_id,
    )


async def _insert_tip(conn, technique_id: int, text: str, sort_order: int) -> int:
    """Insert a tip for a technique and return its id."""
    return await conn.fetchval(
        """
        INSERT INTO content.movement_tech_tips (technique_id, text, sort_order)
        VALUES ($1, $2, $3)
        RETURNING id
        """,
        technique_id,
        text,
        sort_order,
    )


async def _insert_video(conn, technique_id: int, url: str, sort_order: int, caption: str | None = None) -> int:
    """Insert a video for a technique and return its id."""
    return await conn.fetchval(
        """
        INSERT INTO content.movement_tech_videos (technique_id, url, caption, sort_order)
        VALUES ($1, $2, $3, $4)
        RETURNING id
        """,
        technique_id,
        url,
        caption,
        sort_order,
    )


async def _fetch_technique_display_orders(conn) -> list[int]:
    """Return all technique display_orders ordered ascending."""
    rows = await conn.fetch("SELECT display_order FROM content.movement_techniques ORDER BY display_order")
    return [r["display_order"] for r in rows]


# ===========================================================================
# ATEC-01: Create Technique
# ===========================================================================


class TestCreateTechnique:
    """POST /techniques — admin create."""

    async def test_happy_path(self, test_client, asyncpg_conn):
        """Returns 201 with full technique structure."""
        response = await test_client.post(
            f"{BASE}/techniques",
            json={"name": "TestTech_ATEC01_Happy", "description": "A description"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "TestTech_ATEC01_Happy"
        assert data["description"] == "A description"
        assert "id" in data
        assert "display_order" in data
        assert data["category_id"] is None
        assert data["difficulty_id"] is None
        assert data["category_name"] is None
        assert data["difficulty_name"] is None
        assert isinstance(data["tips"], list)
        assert isinstance(data["videos"], list)
        await _delete_technique(asyncpg_conn, data["id"])

    async def test_requires_auth(self, unauthenticated_client):
        """Unauthenticated request returns 401."""
        response = await unauthenticated_client.post(f"{BASE}/techniques", json={"name": "ShouldFail_Auth"})
        assert response.status_code == 401

    async def test_with_tips(self, test_client, asyncpg_conn):
        """POST with tips list returns technique with tips containing DB-assigned IDs."""
        response = await test_client.post(
            f"{BASE}/techniques",
            json={
                "name": "TestTech_ATEC01_Tips",
                "tips": [
                    {"text": "Tip 1", "sort_order": 1},
                    {"text": "Tip 2", "sort_order": 2},
                ],
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert len(data["tips"]) == 2
        # Each tip must have a DB-assigned id
        for tip in data["tips"]:
            assert "id" in tip
            assert isinstance(tip["id"], int)
        texts = {t["text"] for t in data["tips"]}
        assert texts == {"Tip 1", "Tip 2"}
        await _delete_technique(asyncpg_conn, data["id"])

    async def test_with_videos(self, test_client, asyncpg_conn):
        """POST with videos list returns technique with videos containing IDs."""
        response = await test_client.post(
            f"{BASE}/techniques",
            json={
                "name": "TestTech_ATEC01_Videos",
                "videos": [{"url": "https://example.com/v1", "caption": "Cap 1", "sort_order": 1}],
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert len(data["videos"]) == 1
        assert "id" in data["videos"][0]
        assert data["videos"][0]["url"] == "https://example.com/v1"
        await _delete_technique(asyncpg_conn, data["id"])

    async def test_with_both_tips_and_videos(self, test_client, asyncpg_conn):
        """POST with both tips and videos returns both nested arrays populated."""
        response = await test_client.post(
            f"{BASE}/techniques",
            json={
                "name": "TestTech_ATEC01_Both",
                "tips": [{"text": "Tip A", "sort_order": 1}],
                "videos": [{"url": "https://example.com/vA", "sort_order": 1}],
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert len(data["tips"]) == 1
        assert len(data["videos"]) == 1
        await _delete_technique(asyncpg_conn, data["id"])

    async def test_with_category_and_difficulty(self, test_client, asyncpg_conn):
        """Technique created with valid category and difficulty shows names in response."""
        cat_id = await _insert_category(asyncpg_conn, "TestCat_ATEC01_FK", 8001)
        dif_id = await _insert_difficulty(asyncpg_conn, "TestDif_ATEC01_FK", 8001)
        try:
            response = await test_client.post(
                f"{BASE}/techniques",
                json={
                    "name": "TestTech_ATEC01_FK",
                    "category_id": cat_id,
                    "difficulty_id": dif_id,
                },
            )
            assert response.status_code == 201
            data = response.json()
            assert data["category_id"] == cat_id
            assert data["difficulty_id"] == dif_id
            assert data["category_name"] == "TestCat_ATEC01_FK"
            assert data["difficulty_name"] == "TestDif_ATEC01_FK"
            await _delete_technique(asyncpg_conn, data["id"])
        finally:
            await _delete_category(asyncpg_conn, cat_id)
            await _delete_difficulty(asyncpg_conn, dif_id)

    async def test_invalid_category_id_returns_400(self, test_client):
        """POST with non-existent category_id returns 400."""
        response = await test_client.post(
            f"{BASE}/techniques",
            json={"name": "TestTech_ATEC01_BadCat", "category_id": 999999999},
        )
        assert response.status_code == 400

    async def test_invalid_difficulty_id_returns_400(self, test_client):
        """POST with non-existent difficulty_id returns 400."""
        response = await test_client.post(
            f"{BASE}/techniques",
            json={"name": "TestTech_ATEC01_BadDif", "difficulty_id": 999999999},
        )
        assert response.status_code == 400

    async def test_response_contains_refetched_data(self, test_client, asyncpg_conn):
        """Pitfall #1: response tips have DB-assigned IDs, proving re-fetch not request assembly."""
        response = await test_client.post(
            f"{BASE}/techniques",
            json={
                "name": "TestTech_ATEC01_Refetch",
                "tips": [{"text": "Re-fetched tip", "sort_order": 1}],
            },
        )
        assert response.status_code == 201
        data = response.json()
        # Tips in response must carry integer IDs assigned by the DB
        assert len(data["tips"]) == 1
        tip = data["tips"][0]
        assert "id" in tip
        assert isinstance(tip["id"], int)
        assert tip["id"] > 0
        # Confirm the ID actually exists in the DB
        row = await asyncpg_conn.fetchrow("SELECT id FROM content.movement_tech_tips WHERE id = $1", tip["id"])
        assert row is not None
        await _delete_technique(asyncpg_conn, data["id"])

    async def test_with_instructions(self, test_client, asyncpg_conn):
        """POST with instructions field returns it in response."""
        response = await test_client.post(
            f"{BASE}/techniques",
            json={"name": "TestTech_ATEC01_Instr", "instructions": "Hold jump then dash forward"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["instructions"] == "Hold jump then dash forward"
        await _delete_technique(asyncpg_conn, data["id"])

    async def test_without_instructions_returns_null(self, test_client, asyncpg_conn):
        """POST without instructions field returns instructions as null."""
        response = await test_client.post(
            f"{BASE}/techniques",
            json={"name": "TestTech_ATEC01_NoInstr"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["instructions"] is None
        await _delete_technique(asyncpg_conn, data["id"])


# ===========================================================================
# ATEC-05: Fetch Technique
# ===========================================================================


class TestFetchTechnique:
    """GET /techniques/{id} — admin fetch single technique."""

    async def test_happy_path(self, test_client, asyncpg_conn):
        """Returns 200 with full nested structure for an existing technique."""
        tech_id = await _insert_technique(asyncpg_conn, "TestTech_ATEC05_Happy", 7001)
        await _insert_tip(asyncpg_conn, tech_id, "Tip A", 1)
        await _insert_video(asyncpg_conn, tech_id, "https://example.com/v", 1, "Cap")
        try:
            response = await test_client.get(f"{BASE}/techniques/{tech_id}")
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == tech_id
            assert data["name"] == "TestTech_ATEC05_Happy"
        finally:
            await _delete_technique(asyncpg_conn, tech_id)

    async def test_requires_auth(self, unauthenticated_client):
        """Unauthenticated request returns 401."""
        response = await unauthenticated_client.get(f"{BASE}/techniques/1")
        assert response.status_code == 401

    async def test_nonexistent_returns_404(self, test_client):
        """Fetching a non-existent technique returns 404."""
        response = await test_client.get(f"{BASE}/techniques/999999999")
        assert response.status_code == 404

    async def test_response_contains_nested_tips_videos(self, test_client, asyncpg_conn):
        """Response contains tips and videos arrays with expected fields."""
        tech_id = await _insert_technique(asyncpg_conn, "TestTech_ATEC05_Nested", 7002)
        tip_id = await _insert_tip(asyncpg_conn, tech_id, "Nested tip", 1)
        vid_id = await _insert_video(asyncpg_conn, tech_id, "https://example.com/nested", 1, "Nested cap")
        try:
            response = await test_client.get(f"{BASE}/techniques/{tech_id}")
            assert response.status_code == 200
            data = response.json()
            assert len(data["tips"]) == 1
            assert data["tips"][0]["id"] == tip_id
            assert data["tips"][0]["text"] == "Nested tip"
            assert data["tips"][0]["sort_order"] == 1
            assert len(data["videos"]) == 1
            assert data["videos"][0]["id"] == vid_id
            assert data["videos"][0]["url"] == "https://example.com/nested"
            assert data["videos"][0]["caption"] == "Nested cap"
        finally:
            await _delete_technique(asyncpg_conn, tech_id)


# ===========================================================================
# ATEC-02: Update Technique
# ===========================================================================


class TestUpdateTechnique:
    """PUT /techniques/{id} — admin update."""

    async def test_happy_path(self, test_client, asyncpg_conn):
        """Returns 200 with updated name."""
        tech_id = await _insert_technique(asyncpg_conn, "TestTech_ATEC02_Before", 6001)
        try:
            response = await test_client.put(
                f"{BASE}/techniques/{tech_id}",
                json={"name": "TestTech_ATEC02_After"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == tech_id
            assert data["name"] == "TestTech_ATEC02_After"
        finally:
            await _delete_technique(asyncpg_conn, tech_id)

    async def test_requires_auth(self, unauthenticated_client):
        """Unauthenticated request returns 401."""
        response = await unauthenticated_client.put(f"{BASE}/techniques/999999", json={"name": "x"})
        assert response.status_code == 401

    async def test_nonexistent_returns_404(self, test_client):
        """Updating a non-existent technique returns 404."""
        response = await test_client.put(f"{BASE}/techniques/999999999", json={"name": "x"})
        assert response.status_code == 404

    async def test_unset_tips_preserves_existing(self, test_client, asyncpg_conn):
        """PUT without 'tips' key leaves existing tips unchanged (UNSET semantics)."""
        tech_id = await _insert_technique(asyncpg_conn, "TestTech_ATEC02_UnsetTips", 6002)
        await _insert_tip(asyncpg_conn, tech_id, "Existing tip", 1)
        try:
            # Send PUT with only name — no 'tips' key at all
            response = await test_client.put(
                f"{BASE}/techniques/{tech_id}",
                json={"name": "TestTech_ATEC02_UnsetTips_Updated"},
            )
            assert response.status_code == 200
            data = response.json()
            assert len(data["tips"]) == 1
            assert data["tips"][0]["text"] == "Existing tip"
        finally:
            await _delete_technique(asyncpg_conn, tech_id)

    async def test_empty_tips_list_clears_tips(self, test_client, asyncpg_conn):
        """PUT with 'tips: []' explicitly removes all tips."""
        tech_id = await _insert_technique(asyncpg_conn, "TestTech_ATEC02_ClearTips", 6003)
        await _insert_tip(asyncpg_conn, tech_id, "Tip to clear", 1)
        try:
            response = await test_client.put(
                f"{BASE}/techniques/{tech_id}",
                json={"tips": []},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["tips"] == []
        finally:
            await _delete_technique(asyncpg_conn, tech_id)

    async def test_unset_videos_preserves_existing(self, test_client, asyncpg_conn):
        """PUT without 'videos' key leaves existing videos unchanged (UNSET semantics)."""
        tech_id = await _insert_technique(asyncpg_conn, "TestTech_ATEC02_UnsetVids", 6004)
        await _insert_video(asyncpg_conn, tech_id, "https://example.com/existing", 1, "Existing")
        try:
            response = await test_client.put(
                f"{BASE}/techniques/{tech_id}",
                json={"name": "TestTech_ATEC02_UnsetVids_Updated"},
            )
            assert response.status_code == 200
            data = response.json()
            assert len(data["videos"]) == 1
            assert data["videos"][0]["url"] == "https://example.com/existing"
        finally:
            await _delete_technique(asyncpg_conn, tech_id)

    async def test_empty_videos_list_clears_videos(self, test_client, asyncpg_conn):
        """PUT with 'videos: []' explicitly removes all videos."""
        tech_id = await _insert_technique(asyncpg_conn, "TestTech_ATEC02_ClearVids", 6005)
        await _insert_video(asyncpg_conn, tech_id, "https://example.com/to_clear", 1)
        try:
            response = await test_client.put(
                f"{BASE}/techniques/{tech_id}",
                json={"videos": []},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["videos"] == []
        finally:
            await _delete_technique(asyncpg_conn, tech_id)

    async def test_replace_tips(self, test_client, asyncpg_conn):
        """PUT with new tips replaces existing tips wholesale."""
        tech_id = await _insert_technique(asyncpg_conn, "TestTech_ATEC02_ReplaceTips", 6006)
        await _insert_tip(asyncpg_conn, tech_id, "Old tip 1", 1)
        await _insert_tip(asyncpg_conn, tech_id, "Old tip 2", 2)
        try:
            response = await test_client.put(
                f"{BASE}/techniques/{tech_id}",
                json={"tips": [{"text": "New tip", "sort_order": 1}]},
            )
            assert response.status_code == 200
            data = response.json()
            assert len(data["tips"]) == 1
            assert data["tips"][0]["text"] == "New tip"
        finally:
            await _delete_technique(asyncpg_conn, tech_id)

    async def test_invalid_category_id_returns_400(self, test_client, asyncpg_conn):
        """PUT with non-existent category_id returns 400."""
        tech_id = await _insert_technique(asyncpg_conn, "TestTech_ATEC02_BadCat", 6007)
        try:
            response = await test_client.put(
                f"{BASE}/techniques/{tech_id}",
                json={"category_id": 999999999},
            )
            assert response.status_code == 400
        finally:
            await _delete_technique(asyncpg_conn, tech_id)

    async def test_invalid_difficulty_id_returns_400(self, test_client, asyncpg_conn):
        """PUT with non-existent difficulty_id returns 400."""
        tech_id = await _insert_technique(asyncpg_conn, "TestTech_ATEC02_BadDif", 6008)
        try:
            response = await test_client.put(
                f"{BASE}/techniques/{tech_id}",
                json={"difficulty_id": 999999999},
            )
            assert response.status_code == 400
        finally:
            await _delete_technique(asyncpg_conn, tech_id)

    async def test_update_category_to_null(self, test_client, asyncpg_conn):
        """PUT with category_id=null clears the category FK."""
        cat_id = await _insert_category(asyncpg_conn, "TestCat_ATEC02_Null", 8002)
        tech_id = await _insert_technique_with_cat_dif(
            asyncpg_conn, "TestTech_ATEC02_NullCat", 6009, category_id=cat_id
        )
        try:
            response = await test_client.put(
                f"{BASE}/techniques/{tech_id}",
                json={"category_id": None},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["category_id"] is None
            assert data["category_name"] is None
        finally:
            await _delete_technique(asyncpg_conn, tech_id)
            await _delete_category(asyncpg_conn, cat_id)

    async def test_response_contains_refetched_data(self, test_client, asyncpg_conn):
        """Pitfall #1: PUT with tips change returns fresh IDs from DB re-fetch."""
        tech_id = await _insert_technique(asyncpg_conn, "TestTech_ATEC02_Refetch", 6010)
        try:
            response = await test_client.put(
                f"{BASE}/techniques/{tech_id}",
                json={"tips": [{"text": "Fresh tip", "sort_order": 1}]},
            )
            assert response.status_code == 200
            data = response.json()
            assert len(data["tips"]) == 1
            tip = data["tips"][0]
            assert "id" in tip
            assert isinstance(tip["id"], int)
            assert tip["id"] > 0
            # Confirm the tip actually exists in the DB under this ID
            row = await asyncpg_conn.fetchrow("SELECT id FROM content.movement_tech_tips WHERE id = $1", tip["id"])
            assert row is not None
        finally:
            await _delete_technique(asyncpg_conn, tech_id)

    async def test_update_instructions(self, test_client, asyncpg_conn):
        """PUT with instructions changes the stored value."""
        tech_id = await _insert_technique(asyncpg_conn, "TestTech_ATEC02_InstrUpd", 6020)
        try:
            response = await test_client.put(
                f"{BASE}/techniques/{tech_id}",
                json={"instructions": "Updated instructions text"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["instructions"] == "Updated instructions text"
        finally:
            await _delete_technique(asyncpg_conn, tech_id)

    async def test_unset_instructions_preserves_existing(self, test_client, asyncpg_conn):
        """PUT without instructions key preserves existing value (UNSET semantics)."""
        # Create technique with instructions via API
        create_resp = await test_client.post(
            f"{BASE}/techniques",
            json={"name": "TestTech_ATEC02_InstrUnset", "instructions": "Original instructions"},
        )
        assert create_resp.status_code == 201
        tech_id = create_resp.json()["id"]
        try:
            # Update only the name, omitting instructions entirely
            response = await test_client.put(
                f"{BASE}/techniques/{tech_id}",
                json={"name": "TestTech_ATEC02_InstrUnset_Updated"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["instructions"] == "Original instructions"
        finally:
            await _delete_technique(asyncpg_conn, tech_id)

    async def test_clear_instructions_with_null(self, test_client, asyncpg_conn):
        """PUT with instructions=null clears the field."""
        create_resp = await test_client.post(
            f"{BASE}/techniques",
            json={"name": "TestTech_ATEC02_InstrClear", "instructions": "To be cleared"},
        )
        assert create_resp.status_code == 201
        tech_id = create_resp.json()["id"]
        try:
            response = await test_client.put(
                f"{BASE}/techniques/{tech_id}",
                json={"instructions": None},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["instructions"] is None
        finally:
            await _delete_technique(asyncpg_conn, tech_id)


# ===========================================================================
# ATEC-03: Delete Technique
# ===========================================================================


class TestDeleteTechnique:
    """DELETE /techniques/{id} — admin delete."""

    async def test_happy_path(self, test_client, asyncpg_conn):
        """Returns 204 and technique is gone."""
        tech_id = await _insert_technique(asyncpg_conn, "TestTech_ATEC03_Del", 5001)
        response = await test_client.delete(f"{BASE}/techniques/{tech_id}")
        assert response.status_code == 204
        row = await asyncpg_conn.fetchrow("SELECT id FROM content.movement_techniques WHERE id = $1", tech_id)
        assert row is None

    async def test_requires_auth(self, unauthenticated_client):
        """Unauthenticated request returns 401."""
        response = await unauthenticated_client.delete(f"{BASE}/techniques/999999")
        assert response.status_code == 401

    async def test_nonexistent_returns_404(self, test_client):
        """Deleting a non-existent technique returns 404."""
        response = await test_client.delete(f"{BASE}/techniques/999999999")
        assert response.status_code == 404

    async def test_cascade_deletes_tips_and_videos(self, test_client, asyncpg_conn):
        """Deleting a technique removes its tips and videos from the DB."""
        tech_id = await _insert_technique(asyncpg_conn, "TestTech_ATEC03_Cascade", 5002)
        tip_id = await _insert_tip(asyncpg_conn, tech_id, "Cascade tip", 1)
        vid_id = await _insert_video(asyncpg_conn, tech_id, "https://example.com/cascade", 1)
        response = await test_client.delete(f"{BASE}/techniques/{tech_id}")
        assert response.status_code == 204
        tip_row = await asyncpg_conn.fetchrow("SELECT id FROM content.movement_tech_tips WHERE id = $1", tip_id)
        assert tip_row is None, "Tip should have been cascade-deleted"
        vid_row = await asyncpg_conn.fetchrow("SELECT id FROM content.movement_tech_videos WHERE id = $1", vid_id)
        assert vid_row is None, "Video should have been cascade-deleted"

    async def test_normalize_display_order_after_delete(self, test_client, asyncpg_conn):
        """Pitfall #2: deleting middle technique renormalizes remaining display_orders to [1, 2]."""
        existing = await asyncpg_conn.fetch("SELECT id FROM content.movement_techniques")
        for row in existing:
            await asyncpg_conn.execute("DELETE FROM content.movement_techniques WHERE id = $1", row["id"])

        tech_a = await _insert_technique(asyncpg_conn, "TestTech_ATEC03_Norm_A", 1)
        tech_b = await _insert_technique(asyncpg_conn, "TestTech_ATEC03_Norm_B", 2)
        tech_c = await _insert_technique(asyncpg_conn, "TestTech_ATEC03_Norm_C", 3)

        try:
            response = await test_client.delete(f"{BASE}/techniques/{tech_b}")
            assert response.status_code == 204

            remaining = await _fetch_technique_display_orders(asyncpg_conn)
            assert remaining == [1, 2], f"Expected [1, 2] after normalize, got {remaining}"
        finally:
            await _delete_technique(asyncpg_conn, tech_a)
            await _delete_technique(asyncpg_conn, tech_c)


# ===========================================================================
# ATEC-04: Reorder Technique
# ===========================================================================


class TestReorderTechnique:
    """POST /techniques/{id}/reorder — admin reorder."""

    async def test_happy_path_swap(self, test_client, asyncpg_conn):
        """Moving technique down swaps display_orders with next neighbour."""
        existing = await asyncpg_conn.fetch("SELECT id FROM content.movement_techniques")
        for row in existing:
            await asyncpg_conn.execute("DELETE FROM content.movement_techniques WHERE id = $1", row["id"])

        tech_a = await _insert_technique(asyncpg_conn, "TestTech_ATEC04_A", 1)
        tech_b = await _insert_technique(asyncpg_conn, "TestTech_ATEC04_B", 2)
        try:
            response = await test_client.post(f"{BASE}/techniques/{tech_a}/reorder", json={"direction": "down"})
            assert response.status_code == 201
            data = response.json()
            assert "techniques" in data
            items = {t["id"]: t["display_order"] for t in data["techniques"]}
            assert items[tech_a] == 2
            assert items[tech_b] == 1
        finally:
            await _delete_technique(asyncpg_conn, tech_a)
            await _delete_technique(asyncpg_conn, tech_b)

    async def test_requires_auth(self, unauthenticated_client):
        """Unauthenticated request returns 401."""
        response = await unauthenticated_client.post(f"{BASE}/techniques/999999/reorder", json={"direction": "up"})
        assert response.status_code == 401

    async def test_nonexistent_returns_404(self, test_client):
        """Reordering a non-existent technique returns 404."""
        response = await test_client.post(f"{BASE}/techniques/999999999/reorder", json={"direction": "up"})
        assert response.status_code == 404

    async def test_boundary_reorder_up_first_item(self, test_client, asyncpg_conn):
        """Pitfall #3: reordering first technique up returns 201 with unchanged order."""
        existing = await asyncpg_conn.fetch("SELECT id FROM content.movement_techniques")
        for row in existing:
            await asyncpg_conn.execute("DELETE FROM content.movement_techniques WHERE id = $1", row["id"])

        tech_a = await _insert_technique(asyncpg_conn, "TestTech_ATEC04_BoundU_A", 1)
        tech_b = await _insert_technique(asyncpg_conn, "TestTech_ATEC04_BoundU_B", 2)
        try:
            response = await test_client.post(f"{BASE}/techniques/{tech_a}/reorder", json={"direction": "up"})
            assert response.status_code == 201
            data = response.json()
            items = {t["id"]: t["display_order"] for t in data["techniques"]}
            assert items[tech_a] == 1
            assert items[tech_b] == 2
        finally:
            await _delete_technique(asyncpg_conn, tech_a)
            await _delete_technique(asyncpg_conn, tech_b)

    async def test_boundary_reorder_down_last_item(self, test_client, asyncpg_conn):
        """Pitfall #3: reordering last technique down returns 201 with unchanged order."""
        existing = await asyncpg_conn.fetch("SELECT id FROM content.movement_techniques")
        for row in existing:
            await asyncpg_conn.execute("DELETE FROM content.movement_techniques WHERE id = $1", row["id"])

        tech_a = await _insert_technique(asyncpg_conn, "TestTech_ATEC04_BoundD_A", 1)
        tech_b = await _insert_technique(asyncpg_conn, "TestTech_ATEC04_BoundD_B", 2)
        try:
            response = await test_client.post(f"{BASE}/techniques/{tech_b}/reorder", json={"direction": "down"})
            assert response.status_code == 201
            data = response.json()
            items = {t["id"]: t["display_order"] for t in data["techniques"]}
            assert items[tech_a] == 1
            assert items[tech_b] == 2
        finally:
            await _delete_technique(asyncpg_conn, tech_a)
            await _delete_technique(asyncpg_conn, tech_b)

    async def test_response_contains_full_list(self, test_client, asyncpg_conn):
        """Reorder response contains 'techniques' key with all techniques."""
        existing = await asyncpg_conn.fetch("SELECT id FROM content.movement_techniques")
        for row in existing:
            await asyncpg_conn.execute("DELETE FROM content.movement_techniques WHERE id = $1", row["id"])

        tech_a = await _insert_technique(asyncpg_conn, "TestTech_ATEC04_List_A", 1)
        tech_b = await _insert_technique(asyncpg_conn, "TestTech_ATEC04_List_B", 2)
        tech_c = await _insert_technique(asyncpg_conn, "TestTech_ATEC04_List_C", 3)
        try:
            response = await test_client.post(f"{BASE}/techniques/{tech_b}/reorder", json={"direction": "up"})
            assert response.status_code == 201
            data = response.json()
            assert "techniques" in data
            assert len(data["techniques"]) == 3
            returned_ids = {t["id"] for t in data["techniques"]}
            assert returned_ids == {tech_a, tech_b, tech_c}
        finally:
            await _delete_technique(asyncpg_conn, tech_a)
            await _delete_technique(asyncpg_conn, tech_b)
            await _delete_technique(asyncpg_conn, tech_c)

import pytest
from asyncpg import Connection
from genjishimada_sdk.difficulties import DIFFICULTY_RANGES_TOP
from litestar import Litestar
from litestar.status_codes import HTTP_200_OK, HTTP_201_CREATED, HTTP_204_NO_CONTENT, HTTP_400_BAD_REQUEST
from litestar.testing import AsyncTestClient
# ruff: noqa: D102, D103, ANN001, ANN201


class TestMapsEndpoints:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "code,expected,http_status",
        [
            ("AAAAA", False, 200),
            ("BBBBB", False, 200),
            ("1EASY", True, 200),
            ("BAD", False, 400),
            ("BADAGAIN", False, 400),
        ],
    )
    async def test_check_code_exists(
        self,
        test_client: AsyncTestClient[Litestar],
        code: str,
        expected: bool,
        http_status: int
    ) -> None:
        response = await test_client.get(f"/api/v3/maps/{code}/exists/")
        assert response.status_code == http_status
        if http_status != 400:
            assert response.json() == expected

    @pytest.mark.asyncio
    async def test_get_guides(self, test_client):
        response = await test_client.get(f"/api/v3/maps/2GUIDE/guides/")
        assert response.status_code == HTTP_200_OK
        assert len(response.json()) == 2
        for x in response.json():
            assert x["url"] is not None
            assert x["user_id"] is not None
            assert x["usernames"] is not None

    @pytest.mark.asyncio
    async def test_create_guides(self, test_client):
        response = await test_client.get(f"/api/v3/maps/GUIDE/guides/")
        assert response.status_code == HTTP_200_OK
        assert not response.json()


        new_data = {
            "user_id": 53,
            "url": "https://www.youtube.com/watch?v=ri76tCrDjXw"
        }
        response = await test_client.post(f"/api/v3/maps/GUIDE/guides/", json=new_data)
        assert response.status_code == HTTP_201_CREATED

        data = response.json()
        assert data["user_id"] == 53
        assert data["url"] == "https://www.youtube.com/watch?v=ri76tCrDjXw"

        response = await test_client.get(f"/api/v3/maps/GUIDE/guides/")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data[0]["user_id"] == 53
        assert data[0]["url"] == "https://www.youtube.com/watch?v=ri76tCrDjXw"
        assert data[0]["usernames"] == ['GuideMaker', 'GuideMaker']

    @pytest.mark.asyncio
    async def test_delete_guides(self, test_client):
        response = await test_client.get(f"/api/v3/maps/1GUIDE/guides/")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["url"] == 'https://www.youtube.com/watch?v=FJs41oeAnHU'
        assert data[0]["user_id"] == 53
        assert data[0]["usernames"] is not None

        response = await test_client.delete(f"/api/v3/maps/1GUIDE/guides/53")
        assert response.status_code == HTTP_204_NO_CONTENT

        response = await test_client.get(f"/api/v3/maps/1GUIDE/guides/")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert len(data) == 0

    @pytest.mark.asyncio
    async def test_edit_guides(self, test_client):
        response = await test_client.get(f"/api/v3/maps/3GUIDE/guides/")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["url"] == 'https://www.youtube.com/watch?v=GU8htjxY6ro'
        assert data[0]["user_id"] == 54
        assert data[0]["usernames"] is not None

        response = await test_client.patch(f"/api/v3/maps/3GUIDE/guides/54?url=https://www.youtube.com/watch?v=FJs41oeAnHU")
        assert response.status_code == HTTP_200_OK

        response = await test_client.get(f"/api/v3/maps/3GUIDE/guides/")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["url"] == 'https://www.youtube.com/watch?v=FJs41oeAnHU'
        assert data[0]["user_id"] == 54
        assert data[0]["usernames"] is not None

    @pytest.mark.asyncio
    async def test_search_maps_basic(self, test_client):
        response = await test_client.get(
            "/api/v3/maps/",
            params={
                "map_name": ["Hanamura"],
                "category": ["Classic"],
                "page_size": 10,
                "page_number": 1,
            },
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data
        assert all(item["map_name"] == "Hanamura" for item in data)
        assert all(item["category"] == "Classic" for item in data)

    @pytest.mark.asyncio
    async def test_search_maps_by_code(self, test_client):
        response = await test_client.get(
            "/api/v3/maps/",
            params={
                "code": "1EASY",
                "page_size": 10,
                "page_number": 1,
            },
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["code"] == "1EASY"

    @pytest.mark.asyncio
    async def test_search_maps_by_creator_name(self, test_client):
        response = await test_client.get(
            "/api/v3/maps/",
            params={
                "creator_names": ["Pixel"],
                "map_name": ["Hanamura"],
                "category": ["Classic"],
                "page_size": 10,
                "page_number": 1,
            },
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data
        assert all(
            any("Pixel" in creator["name"] for creator in item["creators"])
            for item in data
        )

    @pytest.mark.asyncio
    async def test_search_maps_by_creator_ids(self, test_client):
        response = await test_client.get(
            "/api/v3/maps/",
            params={
                "creator_ids": [100000000000000001],
                "map_name": ["Hanamura"],
                "category": ["Classic"],
                "page_size": 10,
                "page_number": 1,
            },
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data
        assert all(
            any(creator["id"] == 100000000000000001 for creator in item["creators"])
            for item in data
        )

    @pytest.mark.asyncio
    async def test_search_maps_mechanics_filter(self, test_client):
        response = await test_client.get(
            "/api/v3/maps/",
            params={
                "mechanics": ["Bhop"],
                "map_name": ["Hanamura"],
                "category": ["Classic"],
                "page_size": 10,
                "page_number": 1,
            },
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data
        assert "1EASY" in {item["code"] for item in data}
        assert all("Bhop" in item["mechanics"] for item in data)

    @pytest.mark.asyncio
    async def test_search_maps_restrictions_filter(self, test_client):
        response = await test_client.get(
            "/api/v3/maps/",
            params={
                "restrictions": ["Wall Climb"],
                "map_name": ["Hanamura"],
                "category": ["Classic"],
                "page_size": 10,
                "page_number": 1,
            },
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data
        assert "1EASY" in {item["code"] for item in data}
        assert all("Wall Climb" in item["restrictions"] for item in data)

    @pytest.mark.asyncio
    async def test_search_maps_completion_filter(self, test_client):
        response = await test_client.get(
            "/api/v3/maps/",
            params={
                "completion_filter": "With",
                "user_id": 200,
                "map_name": ["Hanamura"],
                "category": ["Classic"],
                "page_size": 50,
                "page_number": 1,
            },
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data
        assert all(item["time"] is not None for item in data)

        response = await test_client.get(
            "/api/v3/maps/",
            params={
                "completion_filter": "Without",
                "user_id": 200,
                "map_name": ["Hanamura"],
                "category": ["Classic"],
                "page_size": 50,
                "page_number": 1,
            },
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        codes = {item["code"] for item in data}
        assert "1EASY" not in codes

    @pytest.mark.asyncio
    async def test_search_maps_minimum_quality(self, test_client):
        response = await test_client.get(
            "/api/v3/maps/",
            params={
                "minimum_quality": 4,
                "map_name": ["Hanamura"],
                "category": ["Classic"],
                "page_size": 50,
                "page_number": 1,
            },
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data
        assert all(item["ratings"] is not None and item["ratings"] >= 4 for item in data)

    @pytest.mark.asyncio
    async def test_search_maps_medal_filter_with(self, test_client):
        response = await test_client.get(
            "/api/v3/maps/",
            params={
                "medal_filter": "With",
                "map_name": ["Hanamura"],
                "category": ["Classic"],
                "page_size": 10,
                "page_number": 1,
            },
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data
        assert "1EASY" in {item["code"] for item in data}
        assert all(item["medals"] is not None for item in data)

    @pytest.mark.asyncio
    async def test_search_maps_medal_filter_without(self, test_client):
        response = await test_client.get(
            "/api/v3/maps/",
            params={
                "medal_filter": "Without",
                "map_name": ["Hanamura"],
                "category": ["Classic"],
                "page_size": 10,
                "page_number": 1,
            },
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data
        assert "1EASY" not in {item["code"] for item in data}
        assert all(item["medals"] is None for item in data)

    @pytest.mark.asyncio
    async def test_search_maps_playtest_filter_only(self, test_client):
        response = await test_client.get(
            "/api/v3/maps/",
            params={
                "playtest_filter": "Only",
                "map_name": ["Hanamura"],
                "category": ["Classic"],
                "page_size": 50,
                "page_number": 1,
            },
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data
        codes = {item["code"] for item in data}
        assert codes.issubset({"PTEST1", "PTEST2", "PTEST3"})

    @pytest.mark.asyncio
    async def test_search_maps_playtest_filter_none(self, test_client):
        response = await test_client.get(
            "/api/v3/maps/",
            params={
                "playtest_filter": "None",
                "map_name": ["Hanamura"],
                "category": ["Classic"],
                "page_size": 10,
                "page_number": 1,
            },
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data
        assert all(item["playtest"] is None for item in data)
        codes = {item["code"] for item in data}
        assert not codes.intersection({"PTEST1", "PTEST2", "PTEST3"})

    @pytest.mark.asyncio
    async def test_search_maps_playtest_status_filter(self, test_client):
        response = await test_client.get(
            "/api/v3/maps/",
            params={
                "playtest_status": "In Progress",
                "map_name": ["Hanamura"],
                "category": ["Classic"],
                "page_size": 10,
                "page_number": 1,
            },
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data
        assert all(item["playtesting"] == "In Progress" for item in data)

    @pytest.mark.asyncio
    async def test_search_maps_playtest_thread_id(self, test_client):
        response = await test_client.get(
            "/api/v3/maps/",
            params={
                "playtest_thread_id": 2000000001,
                "map_name": ["Hanamura"],
                "category": ["Classic"],
                "page_size": 10,
                "page_number": 1,
            },
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data
        assert all(item["playtest"] is not None and item["playtest"]["thread_id"] == 2000000001 for item in data)
        assert {item["code"] for item in data}.issubset({"PTEST1"})

    @pytest.mark.asyncio
    async def test_search_maps_finalized_playtests(self, test_client):
        response = await test_client.get(
            "/api/v3/maps/",
            params={
                "finalized_playtests": True,
                "map_name": ["Hanamura"],
                "category": ["Classic"],
                "page_size": 10,
                "page_number": 1,
            },
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data
        assert {item["code"] for item in data}.issubset({"PTEST1", "PTEST2"})

    @pytest.mark.asyncio
    async def test_search_maps_difficulty_exact(self, test_client):
        response = await test_client.get(
            "/api/v3/maps/",
            params={
                "difficulty_exact": "Hell",
                "map_name": ["Hanamura"],
                "category": ["Classic"],
                "page_size": 10,
                "page_number": 1,
            },
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data
        assert all(item["difficulty"] == "Hell" for item in data)

    @pytest.mark.asyncio
    async def test_search_maps_difficulty_range(self, test_client):
        response = await test_client.get(
            "/api/v3/maps/",
            params={
                "difficulty_range_min": "Medium",
                "difficulty_range_max": "Hard",
                "map_name": ["Hanamura"],
                "category": ["Classic"],
                "page_size": 10,
                "page_number": 1,
            },
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data
        raw_min = DIFFICULTY_RANGES_TOP["Medium"][0]
        raw_max = DIFFICULTY_RANGES_TOP["Hard"][1]
        assert all(raw_min <= item["raw_difficulty"] <= raw_max for item in data)

    @pytest.mark.asyncio
    async def test_search_maps_visibility_filters(self, test_client):
        response = await test_client.get(
            "/api/v3/maps/",
            params={
                "archived": True,
                "map_name": ["Hanamura"],
                "category": ["Classic"],
                "page_size": 10,
                "page_number": 1,
            },
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data
        assert "1MEDIU" in {item["code"] for item in data}
        assert all(item["archived"] is True for item in data)

        response = await test_client.get(
            "/api/v3/maps/",
            params={
                "hidden": True,
                "map_name": ["Hanamura"],
                "category": ["Classic"],
                "page_size": 10,
                "page_number": 1,
            },
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data
        assert "9EASY" in {item["code"] for item in data}
        assert all(item["hidden"] is True for item in data)

        response = await test_client.get(
            "/api/v3/maps/",
            params={
                "official": False,
                "map_name": ["Hanamura"],
                "category": ["Classic"],
                "page_size": 10,
                "page_number": 1,
            },
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data
        assert "8EASY" in {item["code"] for item in data}
        assert all(item["official"] is False for item in data)

    @pytest.mark.asyncio
    async def test_search_maps_force_filters(self, test_client):
        response = await test_client.get(
            "/api/v3/maps/",
            params={
                "code": "1EASY",
                "mechanics": ["Dash"],
                "map_name": ["Hanamura"],
                "category": ["Classic"],
                "page_size": 10,
                "page_number": 1,
            },
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["code"] == "1EASY"

        response = await test_client.get(
            "/api/v3/maps/",
            params={
                "code": "1EASY",
                "mechanics": ["Dash"],
                "map_name": ["Hanamura"],
                "category": ["Classic"],
                "force_filters": True,
                "page_size": 10,
                "page_number": 1,
            },
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data == []

    @pytest.mark.asyncio
    async def test_search_maps_return_all(self, test_client):
        response = await test_client.get(
            "/api/v3/maps/",
            params={
                "map_name": ["Hanamura"],
                "category": ["Classic"],
                "return_all": True,
                "page_size": 10,
                "page_number": 1,
            },
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert len(data) > 10

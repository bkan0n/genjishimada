"""End-to-end quest lifecycle tests."""

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.domain_store,
]


@pytest.mark.asyncio
async def test_full_quest_lifecycle(test_client, create_test_user):
    """Fetch quests and attempt claim on incomplete quest."""
    user_id = await create_test_user()

    response = await test_client.get(
        "/api/v3/store/quests",
        params={"user_id": user_id},
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data["quests"]) == 6

    progress_id = data["quests"][0]["progress_id"]

    claim_response = await test_client.post(
        f"/api/v3/store/quests/{progress_id}/claim",
        json={"user_id": user_id},
    )

    assert claim_response.status_code in (400, 404, 409)

"""Rename behavior against real PostgreSQL and an in-memory object store."""

import io

import pytest
from botocore.exceptions import ClientError
from litestar.datastructures import State

from repository.map_content_repository import MapContentRepository
from services.image_storage_service import ImageStorageService
from services.map_content_service import MapContentService

pytestmark = [pytest.mark.domain_maps, pytest.mark.database]


class ObjectStore:
    def __init__(self):
        self.objects = {}
        self.copies = []
        self.fail_copy = False

    def get_object(self, *, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self.objects[Key])}

    def copy_object(self, *, Bucket, Key, CopySource):
        if self.fail_copy:
            raise RuntimeError("storage unavailable")
        self.objects[Key] = self.objects[CopySource["Key"]]
        self.copies.append((CopySource["Key"], Key))

    def upload_fileobj(self, fileobj, bucket, key, ExtraArgs):
        self.objects[key] = fileobj.read()


@pytest.fixture
def rename_service(asyncpg_pool):
    storage = ImageStorageService.__new__(ImageStorageService)
    storage.client = ObjectStore()
    service = MapContentService(asyncpg_pool, State(), MapContentRepository(asyncpg_pool), storage)
    return service, storage.client


async def test_case_correction_preserves_course_and_reserves_old_name(rename_service, asyncpg_conn, create_test_map):
    service, objects = rename_service
    old = "WATCHPOINT: GRIMSVOTN"
    new = "Watchpoint: Grimsvotn"
    await asyncpg_conn.execute("INSERT INTO maps.names(name) VALUES($1)", old)
    map_id = await create_test_map(map_name=old)
    objects.objects["assets/map_banners/watchpointgrimsvotn.png"] = b"existing"

    result = await service.rename_map(old, new)

    assert result == {"old_name": old, "name": new, "renamed": True}
    assert await asyncpg_conn.fetchval("SELECT map_name FROM core.maps WHERE id=$1", map_id) == new
    assert (
        await asyncpg_conn.fetchval("SELECT canonical_name FROM maps.name_aliases WHERE previous_name=$1", old) == new
    )
    assert objects.copies == []


async def test_aliases_keep_mastery_and_search_filters_working(rename_service, asyncpg_conn, create_test_map):
    from repository.maps_repository import MapsRepository
    from services.maps_service import MapsService
    from utilities.map_search import MapSearchFilters

    service, _ = rename_service
    map_id = await create_test_map(map_name="Hanamura")
    await service.rename_map("Hanamura", "New Hanamura")
    maps = MapsService(service._pool, State(), MapsRepository(service._pool))
    result = await maps.fetch_maps(filters=MapSearchFilters(map_name=["Hanamura"], return_all=True))
    assert len(result) == 1
    assert result[0].map_name == "New Hanamura"
    assert await asyncpg_conn.fetchval("SELECT map_name FROM core.maps WHERE id=$1", map_id) == "New Hanamura"


async def test_missing_source_art_does_not_adopt_unowned_destination(rename_service):
    from utilities.errors import CustomHTTPException

    service, objects = rename_service
    objects.objects["assets/map_banners/unownedtarget.png"] = b"someone else's image"
    with pytest.raises(CustomHTTPException) as error:
        await service.rename_map("Hanamura", "Unowned Target")
    assert error.value.status_code == 409
    assert objects.copies == []


@pytest.mark.parametrize("new", ["New Map", "Hanamúra", "Hana/mura: Revised"])
async def test_renames_preserve_all_art_families_and_leave_originals(rename_service, asyncpg_conn, new):
    service, objects = rename_service
    old_keys = ImageStorageService.map_artwork_keys("Hanamura")
    new_keys = ImageStorageService.map_artwork_keys(new)
    for index, key in enumerate(old_keys):
        objects.objects[key] = f"art-{index}".encode()
    await service.rename_map("Hanamura", new)
    for source, destination in zip(old_keys, new_keys, strict=True):
        assert objects.objects[source] == objects.objects[destination]


async def test_repeated_renames_flatten_aliases_and_rename_back_refreshes_art(rename_service, asyncpg_conn):
    service, objects = rename_service
    objects.objects["assets/map_banners/hanamura.png"] = b"first"
    await service.rename_map("Hanamura", "Second Label")
    await service.create_map("Second Label", b"latest", "image/png")
    await service.rename_map("Second Label", "Third Label")
    await service.rename_map("Third Label", "Hanamura")
    aliases = dict(await asyncpg_conn.fetch("SELECT previous_name, canonical_name FROM maps.name_aliases"))
    assert aliases == {"Second Label": "Hanamura", "Third Label": "Hanamura"}
    assert objects.objects["assets/map_banners/hanamura.png"] == b"latest"


@pytest.mark.parametrize("name", ["Busan", "Busan!", "Busa n", "Old Label", "Old-Label"])
async def test_conflicting_names_or_owned_art_are_rejected(rename_service, asyncpg_conn, name):
    from utilities.errors import CustomHTTPException

    service, objects = rename_service
    await service.rename_map("Busan", "Old Label")
    with pytest.raises(CustomHTTPException) as error:
        await service.rename_map("Hanamura", name)
    assert error.value.status_code == 409
    assert await asyncpg_conn.fetchval("SELECT name FROM maps.names WHERE name='Hanamura'") == "Hanamura"
    assert objects.copies == []


async def test_retired_names_cannot_create_or_replace_banners(rename_service, asyncpg_conn):
    from utilities.errors import CustomHTTPException

    service, objects = rename_service
    await service.rename_map("Hanamura", "Updated Hanamura")
    with pytest.raises(CustomHTTPException) as error:
        await service.create_map("Hanamura", b"wrong", "image/png")
    assert error.value.status_code == 409
    assert "Updated Hanamura" in error.value.detail
    assert not objects.objects


@pytest.mark.parametrize(
    "old,name,status", [("Hanamura", "", 422), ("Hanamura", "✨", 422), ("Missing", "Hanamura", 404)]
)
async def test_invalid_or_missing_sources_do_not_mutate(rename_service, old, name, status):
    from utilities.errors import CustomHTTPException

    service, objects = rename_service
    with pytest.raises(CustomHTTPException) as error:
        await service.rename_map(old, name)
    assert error.value.status_code == status
    assert objects.copies == []


async def test_same_name_is_idempotent_but_alias_is_not_a_rename_source(rename_service):
    from utilities.errors import CustomHTTPException

    service, objects = rename_service
    assert await service.rename_map("Hanamura", "Hanamura") == {
        "old_name": "Hanamura",
        "name": "Hanamura",
        "renamed": False,
    }
    await service.rename_map("Hanamura", "Changed Hanamura")
    with pytest.raises(CustomHTTPException) as error:
        await service.rename_map("Hanamura", "Changed Hanamura")
    assert error.value.status_code == 404


async def test_asset_conflict_checks_all_objects_before_copying(rename_service, asyncpg_conn):
    from utilities.errors import CustomHTTPException

    service, objects = rename_service
    objects.objects["assets/map_banners/hanamura.png"] = b"banner"
    objects.objects["assets/mastery/hanamura_rookie.webp"] = b"badge"
    objects.objects["assets/mastery/target_rookie.webp"] = b"unowned"
    with pytest.raises(CustomHTTPException) as error:
        await service.rename_map("Hanamura", "Target")
    assert error.value.status_code == 409
    assert objects.copies == []
    assert "assets/map_banners/target.png" not in objects.objects
    assert await asyncpg_conn.fetchval("SELECT count(*) FROM maps.name_aliases") == 0


async def test_partial_copy_failure_can_retry_without_changing_source(rename_service, asyncpg_conn):
    service, objects = rename_service
    objects.objects["assets/map_banners/hanamura.png"] = b"banner"
    objects.objects["assets/mastery/hanamura_rookie.webp"] = b"badge"
    original = objects.copy_object

    def fail_second(**kwargs):
        if kwargs["Key"].endswith(".webp"):
            raise RuntimeError("storage unavailable")
        original(**kwargs)

    objects.copy_object = fail_second
    with pytest.raises(RuntimeError):
        await service.rename_map("Hanamura", "Target")
    assert await asyncpg_conn.fetchval("SELECT name FROM maps.names WHERE name='Hanamura'") == "Hanamura"
    assert await asyncpg_conn.fetchval("SELECT count(*) FROM maps.name_aliases") == 0
    objects.copy_object = original
    await service.rename_map("Hanamura", "Target")
    assert objects.objects["assets/map_banners/hanamura.png"] == b"banner"
    assert objects.objects["assets/mastery/target_rookie.webp"] == b"badge"
    assert objects.copies.count(("assets/map_banners/hanamura.png", "assets/map_banners/target.png")) == 1


async def test_permission_errors_are_not_treated_as_missing_art(rename_service, asyncpg_conn):
    service, objects = rename_service

    def denied(**kwargs):
        raise ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject")

    objects.get_object = denied
    with pytest.raises(ClientError):
        await service.rename_map("Hanamura", "Target")
    assert await asyncpg_conn.fetchval("SELECT name FROM maps.names WHERE name='Hanamura'") == "Hanamura"


async def test_equipped_mastery_and_eligibility_survive_rename(
    rename_service, asyncpg_conn, asyncpg_pool, create_test_user
):
    from genjishimada_sdk.rank_card import RankCardBadgeSettings
    from repository.rank_card_repository import RankCardRepository
    from services.rank_card_service import RankCardService
    from utilities.shared_queries import get_map_mastery_data_raw, get_map_mastery_data

    service, objects = rename_service
    user = await create_test_user()
    await asyncpg_conn.execute(
        "INSERT INTO maps.mastery(user_id,map_name,medal) VALUES($1,'Hanamura','Explorer')", user
    )
    slots = {
        f"badge_{field}{slot}": value
        for slot in range(1, 7)
        for field, value in [("type", "mastery"), ("name", "Hanamura")]
    }
    cards = RankCardService(asyncpg_pool, State(), RankCardRepository(asyncpg_pool))
    await cards.set_badges(user, RankCardBadgeSettings(**slots))
    await service.rename_map("Hanamura", "Fresh Hanamura")
    row = await asyncpg_conn.fetchrow("SELECT * FROM rank_card.badges WHERE user_id=$1", user)
    assert all(row[f"badge_name{slot}"] == "Fresh Hanamura" for slot in range(1, 7))
    assert (
        await asyncpg_conn.fetchval(
            "SELECT medal FROM maps.mastery WHERE user_id=$1 AND map_name='Fresh Hanamura'", user
        )
        == "Explorer"
    )
    # An already-open editor still submits the old name; only mastery slots change.
    await cards.set_badges(
        user,
        RankCardBadgeSettings(
            badge_name1="Hanamura", badge_type1="mastery", badge_name2="Hanamura", badge_type2="spray"
        ),
    )
    badges = await cards.get_badges(user)
    assert badges.badge_name1 == "Fresh Hanamura"
    assert badges.badge_name2 == "Hanamura"
    assert badges.badge_url1.endswith("fresh_hanamura_placeholder.webp")
    assert (await get_map_mastery_data_raw(asyncpg_conn, user, "Hanamura"))[0]["map_name"] == "Fresh Hanamura"
    await service.rename_map("Adlersbrunn", "Halloween Town")
    assert not await get_map_mastery_data_raw(asyncpg_conn, user, "Halloween Town")
    assert not await get_map_mastery_data(asyncpg_conn, user, "Adlersbrunn")
    assert await asyncpg_conn.fetchval("SELECT mastery_enabled FROM maps.names WHERE name='Halloween Town'") is False


async def test_http_rename_preserves_history_and_checks_scope(test_client, asyncpg_conn, monkeypatch):
    objects = ObjectStore()
    monkeypatch.setattr(ImageStorageService, "__init__", lambda self: setattr(self, "client", objects))
    jobs_before = await asyncpg_conn.fetchval("SELECT count(*) FROM public.jobs")
    response = await test_client.patch("/api/v3/content/maps", json={"old_name": "Hanamura", "name": "Hanamúra"})
    assert response.status_code == 200, response.text
    assert response.json() == {"old_name": "Hanamura", "name": "Hanamúra", "renamed": True}
    assert await asyncpg_conn.fetchval("SELECT count(*) FROM public.jobs") == jobs_before
    listed = await test_client.get("/api/v3/utilities/map-names")
    assert "Hanamúra" in listed.json() and "Hanamura" not in listed.json()
    await asyncpg_conn.execute(
        "UPDATE public.api_tokens SET is_superuser=false, scopes=ARRAY['maps:read'] WHERE api_key='testing'"
    )
    denied = await test_client.patch("/api/v3/content/maps", json={"old_name": "Hanamúra", "name": "Other Name"})
    assert denied.status_code == 401, denied.text
    assert "content:admin" in denied.json()["error"]


async def test_http_rename_requires_auth(unauthenticated_client):
    response = await unauthenticated_client.patch(
        "/api/v3/content/maps", json={"old_name": "Hanamura", "name": "Other Name"}
    )
    assert response.status_code == 401


async def test_pending_proposal_keeps_submitted_name_and_accepts_after_rename(
    test_client, rename_service, asyncpg_conn, create_test_user, create_test_map, unique_map_code
):
    user = await create_test_user()
    await create_test_map(code=unique_map_code, map_name="Busan")
    response = await test_client.post(
        "/api/v3/maps/map-edits/",
        json={"code": unique_map_code, "created_by": user, "reason": "Map correction", "map_name": "Hanamura"},
    )
    assert response.status_code == 201, response.text
    edit_id = response.json()["id"]
    service, _ = rename_service
    await service.rename_map("Hanamura", "Current Hanamura")
    response = await test_client.put(
        f"/api/v3/maps/map-edits/{edit_id}/resolve",
        json={"accepted": True, "resolved_by": user, "send_to_playtest": False},
    )
    assert response.status_code == 204, response.text
    assert (
        await asyncpg_conn.fetchval("SELECT map_name FROM core.maps WHERE code=$1", unique_map_code)
        == "Current Hanamura"
    )
    proposal = await asyncpg_conn.fetchval("SELECT proposed_changes FROM maps.edit_requests WHERE id=$1", edit_id)
    assert proposal["map_name"] == "Hanamura"


async def test_queue_snapshot_and_original_effect_key_survive_rename(
    rename_service, asyncpg_conn, asyncpg_pool, create_test_user, create_test_map, create_test_completion
):
    from datetime import timedelta
    from uuid import uuid4
    import msgspec
    from genjishimada_sdk.maps import MapMasteryCreateRequest
    from genjishimada_sdk.queue import JobContext, JobEnvelope
    from genjishimada_sdk.queue_store import enqueue_job, save_snapshot, apply_mutation
    from genjishimada_sdk.queue_worker import FencedQueries
    from pgqueuer.ports.repository import EntrypointExecutionParameter
    from repository.maps_repository import MapsRepository
    from services.maps_service import MapsService
    from utilities.transactions import transaction

    user = await create_test_user()
    for _ in range(5):
        map_id = await create_test_map(map_name="Hanamura")
        await create_test_completion(user, map_id)
    event = "api.completion.verification"
    async with asyncpg_conn.transaction():
        public = await enqueue_job(asyncpg_conn, event_name=event, payload={"completion_id": 1}, event_key=str(uuid4()))
    queries = FencedQueries.from_asyncpg_connection(asyncpg_conn)
    jobs = await queries.dequeue(1, {event: EntrypointExecutionParameter(1)}, uuid4(), 2, timedelta(seconds=60))
    job = jobs[0]
    envelope = msgspec.json.decode(job.payload, type=JobEnvelope)
    context = JobContext(
        public.id, event, envelope.event_key, job.id, job.queue_manager_id, job.updated, envelope.payload
    )
    original = [{"map_name": "Hanamura", "amount": 5}]
    key = f"mastery-plan:{user}"
    await save_snapshot(asyncpg_conn, context, key, original)
    service, _ = rename_service
    await service.rename_map("Hanamura", "Queued Hanamura")
    snapshot = await save_snapshot(asyncpg_conn, context, key, [{"map_name": "Queued Hanamura", "amount": 5}])
    assert snapshot == original
    maps = MapsService(asyncpg_pool, State(), MapsRepository(asyncpg_pool))
    request = MapMasteryCreateRequest(user, snapshot[0]["map_name"], "Rookie")
    calls = 0

    async def mutate():
        nonlocal calls
        calls += 1
        return msgspec.to_builtins(await maps.update_mastery(request))

    # The worker's immutable old spelling remains its effect identity.
    effect = f"mastery:{user}:Hanamura"
    async with transaction(asyncpg_pool, conn=asyncpg_conn):
        first = await apply_mutation(asyncpg_conn, context, effect, "original-request", mutate)
    async with transaction(asyncpg_pool, conn=asyncpg_conn):
        replay = await apply_mutation(asyncpg_conn, context, effect, "original-request", mutate)
    assert calls == 1
    assert replay == first and first["map_name"] == "Queued Hanamura" and first["medal"] == "Rookie"
    assert request.map_name == "Hanamura"
    assert (
        await asyncpg_conn.fetchval(
            "SELECT count(*) FROM public.job_effects WHERE job_id=$1 AND effect_key=$2", public.id, effect
        )
        == 1
    )
    assert (
        await asyncpg_conn.fetchval(
            "SELECT result FROM public.job_effects WHERE job_id=$1 AND effect_key=$2", public.id, "snapshot:" + key
        )
        == original
    )


async def test_create_cannot_claim_a_key_during_rename(rename_service, asyncpg_conn, monkeypatch):
    import asyncio
    import threading
    from utilities.errors import CustomHTTPException

    service, objects = rename_service
    started, release = threading.Event(), threading.Event()
    original = service._image_svc.preserve_map_artwork

    def delayed(*args):
        started.set()
        if not release.wait(5):
            raise TimeoutError("test failed to release storage")
        return original(*args)

    monkeypatch.setattr(service._image_svc, "preserve_map_artwork", delayed)
    rename = asyncio.create_task(service.rename_map("Hanamura", "Race Target"))
    assert await asyncio.to_thread(started.wait, 3)
    create = asyncio.create_task(service.create_map("Race-Target", b"attacker", "image/png"))
    try:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(create), 0.1)
    finally:
        release.set()
    await rename
    with pytest.raises(CustomHTTPException) as error:
        await create
    assert error.value.status_code == 422
    assert await asyncpg_conn.fetchval("SELECT count(*) FROM maps.names WHERE name='Race-Target'") == 0
    assert not objects.objects


async def test_cancelled_storage_keeps_ownership_lock_until_io_finishes(rename_service, monkeypatch):
    import asyncio
    import threading

    service, _ = rename_service
    started, release = threading.Event(), threading.Event()
    original = service._image_svc.preserve_map_artwork

    def delayed(*args):
        started.set()
        if not release.wait(5):
            raise TimeoutError("test failed to release storage")
        return original(*args)

    monkeypatch.setattr(service._image_svc, "preserve_map_artwork", delayed)
    rename = asyncio.create_task(service.rename_map("Hanamura", "Cancellation Target"))
    assert await asyncio.to_thread(started.wait, 3)
    rename.cancel()
    create = asyncio.create_task(service.create_map("Cancellation Target", b"new", "image/png"))
    try:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(create), 0.1)
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await rename
        await create


async def test_equal_banner_key_still_copies_different_mastery_key(rename_service):
    service, objects = rename_service
    objects.objects["assets/map_banners/hanamura.png"] = b"banner"
    objects.objects["assets/mastery/hanamura_rookie.webp"] = b"mastery"
    await service.rename_map("Hanamura", "Hana mura")
    assert objects.copies == [("assets/mastery/hanamura_rookie.webp", "assets/mastery/hana_mura_rookie.webp")]
    assert objects.objects["assets/map_banners/hanamura.png"] == b"banner"


async def test_rename_waits_for_resolved_course_write(
    rename_service, asyncpg_pool, asyncpg_conn, create_test_map, unique_map_code, monkeypatch
):
    import asyncio
    from genjishimada_sdk.maps import MapPatchRequest
    from repository.maps_repository import MapsRepository
    from services.maps_service import MapsService

    service, _ = rename_service
    map_id = await create_test_map(map_name="Busan", code=unique_map_code)
    maps = MapsService(asyncpg_pool, State(), MapsRepository(asyncpg_pool))
    resolved, release = asyncio.Event(), asyncio.Event()
    original = maps._map_names_repo.resolve_name

    async def delayed(name):
        result = await original(name)
        resolved.set()
        await release.wait()
        return result

    monkeypatch.setattr(maps._map_names_repo, "resolve_name", delayed)
    update = asyncio.create_task(maps.update_map(unique_map_code, MapPatchRequest(map_name="Hanamura")))
    await asyncio.wait_for(resolved.wait(), 3)
    rename = asyncio.create_task(service.rename_map("Hanamura", "After Course Write"))
    try:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(rename), 0.1)
    finally:
        release.set()
    await update
    await rename
    assert await asyncpg_conn.fetchval("SELECT map_name FROM core.maps WHERE id=$1", map_id) == "After Course Write"


async def test_db_failure_after_copy_preserves_source_and_alias_state(rename_service, asyncpg_conn, monkeypatch):
    service, objects = rename_service
    objects.objects["assets/map_banners/hanamura.png"] = b"original"
    original = service._map_content_repo.rename_map_name

    async def failed_commit(*args):
        await original(*args)
        raise RuntimeError("database write failed")

    monkeypatch.setattr(service._map_content_repo, "rename_map_name", failed_commit)
    with pytest.raises(RuntimeError):
        await service.rename_map("Hanamura", "Copied Only")
    assert await asyncpg_conn.fetchval("SELECT name FROM maps.names WHERE name='Hanamura'") == "Hanamura"
    assert await asyncpg_conn.fetchval("SELECT count(*) FROM maps.name_aliases") == 0
    assert objects.objects["assets/map_banners/hanamura.png"] == b"original"
    assert objects.objects["assets/map_banners/copiedonly.png"] == b"original"


async def test_exact_old_name_transform_does_not_fuzzily_choose_another_map(rename_service, asyncpg_pool):
    from repository.autocomplete_repository import AutocompleteRepository

    service, _ = rename_service
    await service.rename_map("Hanamura", "Entirely Different Label")
    repository = AutocompleteRepository(asyncpg_pool)
    assert await repository.transform_map_names("Hanamura") == '"Entirely Different Label"'

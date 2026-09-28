"""Database factories using a connection supplied by the calling test.

The fixture adapters own random data and per-test uniqueness tracking. These
helpers never open connections or pools; test infrastructure owns their lifetime.
"""

import base64
import datetime as dt
import hashlib
from collections.abc import Callable
from typing import Any, TypeVar
from uuid import UUID

import asyncpg
from faker import Faker
from genjishimada_sdk import difficulties

GUILD_ID = 100000000000000001
# bcrypt hash of the existing factory default, "password123". Reusing this
# test-only value avoids hashing the same setup password for every fixture call.
DEFAULT_PASSWORD_HASH = "$2b$12$8bfXwE4uyJHhJoWjZrpnFea2.vgJifeSbFCYr8hOmMjs9QwVLqn0i"

T = TypeVar("T")


def new_uuid(fake: Faker) -> UUID:
    """Generate a UUID from the test's seeded random source."""
    return UUID(int=fake.random.getrandbits(128), version=4)


def unique_value(used: set[T], generate: Callable[[], T]) -> T:
    """Reserve a value that has not been used by this test."""
    while True:
        value = generate()
        if value not in used:
            used.add(value)
            return value


def snowflake(fake: Faker, used: set[int]) -> int:
    """Reserve a Discord-style snowflake within this test."""
    return unique_value(used, lambda: fake.random_int(min=100000000000000000, max=999999999999999999))


def map_code(fake: Faker, used: set[str]) -> str:
    """Reserve a six-character map code within this test."""
    return unique_value(used, lambda: f"T{new_uuid(fake).hex[:5].upper()}")


def hex_digest(fake: Faker, used: set[str]) -> str:
    """Reserve a SHA256-shaped token within this test."""
    return unique_value(used, lambda: hashlib.sha256(new_uuid(fake).bytes).hexdigest())


async def create_user(
    conn: asyncpg.Connection,
    nickname: str | None = None,
    *,
    fake: Faker,
    global_user_id_tracker: set[int],
) -> int:
    """Insert a user and return its generated ID."""
    if nickname is None:
        nickname = fake.user_name()

    user_id = snowflake(fake, global_user_id_tracker)

    await conn.execute(
        """
        INSERT INTO core.users (id, nickname, global_name)
        VALUES ($1, $2, $3)
        """,
        user_id,
        nickname,
        nickname,
    )
    return user_id


async def create_playtest(
    conn: asyncpg.Connection,
    map_id: int,
    thread_id: int | None = None,
    *,
    fake: Faker,
    global_thread_id_tracker: set[int],
    **overrides: Any,
) -> int:
    """Insert playtest metadata with the existing test defaults."""
    if thread_id is None:
        thread_id = snowflake(fake, global_thread_id_tracker)
    global_thread_id_tracker.add(thread_id)

    # Default values
    data = {
        "verification_id": None,
        "initial_difficulty": 5.0,  # Default mid-range difficulty
        "completed": False,
    }

    # Apply overrides
    data.update(overrides)

    playtest_id = await conn.fetchval(
        """
        INSERT INTO playtests.meta (
            thread_id, map_id, verification_id, initial_difficulty, completed
        )
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id
        """,
        thread_id,
        map_id,
        data["verification_id"],
        data["initial_difficulty"],
        data["completed"],
    )
    return playtest_id


async def create_edit_request(
    conn: asyncpg.Connection,
    map_id: int,
    code: str,
    created_by: int,
    *,
    fake: Faker,
    **overrides: Any,
) -> int:
    """Insert an edit request and return its ID."""
    data = {
        "proposed_changes": {"difficulty": "Hard", "checkpoints": 10},
        "reason": fake.sentence(nb_words=10),
    }

    # Apply overrides
    data.update(overrides)

    edit_id = await conn.fetchval(
        """
        INSERT INTO maps.edit_requests (
            map_id, code, proposed_changes, reason, created_by
        )
        VALUES ($1, $2, $3::jsonb, $4, $5)
        RETURNING id
        """,
        map_id,
        code,
        data["proposed_changes"],
        data["reason"],
        created_by,
    )
    return edit_id


async def create_email_user(
    conn: asyncpg.Connection,
    nickname: str | None = None,
    email: str | None = None,
    password_hash: str | None = None,
    email_verified: bool = False,
    *,
    fake: Faker,
    global_user_id_tracker: set[int],
    global_email_tracker: set[str],
) -> tuple[int, str, str]:
    """Insert a user with email authentication and return its credentials."""
    if nickname is None:
        nickname = fake.user_name()

    if email is None:
        email = unique_value(global_email_tracker, lambda: f"test-{new_uuid(fake).hex[:8]}@example.com")
    global_email_tracker.add(email)

    if password_hash is None:
        password_hash = DEFAULT_PASSWORD_HASH

    user_id = snowflake(fake, global_user_id_tracker)

    await conn.execute(
        """
        INSERT INTO core.users (id, nickname, global_name)
        VALUES ($1, $2, $3)
        """,
        user_id,
        nickname,
        nickname,
    )

    # Create email auth
    if email_verified:
        await conn.execute(
            """
            INSERT INTO users.email_auth (user_id, email, password_hash, email_verified_at)
            VALUES ($1, $2, $3, now())
            """,
            user_id,
            email,
            password_hash,
        )
    else:
        await conn.execute(
            """
            INSERT INTO users.email_auth (user_id, email, password_hash)
            VALUES ($1, $2, $3)
            """,
            user_id,
            email,
            password_hash,
        )

    return user_id, email, password_hash


async def create_session(
    conn: asyncpg.Connection,
    user_id: int | None = None,
    payload: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    *,
    fake: Faker,
    global_session_id_tracker: set[str],
) -> str:
    """Insert an authenticated or anonymous session and return its ID."""
    session_id = unique_value(global_session_id_tracker, lambda: new_uuid(fake).hex)

    if payload is None:
        # Create a simple base64-encoded payload
        payload = base64.b64encode(f'{{"session_id": "{session_id}"}}'.encode()).decode()

    if ip_address is None:
        ip_address = fake.ipv4()

    if user_agent is None:
        user_agent = fake.user_agent()

    await conn.execute(
        """
        INSERT INTO users.sessions (id, user_id, payload, last_activity, ip_address, user_agent)
        VALUES ($1, $2, $3, now(), $4, $5)
        """,
        session_id,
        user_id,
        payload,
        ip_address,
        user_agent,
    )

    return session_id


async def create_change_request(
    conn: asyncpg.Connection,
    code: str,
    user_id: int,
    thread_id: int | None = None,
    content: str | None = None,
    change_request_type: str | None = None,
    creator_mentions: str | None = None,
    *,
    fake: Faker,
    global_thread_id_tracker: set[int],
    **overrides: Any,
) -> int:
    """Insert a change request and return its thread ID."""
    if thread_id is None:
        thread_id = snowflake(fake, global_thread_id_tracker)
    global_thread_id_tracker.add(thread_id)

    # Default values
    if content is None:
        content = fake.sentence(nb_words=20)

    if change_request_type is None:
        change_request_type = fake.random_element(
            elements=["Bug Fix", "Feature Request", "Improvement", "Balance Change"]
        )

    if creator_mentions is None:
        creator_mentions = ""

    data = {
        "content": content,
        "change_request_type": change_request_type,
        "creator_mentions": creator_mentions,
        "resolved": False,
        "alerted": False,
    }

    # Apply overrides
    data.update(overrides)

    await conn.execute(
        """
        INSERT INTO change_requests (
            thread_id, code, user_id, content, change_request_type,
            creator_mentions, resolved, alerted
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
        thread_id,
        code,
        user_id,
        data["content"],
        data["change_request_type"],
        data["creator_mentions"],
        data["resolved"],
        data["alerted"],
    )
    return thread_id


async def create_job(
    conn: asyncpg.Connection,
    job_id: UUID | None = None,
    action: str | None = None,
    status: str = "queued",
    error_code: str | None = None,
    error_msg: str | None = None,
    *,
    fake: Faker,
    global_job_id_tracker: set[UUID],
    **overrides: Any,
) -> UUID:
    """Insert a job and return its ID."""
    if job_id is None:
        job_id = unique_value(global_job_id_tracker, lambda: new_uuid(fake))
    global_job_id_tracker.add(job_id)

    # Generate action if not provided
    if action is None:
        action = fake.word()

    data = {
        "action": action,
        "status": status,
        "error_code": error_code,
        "error_msg": error_msg,
        "attempts": 0,
    }

    # Apply overrides
    data.update(overrides)

    await conn.execute(
        """
        INSERT INTO public.jobs (
            id, action, status, error_code, error_msg, attempts
        )
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        job_id,
        data["action"],
        data["status"],
        data["error_code"],
        data["error_msg"],
        data["attempts"],
    )
    return job_id


async def create_claim(
    conn: asyncpg.Connection,
    key: str | None = None,
    *,
    fake: Faker,
    global_idempotency_key_tracker: set[str],
) -> str:
    """Insert an idempotency claim and return its key."""
    if key is None:
        key = unique_value(global_idempotency_key_tracker, lambda: f"idem-{new_uuid(fake).hex[:16]}")
    global_idempotency_key_tracker.add(key)

    await conn.execute(
        """
        INSERT INTO public.processed_messages (idempotency_key)
        VALUES ($1)
        """,
        key,
    )
    return key


async def create_newsfeed_event(
    conn: asyncpg.Connection,
    timestamp: Any | None = None,
    payload: dict | None = None,
    *,
    fake: Faker,
) -> int:
    """Insert a newsfeed event with optional timestamp and payload."""
    # Generate timestamp if not provided
    if timestamp is None:
        timestamp = dt.datetime.now(dt.timezone.utc)

    # Generate payload if not provided
    if payload is None:
        payload = {
            "type": fake.word(),
            "data": fake.sentence(),
        }

    event_id = await conn.fetchval(
        """
        INSERT INTO public.newsfeed (timestamp, payload)
        VALUES ($1, $2::jsonb)
        RETURNING id
        """,
        timestamp,
        payload,
    )
    return event_id


async def create_notification_event(
    conn: asyncpg.Connection,
    user_id: int | None = None,
    event_type: str | None = None,
    title: str | None = None,
    body: str | None = None,
    metadata: dict[str, Any] | None = None,
    *,
    fake: Faker,
    global_user_id_tracker: set[int],
) -> int:
    """Insert a notification, creating its recipient when needed."""
    if user_id is None:
        user_id = snowflake(fake, global_user_id_tracker)

        # Create user if we generated a new ID
        await conn.execute(
            """
            INSERT INTO core.users (id, nickname, global_name)
            VALUES ($1, $2, $3)
            """,
            user_id,
            fake.user_name(),
            fake.user_name(),
        )

    # Generate defaults if not provided
    if event_type is None:
        event_type = fake.word()

    if title is None:
        title = fake.sentence(nb_words=5)

    if body is None:
        body = fake.sentence(nb_words=15)

    event_id = await conn.fetchval(
        """
        INSERT INTO notifications.events (user_id, event_type, title, body, metadata)
        VALUES ($1, $2, $3, $4, $5::jsonb)
        RETURNING id
        """,
        user_id,
        event_type,
        title,
        body,
        metadata,
    )
    return event_id


async def create_map(
    conn: asyncpg.Connection,
    code: str | None = None,
    creator_id: int | None = None,
    mechanics: list[int] | None = None,
    restrictions: list[int] | None = None,
    tags: list[int] | None = None,
    medals: dict[str, float] | None = None,
    *,
    fake: Faker,
    global_code_tracker: set[str],
    global_user_id_tracker: set[int],
    **overrides: Any,
) -> int:
    """Insert a map, primary creator, and requested related records."""
    if code is None:
        code = map_code(fake, global_code_tracker)
    global_code_tracker.add(code)

    # Default values
    data = {
        "map_name": "Hanamura",
        "category": "Classic",
        "checkpoints": fake.random_int(min=1, max=50),
        "official": True,
        "playtesting": "Approved",
        "difficulty": "Medium",
        "hidden": False,
        "archived": False,
    }

    # Apply overrides
    data.update(overrides)

    # Auto-calculate raw_difficulty from difficulty (ignores any explicit raw_difficulty)
    difficulty = data["difficulty"]
    raw_min, raw_max = difficulties.DIFFICULTY_RANGES_ALL[difficulty]
    data["raw_difficulty"] = fake.pyfloat(min_value=raw_min, max_value=raw_max - 0.1, right_digits=2)

    map_id = await conn.fetchval(
        """
        INSERT INTO core.maps (
            code, map_name, category, checkpoints, official,
            playtesting, difficulty, raw_difficulty, hidden, archived
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        RETURNING id
        """,
        code,
        data["map_name"],
        data["category"],
        data["checkpoints"],
        data["official"],
        data["playtesting"],
        data["difficulty"],
        data["raw_difficulty"],
        data["hidden"],
        data["archived"],
    )

    # Create primary creator
    if creator_id is None:
        creator_id = snowflake(fake, global_user_id_tracker)

        # Create user
        await conn.execute(
            """
            INSERT INTO core.users (id, nickname, global_name)
            VALUES ($1, $2, $3)
            """,
            creator_id,
            fake.user_name(),
            fake.user_name(),
        )

    # Link creator to map
    await conn.execute(
        """
        INSERT INTO maps.creators (map_id, user_id, is_primary)
        VALUES ($1, $2, $3)
        """,
        map_id,
        creator_id,
        True,
    )

    # Link mechanics if provided
    if mechanics:
        for mechanic_id in mechanics:
            await conn.execute(
                """
                INSERT INTO maps.mechanic_links (map_id, mechanic_id)
                VALUES ($1, $2)
                """,
                map_id,
                mechanic_id,
            )

    # Link restrictions if provided
    if restrictions:
        for restriction_id in restrictions:
            await conn.execute(
                """
                INSERT INTO maps.restriction_links (map_id, restriction_id)
                VALUES ($1, $2)
                """,
                map_id,
                restriction_id,
            )

    # Link tags if provided
    if tags:
        for tag_id in tags:
            await conn.execute(
                """
                INSERT INTO maps.tag_links (map_id, tag_id)
                VALUES ($1, $2)
                """,
                map_id,
                tag_id,
            )

    # Create medals if provided
    if medals:
        await conn.execute(
            """
            INSERT INTO maps.medals (map_id, gold, silver, bronze)
            VALUES ($1, $2, $3, $4)
            """,
            map_id,
            medals.get("gold"),
            medals.get("silver"),
            medals.get("bronze"),
        )

    return map_id


async def grant_user_coins(conn: asyncpg.Connection, user_id: int, amount: int) -> int:
    """Add coins to a user's balance and return the balance."""
    result = await conn.fetchval(
        """
        UPDATE core.users
        SET coins = coins + $2
        WHERE id = $1
        RETURNING coins
        """,
        user_id,
        amount,
    )
    return result


async def create_completion(conn: asyncpg.Connection, user_id: int, map_id: int, **overrides: Any) -> int:
    """Insert a completion with the existing test defaults."""
    data = {
        "verified": True,
        "legacy": False,
        "time": 30.5,
        "screenshot": "https://example.com/screenshot.png",
        "completion": True,
        "message_id": None,
        "verified_by": None,
        "reason": None,
    }

    # Apply overrides
    data.update(overrides)

    completion_id = await conn.fetchval(
        """
        INSERT INTO core.completions (
            user_id, map_id, verified, legacy, time, screenshot,
            completion, message_id, verified_by, reason
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        RETURNING id
        """,
        user_id,
        map_id,
        data["verified"],
        data["legacy"],
        data["time"],
        data["screenshot"],
        data["completion"],
        data["message_id"],
        data["verified_by"],
        data["reason"],
    )
    return completion_id


async def create_vote(
    conn: asyncpg.Connection,
    user_id: int,
    map_id: int,
    thread_id: int,
    **overrides: Any,
) -> int:
    """Insert a playtest vote and return its ID."""
    data = {
        "difficulty": 5.0,
    }

    # Apply overrides
    data.update(overrides)

    vote_id = await conn.fetchval(
        """
        INSERT INTO playtests.votes (
            user_id, map_id, playtest_thread_id, difficulty
        )
        VALUES ($1, $2, $3, $4)
        RETURNING id
        """,
        user_id,
        map_id,
        thread_id,
        data["difficulty"],
    )
    return vote_id


async def create_tag(
    conn: asyncpg.Connection,
    name: str,
    content: str,
    *,
    owner_id: int,
    guild_id: int = GUILD_ID,
    **overrides: Any,
) -> int:
    """Insert a tag and its lookup entry in one statement."""
    tag_id: int = await conn.fetchval(
        """
        WITH new_tag AS (
            INSERT INTO public.tags (name, content, owner_id, location_id)
            VALUES ($1, $2, $3, $4)
            RETURNING id
        )
        INSERT INTO public.tag_lookup (name, owner_id, location_id, tag_id)
        SELECT $1, $3, $4, id FROM new_tag
        RETURNING tag_id
        """,
        name,
        content,
        owner_id,
        guild_id,
    )
    return tag_id


async def create_alias(
    conn: asyncpg.Connection,
    name: str,
    tag_id: int,
    *,
    owner_id: int,
    guild_id: int = GUILD_ID,
) -> int:
    """Insert an alias pointing to an existing tag."""
    await conn.execute(
        """
        INSERT INTO public.tag_lookup (name, owner_id, location_id, tag_id)
        VALUES ($1, $2, $3, $4)
        """,
        name,
        owner_id,
        guild_id,
        tag_id,
    )
    return tag_id

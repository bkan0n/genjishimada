"""Adapters preserving the existing public factory fixture API."""

from functools import partial
from uuid import UUID

import asyncpg
import pytest
from faker import Faker

from tests.support import factories


@pytest.fixture
def global_code_tracker() -> set[str]:
    """Track code values within one isolated test."""
    return set()


@pytest.fixture
def global_user_id_tracker() -> set[int]:
    """Track user id values within one isolated test."""
    return set()


@pytest.fixture
def global_thread_id_tracker() -> set[int]:
    """Track thread id values within one isolated test."""
    return set()


@pytest.fixture
def global_message_id_tracker() -> set[int]:
    """Track message id values within one isolated test."""
    return set()


@pytest.fixture
def global_email_tracker() -> set[str]:
    """Track email values within one isolated test."""
    return set()


@pytest.fixture
def global_session_id_tracker() -> set[str]:
    """Track session id values within one isolated test."""
    return set()


@pytest.fixture
def global_token_hash_tracker() -> set[str]:
    """Track token hash values within one isolated test."""
    return set()


@pytest.fixture
def global_job_id_tracker() -> set[UUID]:
    """Track job id values within one isolated test."""
    return set()


@pytest.fixture
def global_idempotency_key_tracker() -> set[str]:
    """Track idempotency key values within one isolated test."""
    return set()


@pytest.fixture
def global_ip_hash_tracker() -> set[str]:
    """Track ip hash values within one isolated test."""
    return set()


@pytest.fixture
def unique_map_code(faker: Faker, global_code_tracker: set[str]) -> str:
    """Generate a unique map code for this test."""
    return factories.map_code(faker, global_code_tracker)


@pytest.fixture
def unique_user_id(faker: Faker, global_user_id_tracker: set[int]) -> int:
    """Generate a unique user id for this test."""
    return factories.snowflake(faker, global_user_id_tracker)


@pytest.fixture
def unique_thread_id(faker: Faker, global_thread_id_tracker: set[int]) -> int:
    """Generate a unique thread id for this test."""
    return factories.snowflake(faker, global_thread_id_tracker)


@pytest.fixture
def unique_message_id(faker: Faker, global_message_id_tracker: set[int]) -> int:
    """Generate a unique message id for this test."""
    return factories.snowflake(faker, global_message_id_tracker)


@pytest.fixture
def unique_email(faker: Faker, global_email_tracker: set[str]) -> str:
    """Generate a unique email for this test."""
    return factories.unique_value(
        global_email_tracker,
        lambda: f"test-{factories.new_uuid(faker).hex[:8]}@example.com",
    )


@pytest.fixture
def unique_session_id(faker: Faker, global_session_id_tracker: set[str]) -> str:
    """Generate a unique session id for this test."""
    return factories.unique_value(global_session_id_tracker, lambda: factories.new_uuid(faker).hex)


@pytest.fixture
def unique_token_hash(faker: Faker, global_token_hash_tracker: set[str]) -> str:
    """Generate a unique token hash for this test."""
    return factories.hex_digest(faker, global_token_hash_tracker)


@pytest.fixture
def unique_job_id(faker: Faker, global_job_id_tracker: set[UUID]) -> UUID:
    """Generate a unique job id for this test."""
    return factories.unique_value(global_job_id_tracker, lambda: factories.new_uuid(faker))


@pytest.fixture
def unique_idempotency_key(faker: Faker, global_idempotency_key_tracker: set[str]) -> str:
    """Generate a unique idempotency key for this test."""
    return factories.unique_value(
        global_idempotency_key_tracker,
        lambda: f"idem-{factories.new_uuid(faker).hex[:16]}",
    )


@pytest.fixture
def unique_ip_hash(faker: Faker, global_ip_hash_tracker: set[str]) -> str:
    """Generate a unique ip hash for this test."""
    return factories.hex_digest(faker, global_ip_hash_tracker)


@pytest.fixture
def create_test_user(asyncpg_conn: asyncpg.Connection, faker: Faker, global_user_id_tracker: set[int]):
    """Bind create user to this test's connection."""
    return partial(
        factories.create_user,
        asyncpg_conn,
        fake=faker,
        global_user_id_tracker=global_user_id_tracker,
    )


@pytest.fixture
def create_test_playtest(asyncpg_conn: asyncpg.Connection, faker: Faker, global_thread_id_tracker: set[int]):
    """Bind create playtest to this test's connection."""
    return partial(
        factories.create_playtest,
        asyncpg_conn,
        fake=faker,
        global_thread_id_tracker=global_thread_id_tracker,
    )


@pytest.fixture
def create_test_edit_request(asyncpg_conn: asyncpg.Connection, faker: Faker):
    """Bind create edit request to this test's connection."""
    return partial(factories.create_edit_request, asyncpg_conn, fake=faker)


@pytest.fixture
def create_test_email_user(
    asyncpg_conn: asyncpg.Connection,
    faker: Faker,
    global_user_id_tracker: set[int],
    global_email_tracker: set[str],
):
    """Bind create email user to this test's connection."""
    return partial(
        factories.create_email_user,
        asyncpg_conn,
        fake=faker,
        global_user_id_tracker=global_user_id_tracker,
        global_email_tracker=global_email_tracker,
    )


@pytest.fixture
def create_test_session(asyncpg_conn: asyncpg.Connection, faker: Faker, global_session_id_tracker: set[str]):
    """Bind create session to this test's connection."""
    return partial(
        factories.create_session,
        asyncpg_conn,
        fake=faker,
        global_session_id_tracker=global_session_id_tracker,
    )


@pytest.fixture
def create_test_change_request(asyncpg_conn: asyncpg.Connection, faker: Faker, global_thread_id_tracker: set[int]):
    """Bind create change request to this test's connection."""
    return partial(
        factories.create_change_request,
        asyncpg_conn,
        fake=faker,
        global_thread_id_tracker=global_thread_id_tracker,
    )


@pytest.fixture
def create_test_job(asyncpg_conn: asyncpg.Connection, faker: Faker, global_job_id_tracker: set):
    """Bind create job to this test's connection."""
    return partial(
        factories.create_job,
        asyncpg_conn,
        fake=faker,
        global_job_id_tracker=global_job_id_tracker,
    )


@pytest.fixture
def create_test_claim(
    asyncpg_conn: asyncpg.Connection,
    faker: Faker,
    global_idempotency_key_tracker: set[str],
):
    """Bind create claim to this test's connection."""
    return partial(
        factories.create_claim,
        asyncpg_conn,
        fake=faker,
        global_idempotency_key_tracker=global_idempotency_key_tracker,
    )


@pytest.fixture
def create_test_newsfeed_event(asyncpg_conn: asyncpg.Connection, faker: Faker):
    """Bind create newsfeed event to this test's connection."""
    return partial(factories.create_newsfeed_event, asyncpg_conn, fake=faker)


@pytest.fixture
def create_test_notification_event(asyncpg_conn: asyncpg.Connection, faker: Faker, global_user_id_tracker: set[int]):
    """Bind create notification event to this test's connection."""
    return partial(
        factories.create_notification_event,
        asyncpg_conn,
        fake=faker,
        global_user_id_tracker=global_user_id_tracker,
    )


@pytest.fixture
def create_test_map(
    asyncpg_conn: asyncpg.Connection,
    faker: Faker,
    global_code_tracker: set[str],
    global_user_id_tracker: set[int],
):
    """Bind create map to this test's connection."""
    return partial(
        factories.create_map,
        asyncpg_conn,
        fake=faker,
        global_code_tracker=global_code_tracker,
        global_user_id_tracker=global_user_id_tracker,
    )


@pytest.fixture
def grant_user_coins(asyncpg_conn: asyncpg.Connection):
    """Bind grant user coins to this test's connection."""
    return partial(factories.grant_user_coins, asyncpg_conn)


@pytest.fixture
def create_test_completion(asyncpg_conn: asyncpg.Connection):
    """Bind create completion to this test's connection."""
    return partial(factories.create_completion, asyncpg_conn)


@pytest.fixture
def create_test_vote(asyncpg_conn: asyncpg.Connection):
    """Bind create vote to this test's connection."""
    return partial(factories.create_vote, asyncpg_conn)


@pytest.fixture
def create_test_tag(asyncpg_conn: asyncpg.Connection):
    """Bind create tag to this test's connection."""
    return partial(factories.create_tag, asyncpg_conn)


@pytest.fixture
def create_test_alias(asyncpg_conn: asyncpg.Connection):
    """Bind create alias to this test's connection."""
    return partial(factories.create_alias, asyncpg_conn)

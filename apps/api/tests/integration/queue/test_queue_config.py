"""Queue connections reuse the database location without inheriting API credentials."""

import importlib.util
from urllib.parse import unquote, urlsplit

import pytest

from .conftest import ROOT

spec = importlib.util.spec_from_file_location("queue_config", ROOT / "apps/bot/utilities/queue_config.py")
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
queue_database_url = module.queue_database_url

pytestmark = pytest.mark.queue


@pytest.fixture(autouse=True)
def database_environment(monkeypatch):
    for key in ("QUEUE_DATABASE_URL", "QUEUE_DATABASE_PASSWORD", "POSTGRES_HOST", "POSTGRES_DB", "APP_ENVIRONMENT"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("POSTGRES_USER", "api-owner")
    monkeypatch.setenv("POSTGRES_PASSWORD", "api-owner-password")
    monkeypatch.setenv("POSTGRES_DB", "genjishimada")
    monkeypatch.setenv("QUEUE_DATABASE_PASSWORD", "queue-password")


def test_explicit_queue_url_overrides_all_fallback_configuration(monkeypatch):
    expected = "postgresql://worker:override-password@separate-db:6432/queue?sslmode=require"
    monkeypatch.setenv("QUEUE_DATABASE_URL", expected)
    monkeypatch.delenv("QUEUE_DATABASE_PASSWORD")
    monkeypatch.delenv("POSTGRES_DB")
    assert queue_database_url() == expected


@pytest.mark.parametrize("queue_url", [None, ""])
def test_same_database_fallback_uses_only_queue_credentials(monkeypatch, queue_url):
    if queue_url is not None:
        monkeypatch.setenv("QUEUE_DATABASE_URL", queue_url)
    monkeypatch.setenv("POSTGRES_HOST", "shared-database")
    connection = urlsplit(queue_database_url())
    assert connection.hostname == "shared-database"
    assert connection.port == 5432
    assert connection.path == "/genjishimada"
    assert connection.username == "genjishimada_queue_worker"
    assert connection.password == "queue-password"
    assert "api-owner" not in connection.netloc


@pytest.mark.parametrize(
    ("environment", "host"),
    [("development", "genjishimada-db-dev"), ("production", "genjishimada-db")],
)
def test_environment_host_default_matches_api(monkeypatch, environment, host):
    monkeypatch.setenv("APP_ENVIRONMENT", environment)
    assert urlsplit(queue_database_url()).hostname == host


@pytest.mark.parametrize("host", ["localhost", "::1", "[::1]"])
def test_custom_database_host(monkeypatch, host):
    monkeypatch.setenv("POSTGRES_HOST", host)
    parsed = urlsplit(queue_database_url())
    assert parsed.hostname == host.strip("[]")
    assert parsed.port == 5432


def test_password_and_database_name_are_url_encoded(monkeypatch):
    password = "queue:@/ password?#%"
    database = "queue/database name"
    monkeypatch.setenv("QUEUE_DATABASE_PASSWORD", password)
    monkeypatch.setenv("POSTGRES_DB", database)
    parsed = urlsplit(queue_database_url())
    assert unquote(parsed.password) == password
    assert unquote(parsed.path[1:]) == database
    assert parsed.query == parsed.fragment == ""


@pytest.mark.parametrize("password", [None, ""])
def test_missing_queue_password_cannot_fall_back_to_api_owner(monkeypatch, password):
    if password is None:
        monkeypatch.delenv("QUEUE_DATABASE_PASSWORD")
    else:
        monkeypatch.setenv("QUEUE_DATABASE_PASSWORD", password)
    with pytest.raises(ValueError, match="QUEUE_DATABASE_PASSWORD") as error:
        queue_database_url()
    assert "api-owner-password" not in str(error.value)


def test_missing_database_name_has_actionable_error(monkeypatch):
    monkeypatch.delenv("POSTGRES_DB")
    with pytest.raises(ValueError, match="POSTGRES_DB"):
        queue_database_url()

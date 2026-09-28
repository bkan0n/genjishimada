"""Register the API testing infrastructure once, at the pytest root."""

pytest_plugins = [
    "pytest_databases.docker.postgres",
    "tests.support.fixtures",
    "tests.support.factory_fixtures",
    "tests.support.mocks",
]

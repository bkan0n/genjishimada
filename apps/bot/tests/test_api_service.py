"""Self-contained unit tests for the bot's APIService client methods.

The bot has no test harness, conftest, or shared fixtures. These tests mock
``_request`` directly (no live HTTP) and are run with an explicit command:

    cd apps/bot && uv run pytest tests/test_api_service.py -x
"""

import sys
from pathlib import Path
from unittest.mock import Mock

# The bot runs as `python main.py` from apps/bot, so `extensions`/`utilities` are
# top-level imports. pytest does not add the bot root to sys.path on its own (no
# conftest/harness in this project), so bootstrap it here to stay self-contained.
_BOT_ROOT = str(Path(__file__).resolve().parent.parent)
if _BOT_ROOT not in sys.path:
    sys.path.insert(0, _BOT_ROOT)

from extensions.api_service import APIService, Route  # noqa: E402


def _make_service() -> APIService:
    """Build an APIService without running ``__init__``.

    ``APIService.__init__`` opens an aiohttp session and schedules a heartbeat
    task on the running loop, neither of which the client-method-shape tests need.
    ``object.__new__`` gives a bare instance whose methods we can call after
    stubbing ``_request``.
    """
    return object.__new__(APIService)


def test_get_all_map_names_calls_request_with_route_and_response_model() -> None:
    svc = _make_service()
    sentinel = object()
    svc._request = Mock(return_value=sentinel)

    result = svc.get_all_map_names()

    # Returns whatever _request returns (the coroutine, here a sentinel).
    assert result is sentinel

    # _request invoked exactly once.
    svc._request.assert_called_once()
    call = svc._request.call_args

    # First positional arg is a GET Route to /utilities/map-names.
    route = call.args[0]
    assert isinstance(route, Route)
    assert route.method == "GET"
    assert route.path == "/utilities/map-names"

    # response_model is exactly list[str].
    assert call.kwargs["response_model"] == list[str]

    # No search/limit/params/data leaked in (full list, no pagination args).
    assert "search" not in call.kwargs
    assert "limit" not in call.kwargs
    assert "params" not in call.kwargs
    assert "data" not in call.kwargs


def test_get_all_map_names_is_not_a_coroutine_function() -> None:
    # Mirrors get_autocomplete_map_names: a plain def returning the coroutine,
    # NOT an async def. Callers await the returned value.
    import inspect

    assert not inspect.iscoroutinefunction(APIService.get_all_map_names)

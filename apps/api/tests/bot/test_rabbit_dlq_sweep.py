"""Unit tests for the periodic DLQ sweep isolation (Plan 09-03, Part B).

Phase-9 UAT Test 1 surfaced a cascade bug: ``_process_all_dlqs_once`` acquired ONE
pooled channel and reused it across every base queue, so a single channel-level
failure (a ``ChannelNotFoundEntity`` NOT_FOUND on a missing ``.dlq``) closed the shared
channel and every subsequent queue failed with ``Channel closed by RPC timeout``.

These tests prove the sweep is now isolated per base queue: a failing DLQ is logged and
skipped without aborting the remaining queues.

- ``sweep_isolates_failure``    → B's NOT_FOUND must not prevent A and C from processing
- ``sweep_returns_total``       → all-succeed sweep returns the summed processed count
- ``missing_dlq_skips_cleanly`` → a NOT_FOUND DLQ counts 0 and never raises out of the sweep

The bot ``rabbit`` module is path-loaded with the ``utilities``/``extensions`` sys.modules
snapshot/evict/restore guard (mirroring ``test_tournaments_handler.py``). The
``RabbitHandler`` is built via ``object.__new__`` so its async setup never runs; only the
attributes the sweep touches are injected. ``_process_one_dlq`` is monkeypatched so each
base queue's outcome is driven independently, and ``_channel_pool`` is replaced with a fake
async-context pool that yields a fresh fake channel per ``acquire()`` (so per-queue channel
isolation is observable).
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock

import pytest
from aio_pika.exceptions import ChannelNotFoundEntity


def _repo_root() -> pathlib.Path:
    # this file: <root>/apps/api/tests/bot/test_rabbit_dlq_sweep.py
    return pathlib.Path(__file__).resolve().parents[4]


def _install_queue_registry_stub() -> None:
    """Register a minimal ``extensions._queue_registry`` shell.

    ``rabbit.py`` imports ``from extensions._queue_registry import QueueHandler`` at module
    top. We provide a lightweight stub so the import resolves without dragging in the real
    (handler-discovery) module while ``apps/bot`` is on ``sys.path``.
    """
    extensions_pkg = ModuleType("extensions")
    extensions_pkg.__path__ = []  # type: ignore[attr-defined]
    sys.modules["extensions"] = extensions_pkg

    qr_mod = ModuleType("extensions._queue_registry")
    qr_mod.QueueHandler = object  # type: ignore[attr-defined]
    sys.modules["extensions._queue_registry"] = qr_mod


def _load_rabbit_module() -> ModuleType:
    """Path-load ``apps/bot/extensions/rabbit.py`` with the sys.modules guard.

    Snapshots and evicts the ``utilities``/``extensions`` package trees while ``apps/bot`` is
    on ``sys.path`` (so apps/api's own ``utilities`` package is not shadowed), then restores
    them in ``finally`` — the precedent established by ``test_tournaments_handler.py``.
    """
    module_name = "bot_extensions_rabbit"
    if module_name in sys.modules:
        return sys.modules[module_name]

    bot_root = _repo_root() / "apps" / "bot"
    snapshot = {
        k: v
        for k, v in sys.modules.items()
        if k in ("utilities", "extensions") or k.startswith(("utilities.", "extensions."))
    }
    try:
        for key in snapshot:
            del sys.modules[key]
        if str(bot_root) not in sys.path:
            sys.path.insert(0, str(bot_root))

        _install_queue_registry_stub()

        module_path = bot_root / "extensions" / "rabbit.py"
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        for key in list(sys.modules):
            if key in ("utilities", "extensions") or key.startswith(("utilities.", "extensions.")):
                del sys.modules[key]
        sys.modules.update(snapshot)


_rabbit = _load_rabbit_module()
RabbitHandler = _rabbit.RabbitHandler


class _FakeChannel:
    """A fake aio_pika channel; records that set_qos was invoked."""

    def __init__(self) -> None:
        self.set_qos_calls: list[int] = []

    async def set_qos(self, *, prefetch_count: int) -> None:
        self.set_qos_calls.append(prefetch_count)


class _FakeChannelPool:
    """A fake aio_pika ``Pool`` whose ``acquire()`` yields a FRESH channel each call.

    A new channel per ``acquire()`` is the observable proof of per-base-queue isolation:
    a channel closed by queue B cannot be the channel handed to queue C.
    """

    def __init__(self) -> None:
        self.channels: list[_FakeChannel] = []

    def acquire(self) -> _FakeChannelPool:
        return self

    async def __aenter__(self) -> _FakeChannel:
        channel = _FakeChannel()
        self.channels.append(channel)
        return channel

    async def __aexit__(self, *_exc: object) -> None:
        return None


def _make_handler(queues: list[str]) -> Any:
    """Build a RabbitHandler bypassing __init__, injecting only sweep-touched attrs."""
    handler = object.__new__(RabbitHandler)
    handler._queues = {name: object() for name in queues}  # sweep only iterates keys
    handler._dlq_suffix = ".dlq"
    handler._channel_pool = _FakeChannelPool()
    return handler


@pytest.mark.asyncio
async def test_sweep_isolates_failure_so_one_missing_dlq_does_not_poison_the_rest() -> None:
    """B's NOT_FOUND must NOT prevent A and C from being processed (cascade broken)."""
    handler = _make_handler(["A", "B", "C"])

    counts = {"A": 3, "C": 4}

    async def fake_one_dlq(_channel: Any, base_queue: str) -> int:
        if base_queue == "B":
            raise ChannelNotFoundEntity("NOT_FOUND - no queue 'B.dlq'")
        return counts[base_queue]

    handler._process_one_dlq = AsyncMock(side_effect=fake_one_dlq)

    total = await handler._process_all_dlqs_once()

    processed_bases = [call.args[1] for call in handler._process_one_dlq.await_args_list]
    assert processed_bases == ["A", "B", "C"], "every base queue must get a processing attempt"
    assert total == counts["A"] + counts["C"], "B contributes 0; A + C totals are preserved"


@pytest.mark.asyncio
async def test_sweep_returns_total_across_all_base_queues_when_all_succeed() -> None:
    """With every DLQ succeeding, the sweep returns the summed processed count."""
    handler = _make_handler(["A", "B", "C"])

    counts = {"A": 1, "B": 2, "C": 5}

    async def fake_one_dlq(_channel: Any, base_queue: str) -> int:
        return counts[base_queue]

    handler._process_one_dlq = AsyncMock(side_effect=fake_one_dlq)

    total = await handler._process_all_dlqs_once()

    assert total == sum(counts.values())


@pytest.mark.asyncio
async def test_missing_dlq_skips_cleanly_without_raising_out_of_the_sweep() -> None:
    """A NOT_FOUND DLQ counts 0 and the sweep never raises out of itself."""
    handler = _make_handler(["only"])

    async def fake_one_dlq(_channel: Any, _base_queue: str) -> int:
        raise ChannelNotFoundEntity("NOT_FOUND - no queue 'only.dlq'")

    handler._process_one_dlq = AsyncMock(side_effect=fake_one_dlq)

    # Must not raise.
    total = await handler._process_all_dlqs_once()

    assert total == 0
    assert handler._process_one_dlq.await_count == 1


@pytest.mark.asyncio
async def test_sweep_acquires_a_fresh_channel_per_base_queue() -> None:
    """Per-queue isolation: each base queue gets its own channel from the pool."""
    handler = _make_handler(["A", "B", "C"])

    async def fake_one_dlq(_channel: Any, _base_queue: str) -> int:
        return 0

    handler._process_one_dlq = AsyncMock(side_effect=fake_one_dlq)

    await handler._process_all_dlqs_once()

    # One fresh channel acquired per base queue (3), proving the shared-channel reuse is gone.
    assert len(handler._channel_pool.channels) == 3

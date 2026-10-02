"""One application transaction across nested services and effect receipts."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from functools import wraps
from typing import Any, ParamSpec, Protocol, TypeVar, cast

from asyncpg import Connection, Pool

current_connection: ContextVar[Connection | None] = ContextVar("current_connection", default=None)
_transaction_task: ContextVar[asyncio.Task | None] = ContextVar("transaction_task", default=None)
_after_commit: ContextVar[list[Callable[[], None]] | None] = ContextVar("after_commit", default=None)
P = ParamSpec("P")
R = TypeVar("R")


def active_connection() -> Connection | None:
    """Return only this task's connection; background tasks never inherit a lease."""
    if _transaction_task.get() is asyncio.current_task():
        return current_connection.get()
    return None


@asynccontextmanager
async def transaction(pool: Pool, *, conn: Connection | None = None) -> AsyncIterator[Connection]:
    """Reuse an enclosing transaction or commit a new service transaction."""
    existing = active_connection()
    if existing is not None:
        yield existing
        return
    async with _borrow(pool, conn) as connection:
        callbacks: list[Callable[[], None]] = []
        conn_token = current_connection.set(connection)
        task_token = _transaction_task.set(asyncio.current_task())
        callbacks_token = _after_commit.set(callbacks)
        try:
            async with connection.transaction():
                yield connection
        finally:
            current_connection.reset(conn_token)
            _transaction_task.reset(task_token)
            _after_commit.reset(callbacks_token)
        for callback in callbacks:
            callback()


@asynccontextmanager
async def _borrow(pool: Pool, conn: Connection | None) -> AsyncIterator[Connection]:
    if conn is not None:
        yield conn
    else:
        async with pool.acquire() as borrowed:
            yield cast("Connection", borrowed)


class _Service(Protocol):
    _pool: Pool


def on_commit(callback: Callable[[], None]) -> None:
    """Run after the enclosing service commits, without inheriting its connection."""
    callbacks = _after_commit.get() if active_connection() is not None else None
    if callbacks is None:
        callback()
    else:
        callbacks.append(callback)


def transactional(method: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Wrap a service boundary while preserving one connection through nested calls."""

    @wraps(method)
    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        service = cast("_Service", args[0])
        supplied = cast("Connection | None", kwargs.get("conn"))
        async with transaction(service._pool, conn=supplied):  # noqa: SLF001
            return await method(*args, **kwargs)

    return wrapped


class ContextPool:
    """Route legacy explicit pool acquisitions through the current transaction."""

    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    @asynccontextmanager
    async def acquire(self, **kwargs: Any) -> AsyncIterator[Connection]:  # noqa: ANN401
        """Borrow the contextual connection without releasing its parent's lease."""
        conn = active_connection()
        if conn is not None:
            yield conn
        else:
            async with self._pool.acquire(**kwargs) as borrowed:
                yield cast("Connection", borrowed)

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401
        """Forward direct query calls to the contextual connection when present."""
        conn = active_connection()
        if conn is not None and name in {"execute", "executemany", "fetch", "fetchrow", "fetchval"}:
            return getattr(conn, name)
        return getattr(self._pool, name)

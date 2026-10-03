from __future__ import annotations

from functools import wraps
from typing import TYPE_CHECKING, Awaitable, Callable, TypeVar, cast

import msgspec
from genjishimada_sdk.queue import JobContext

if TYPE_CHECKING:
    import core

QueueHandler = Callable[[JobContext], Awaitable[None]]
TStruct = TypeVar("TStruct", bound=msgspec.Struct)
F = TypeVar("F", bound=Callable[..., Awaitable[None]])


def queue_consumer(queue_name: str, *, struct_type: type[TStruct]) -> Callable[[F], F]:
    """Register a typed job handler without claiming the entire business operation.

    Completion belongs to the worker's fenced queue claim. Individual domain mutations
    and external effects are checkpointed separately so replay resumes unfinished work.
    """

    def decorator(fn: F) -> F:
        @wraps(fn)
        async def wrapper(self: object, context: JobContext) -> None:
            ensure_ready = getattr(self, "_ensure_guild_and_channel", None)
            if ensure_ready:
                await ensure_ready()
            event = msgspec.json.decode(context.payload, type=struct_type)
            await fn(self, event, context)

        setattr(wrapper, "_queue_name", queue_name)
        setattr(wrapper, "_struct_type", struct_type)
        return cast(F, wrapper)

    return decorator


async def setup(_: core.Genji) -> None:
    """Provide an extension hook for the shared registration module."""

"""Fence and checkpoint queue-originated domain HTTP mutations in one transaction."""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime
from http import HTTPStatus
from typing import Any, cast
from uuid import UUID

import msgspec
from genjishimada_sdk.queue import JobContext, LostOwnershipError
from genjishimada_sdk.queue_store import apply_mutation
from litestar.types import ASGIApp, Message, Receive, Scope, Send

from utilities.transactions import transaction

# Permit only domain operations that the corresponding consumer owns. New
# cross-domain effects must deliberately extend this list, never trust a header.
_ALLOWED = {
    "api.completion.verification": (
        "/completions/",
        "/lootbox/users/",
        "/maps/mastery",
        "/notifications/events",
        "/newsfeed",
    ),
    "api.completion.submission": ("/completions/",),
    "api.completion.upvote": ("/completions/",),
    "api.newsfeed.create": ("/newsfeed/", "/maps/playtests", "/notifications/events"),
    "api.notification.delivery": ("/notifications/events/",),
    "api.map_edit.created": ("/maps/map-edits/",),
    "api.map_edit.resolved": ("/maps/map-edits/",),
    "api.xp.grant": ("/lootbox/users/", "/notifications/events"),
    "api.tournament.completion.created": ("/tournaments/completions/",),
}
for _event in ("create", "approve", "force_accept", "force_deny", "reset", "vote.cast", "vote.remove"):
    _ALLOWED["api.playtest." + _event] = ("/maps/", "/newsfeed", "/lootbox/users/", "/notifications/events")


MAX_EFFECT_KEY_LENGTH = 200


class _UnsuccessfulResponseError(Exception):
    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self.messages = messages


class JobEffectMiddleware:
    """Normal requests retain their contracts; worker mutations gain durable receipts."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:  # noqa: PLR0912
        """Authenticate, fence, and atomically checkpoint a worker mutation response."""
        if scope["type"] != "http" or scope["method"] in {"GET", "HEAD", "OPTIONS"}:
            await self.app(scope, receive, send)
            return
        headers = {key.decode().lower(): value.decode() for key, value in scope.get("headers", [])}
        if "x-job-id" not in headers or scope["path"].startswith("/api/v3/internal/jobs"):
            await self.app(scope, receive, send)
            return
        auth = scope.get("auth")
        if auth is None or not (auth.is_superuser or "jobs:manage" in auth.scopes):
            await self._error(send, 403, "Worker effect context requires a trusted service credential")
            return
        try:
            job_id = UUID(headers["x-job-id"])
            manager = UUID(headers["x-job-manager"])
            claimed = datetime.fromisoformat(headers["x-job-claimed-at"])
            key = headers["x-job-effect"]
            if not key or len(key) > MAX_EFFECT_KEY_LENGTH or claimed.tzinfo is None:
                raise ValueError("Invalid effect identity")
        except (KeyError, ValueError):
            await self._error(send, 400, "Invalid worker effect context")
            return
        path = scope["path"].removeprefix("/api/v3")
        try:
            async with transaction(scope["app"].state.db_pool) as conn:
                job = await conn.fetchrow("SELECT action,queue_job_id,event_key FROM public.jobs WHERE id=$1", job_id)
                if job is None:
                    raise LookupError("Job not found")
                if not any(path.startswith(prefix) for prefix in _ALLOWED.get(job["action"], ())):
                    raise PermissionError("Job does not own this domain effect")
                context = JobContext(
                    job_id, job["action"], job["event_key"], job["queue_job_id"], manager, claimed, b""
                )
                # Immutable route/semantic effect identify an operation. Replayed input
                # may contain freshly computed timestamps; return its committed response.
                fingerprint = hashlib.sha256((scope["method"] + ":" + path + ":" + key).encode()).hexdigest()

                async def execute() -> list[dict[str, Any]]:
                    messages: list[dict[str, Any]] = []

                    async def capture(message: Message) -> None:
                        messages.append(dict(message))

                    await self.app(scope, receive, capture)
                    start = next((m for m in messages if m["type"] == "http.response.start"), None)
                    if start is None or start["status"] >= HTTPStatus.BAD_REQUEST:
                        raise _UnsuccessfulResponseError(messages)
                    return [self._serialize(message) for message in messages]

                saved = await apply_mutation(conn, context, key, fingerprint, execute)
            # Only tell the caller about success after the business/receipt commit.
            for message in saved:
                await send(self._deserialize(message))
        except _UnsuccessfulResponseError as error:
            for message in error.messages:
                await send(cast(Message, message))
        except PermissionError as error:
            await self._error(send, 403, str(error))
        except LookupError as error:
            await self._error(send, 404, str(error))
        except (ValueError, LostOwnershipError) as error:
            await self._error(send, 409, str(error))

    @staticmethod
    def _serialize(message: dict[str, Any]) -> dict[str, Any]:
        result = dict(message)
        if "body" in result:
            result["body"] = base64.b64encode(result["body"]).decode()
        if "headers" in result:
            result["headers"] = [
                [k.decode("latin1"), v.decode("latin1")]
                for k, v in result["headers"]
                if k.lower() not in {b"set-cookie", b"authorization"}
            ]
        return result

    @staticmethod
    def _deserialize(message: dict[str, Any]) -> Message:
        result = dict(message)
        if "body" in result:
            result["body"] = base64.b64decode(result["body"])
        if "headers" in result:
            result["headers"] = [(k.encode("latin1"), v.encode("latin1")) for k, v in result["headers"]]
        return cast(Message, result)

    @staticmethod
    async def _error(send: Send, status: int, detail: str) -> None:
        await send(
            {"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json")]}
        )
        await send(
            {
                "type": "http.response.body",
                "body": msgspec.json.encode({"status_code": status, "detail": detail}),
                "more_body": False,
            }
        )

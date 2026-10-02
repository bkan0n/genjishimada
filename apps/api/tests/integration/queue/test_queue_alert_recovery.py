"""Exercise real alert recovery with fake HTTP and Discord transports, without a bot login."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import unquote
from uuid import uuid4

import discord
import pytest

pytestmark = [pytest.mark.queue, pytest.mark.asyncio]
ROOT = Path(__file__).resolve().parents[5]


@pytest.fixture
def alert_module(monkeypatch):
    # API and bot both have a top-level utilities package. Load the bot's real
    # dependencies temporarily so queue acceptance cannot contaminate API imports.
    modules = (
        ("utilities.base", "utilities/base.py"),
        ("utilities.errors", "utilities/errors.py"),
        ("_queue_alert_operations", "extensions/job_operations.py"),
    )
    with monkeypatch.context() as imports:
        for name, relative in modules:
            spec = importlib.util.spec_from_file_location(name, ROOT / "apps/bot" / relative)
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            imports.setitem(sys.modules, name, module)
            spec.loader.exec_module(module)
    return module


class FakeMessage:
    def __init__(self, identity, content, view, events):
        self.id = identity
        self.content = content
        self.view = view
        self.author = SimpleNamespace(id=999)
        self.events = events
        self.failed_edits = 0
        self.edit_mentions = []

    async def edit(self, *, content, view, allowed_mentions):
        self.events.append("edit")
        if self.failed_edits:
            self.failed_edits -= 1
            raise TimeoutError("Discord edit response unavailable")
        self.content = content
        self.view = view
        self.edit_mentions.append(allowed_mentions)


class FakeOperationsAPI:
    def __init__(self, job_id, receipts, events):
        self.job_id = job_id
        self.receipts = receipts
        self.events = events
        self.acknowledgements = []

    async def job_operation(self, method, path, *, data=None):
        assert method == "POST"
        if path == f"/{self.job_id}/alert":
            self.events.append("acknowledge")
            self.acknowledgements.append(data)
            return {"accepted": True}
        key, operation = unquote(path.split("/effects/", 1)[1]).rsplit("/", 1)
        if operation == "claim":
            if key in self.receipts:
                return self.receipts[key]
            self.receipts[key] = {"state": "uncertain"}
            return {"state": "claimed"}
        assert operation == "complete"
        self.receipts[key] = {"state": "completed", "result": data["result"]}
        return self.receipts[key]


def recovery_case(module, receipt_state, *, status="succeeded", generation=2, notified_generation=2):
    events = []
    job = {
        "job_id": str(uuid4()),
        "event_name": "api.newsfeed.create",
        "status": status,
        "retry_generation": generation,
        "observed_at": "2026-10-02T12:00:00+00:00",
        "notified_generation": notified_generation,
        "message_id": None,
        "effects": [],
    }
    marker = f"-# job-alert:{job['job_id']}"
    previous = {**job, "status": "failed", "retry_generation": 0}
    message = FakeMessage(123, module._summary(previous) + "\n" + marker, module._view(previous), events)
    messages = {message.id: message}
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 456
    channel.guild = SimpleNamespace(id=789)

    async def fetch_message(identity):
        return messages[identity]

    async def send(content, **kwargs):
        created = FakeMessage(max(messages) + 1, content, kwargs.get("view"), events)
        messages[created.id] = created
        return created

    async def history(**kwargs):
        for candidate in reversed(list(messages.values())):
            yield candidate

    channel.fetch_message = AsyncMock(side_effect=fetch_message)
    channel.send = AsyncMock(side_effect=send)
    channel.history = history
    receipt = {"state": receipt_state}
    if receipt_state == "completed":
        receipt["result"] = {"channel_id": channel.id, "message_id": message.id}
    api = FakeOperationsAPI(job["job_id"], {"alert:card": receipt}, events)
    bot = SimpleNamespace(
        api=api,
        user=SimpleNamespace(id=999),
        get_channel=lambda identity: channel,
        config=SimpleNamespace(
            channels=SimpleNamespace(updates=SimpleNamespace(job_alerts=channel.id, job_alert_user_id=42))
        ),
    )
    return SimpleNamespace(
        cog=module.JobOperationsCog(bot), job=job, message=message, messages=messages,
        channel=channel, api=api, events=events, marker=marker,
    )


@pytest.mark.parametrize("receipt_state", ["completed", "uncertain"])
@pytest.mark.parametrize("status", ["succeeded", "failed"])
async def test_recovered_alert_refreshes_content_and_controls_before_acknowledging(alert_module, receipt_state, status):
    case = recovery_case(alert_module, receipt_state, status=status)

    await case.cog._render(case.job)

    assert f"**Status:** {status} · **Generation:** 2" in case.message.content
    assert case.marker in case.message.content
    retry = case.message.view.children[0]
    assert retry.generation == 2
    assert retry.item.disabled is (status == "succeeded")
    assert case.events.index("edit") < case.events.index("acknowledge")
    assert case.api.acknowledgements[0]["rendered_status"] == status
    assert case.api.acknowledgements[0]["observed_at"] == case.job["observed_at"]
    assert all(mentions.to_dict() == discord.AllowedMentions.none().to_dict() for mentions in case.message.edit_mentions)
    case.channel.send.assert_not_awaited()


@pytest.mark.parametrize("receipt_state", ["completed", "uncertain"])
async def test_failed_recovered_alert_edit_stays_unacknowledged_and_reuses_the_card(alert_module, receipt_state):
    case = recovery_case(alert_module, receipt_state)
    case.message.failed_edits = 1
    previous_content = case.message.content

    with pytest.raises(TimeoutError, match="Discord edit"):
        await case.cog._render(case.job)

    assert case.api.acknowledgements == []
    assert case.message.content == previous_content
    assert case.api.receipts["alert:card"]["state"] == "completed"
    case.channel.send.assert_not_awaited()

    await case.cog._render(case.job)

    assert "**Status:** succeeded · **Generation:** 2" in case.message.content
    assert len(case.api.acknowledgements) == 1
    assert len(case.messages) == 1
    case.channel.send.assert_not_awaited()


async def test_recovered_alert_notifies_each_new_failure_generation_once(alert_module):
    case = recovery_case(alert_module, "completed", status="failed", generation=1, notified_generation=0)

    # Replay the same observation to model losing the final binding response.
    await case.cog._render(case.job)
    await case.cog._render(case.job)

    assert "**Status:** failed · **Generation:** 1" in case.message.content
    case.channel.send.assert_awaited_once()
    assert case.channel.send.await_args.args[0].count("<@42>") == 1
    assert f"job-failure:{case.job['job_id']}:1" in case.channel.send.await_args.args[0]
    assert len(case.messages) == 2
    assert [ack["notified_generation"] for ack in case.api.acknowledgements] == [1, 1]

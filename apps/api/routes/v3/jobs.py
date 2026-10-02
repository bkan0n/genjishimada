"""Durable job status, execution checkpoints, and authorized operator recovery."""

from __future__ import annotations

import uuid
from datetime import datetime
from http import HTTPStatus
from typing import Any

import msgspec
from genjishimada_sdk import queue_store
from genjishimada_sdk.internal import ClaimCreateRequest, ClaimResponse, JobStatusResponse, JobStatusUpdateRequest
from litestar import Controller, Request, delete, get, patch, post
from litestar.di import Provide
from litestar.exceptions import HTTPException

from repository.jobs_repository import InternalJobsRepository, provide_internal_jobs_repository

_MANAGE = {"required_scopes": {"jobs:manage"}}


class RetryJobRequest(msgspec.Struct, forbid_unknown_fields=True):
    """A durable recovery request with optional saved control context."""

    operator_id: int
    expected_generation: int
    request_id: str
    guild_id: int | None = None
    channel_id: int | None = None
    message_id: int | None = None


class EffectClaimRequest(msgspec.Struct, forbid_unknown_fields=True):
    destination: str


class EffectCompletionRequest(msgspec.Struct, forbid_unknown_fields=True):
    result: dict[str, Any]


class SnapshotRequest(msgspec.Struct, forbid_unknown_fields=True):
    value: Any


class AlertBindingRequest(msgspec.Struct, forbid_unknown_fields=True):
    guild_id: int
    channel_id: int
    message_id: int
    expected_generation: int
    rendered_status: str
    observed_at: datetime
    notified_generation: int | None = None


class ReconcileRequest(msgspec.Struct, forbid_unknown_fields=True):
    operator_id: int
    expected_generation: int
    request_id: str
    reason: str
    result: dict[str, Any] | None = None
    resend: bool = False


class DiscardRequest(msgspec.Struct, forbid_unknown_fields=True):
    operator_id: int
    expected_generation: int
    request_id: str
    reason: str


def _binding(guild_id: int | None, channel_id: int | None, message_id: int | None) -> dict[str, int] | None:
    values = {"guild_id": guild_id, "channel_id": channel_id, "message_id": message_id}
    if all(value is None for value in values.values()):
        return None
    if any(value is None or value <= 0 for value in values.values()):
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="A complete, valid control binding is required.")
    return {name: value for name, value in values.items() if value is not None}


class InternalJobsController(Controller):
    path = "/internal"
    tags = ["Internal"]
    dependencies = {"repo": Provide(provide_internal_jobs_repository)}

    @get("/jobs", opt=_MANAGE)
    async def list_operations(
        self,
        repo: InternalJobsRepository,
        operator_id: int,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List actionable jobs for recovery through the common operator API."""
        return await repo.list_operations(operator_id=operator_id, status=status, limit=limit)

    @get("/jobs/stats", opt=_MANAGE)
    async def stats(self, repo: InternalJobsRepository, operator_id: int) -> dict[str, Any]:
        """Report actionable queue pressure and uncertainty to operators."""
        return await repo.queue_stats(operator_id=operator_id)

    @get("/jobs/{job_id:str}")
    async def get_job(self, repo: InternalJobsRepository, job_id: uuid.UUID) -> JobStatusResponse:
        """Get the existing public UUID/status response."""
        return await repo.get_job(job_id)

    @patch("/jobs/{job_id:str}", include_in_schema=False)
    async def update_job(self, repo: InternalJobsRepository, job_id: uuid.UUID, data: JobStatusUpdateRequest) -> None:
        """Retain status updates only for legacy jobs without an execution row."""
        return await repo.update_job(job_id, data)

    @get("/jobs/alerts", opt=_MANAGE)
    async def alerts(self, repo: InternalJobsRepository, after: uuid.UUID | None = None) -> list[dict[str, Any]]:
        """Return durable failures and changed status projections awaiting delivery."""
        return await repo.pending_alerts(after=after)

    @post("/jobs/{job_id:str}/alert", opt=_MANAGE, status_code=HTTPStatus.OK)
    async def bind_alert(
        self,
        repo: InternalJobsRepository,
        job_id: uuid.UUID,
        data: AlertBindingRequest,
    ) -> dict[str, Any]:
        """Persist an operational message binding without granting domain database access."""
        binding = _binding(data.guild_id, data.channel_id, data.message_id)
        assert binding is not None
        return await repo.bind_alert(
            job_id,
            binding=binding,
            expected_generation=data.expected_generation,
            rendered_status=data.rendered_status,
            notified_generation=data.notified_generation,
            observed_at=data.observed_at,
        )

    @get("/jobs/{job_id:str}/operations", opt=_MANAGE)
    async def inspect(  # noqa: PLR0913
        self,
        repo: InternalJobsRepository,
        job_id: uuid.UUID,
        operator_id: int,
        guild_id: int | None = None,
        channel_id: int | None = None,
        message_id: int | None = None,
    ) -> dict[str, Any]:
        """Inspect job effects after validating the operator and optional control binding."""
        return await repo.inspect_operation(
            job_id,
            operator_id=operator_id,
            binding=_binding(guild_id, channel_id, message_id),
        )

    @post("/jobs/{job_id:str}/retry", opt=_MANAGE, status_code=HTTPStatus.OK)
    async def retry(self, repo: InternalJobsRepository, job_id: uuid.UUID, data: RetryJobRequest) -> dict[str, Any]:
        """Requeue the same held job once, retaining all completed business effects."""
        return await repo.perform(
            queue_store.retry_job,
            job_id,
            operator_id=data.operator_id,
            expected_generation=data.expected_generation,
            request_id=data.request_id,
            binding=_binding(data.guild_id, data.channel_id, data.message_id),
        )

    @post("/jobs/{job_id:str}/prepare", opt=_MANAGE, status_code=HTTPStatus.OK)
    async def prepare(self, request: Request, repo: InternalJobsRepository, job_id: uuid.UUID) -> dict[str, bool]:
        """Fence a worker and validate its dependency and entity execution order."""
        await repo.perform(queue_store.ensure_ready, repo.execution_context(job_id, request.headers))
        return {"ready": True}

    @post("/jobs/{job_id:str}/effects/{effect_key:str}/claim", opt=_MANAGE, status_code=HTTPStatus.OK)
    async def claim_effect(
        self,
        request: Request,
        repo: InternalJobsRepository,
        job_id: uuid.UUID,
        effect_key: str,
        data: EffectClaimRequest,
    ) -> dict[str, Any]:
        """Reserve an external effect, returning completed or uncertain prior work."""
        administrative = effect_key.startswith("alert:")
        context = repo.execution_context(job_id, request.headers, administrative=administrative)
        return await repo.perform(
            queue_store.claim_effect,
            context,
            effect_key,
            destination=data.destination,
            administrative=administrative,
        )

    @post("/jobs/{job_id:str}/effects/{effect_key:str}/complete", opt=_MANAGE, status_code=HTTPStatus.OK)
    async def complete_effect(
        self,
        request: Request,
        repo: InternalJobsRepository,
        job_id: uuid.UUID,
        effect_key: str,
        data: EffectCompletionRequest,
    ) -> dict[str, Any]:
        """Persist a completed effect under its active execution or alert service authority."""
        administrative = effect_key.startswith("alert:")
        context = repo.execution_context(job_id, request.headers, administrative=administrative)
        return await repo.perform(
            queue_store.complete_effect,
            context,
            effect_key,
            data.result,
            administrative=administrative,
        )

    @post("/jobs/{job_id:str}/effects/{effect_key:str}/release", opt=_MANAGE, status_code=HTTPStatus.OK)
    async def release_effect(
        self,
        request: Request,
        repo: InternalJobsRepository,
        job_id: uuid.UUID,
        effect_key: str,
    ) -> dict[str, Any]:
        """Release an active reservation after a definite external rejection."""
        administrative = effect_key.startswith("alert:")
        context = repo.execution_context(job_id, request.headers, administrative=administrative)
        return await repo.perform(queue_store.release_effect, context, effect_key, administrative=administrative)

    @post("/jobs/{job_id:str}/snapshots/{key:str}", opt=_MANAGE, status_code=HTTPStatus.OK)
    async def snapshot(
        self,
        request: Request,
        repo: InternalJobsRepository,
        job_id: uuid.UUID,
        key: str,
        data: SnapshotRequest,
    ) -> dict[str, Any]:
        """Retain the first execution's decision inputs across later retries."""
        context = repo.execution_context(job_id, request.headers)
        value = await repo.perform(queue_store.save_snapshot, context, key, data.value)
        return {"value": value}

    @post("/jobs/{job_id:str}/effects/{effect_key:str}/reconcile", opt=_MANAGE, status_code=HTTPStatus.OK)
    async def reconcile(
        self,
        repo: InternalJobsRepository,
        job_id: uuid.UUID,
        effect_key: str,
        data: ReconcileRequest,
    ) -> dict[str, Any]:
        """Record an operator's explicit evidence or permission to repeat an uncertain effect."""
        return await repo.perform(
            queue_store.reconcile_effect,
            job_id,
            effect_key,
            operator_id=data.operator_id,
            expected_generation=data.expected_generation,
            request_id=data.request_id,
            reason=data.reason,
            result=data.result,
            resend=data.resend,
        )

    @post("/jobs/{job_id:str}/discard", opt=_MANAGE, status_code=HTTPStatus.OK)
    async def discard(self, repo: InternalJobsRepository, job_id: uuid.UUID, data: DiscardRequest) -> dict[str, Any]:
        """Discard held work only with an authorized operator's audited reason."""
        return await repo.perform(
            queue_store.discard_job,
            job_id,
            operator_id=data.operator_id,
            expected_generation=data.expected_generation,
            request_id=data.request_id,
            reason=data.reason,
        )

    @post("/idempotency/claim")
    async def claim_idempotency(self, repo: InternalJobsRepository, data: ClaimCreateRequest) -> ClaimResponse:
        """Retain the legacy generic idempotency API for existing callers."""
        return await repo.claim_idempotency(data)

    @delete("/idempotency/claim")
    async def delete_claimed_idempotency(self, repo: InternalJobsRepository, data: ClaimCreateRequest) -> None:
        """Delete a legacy generic idempotency key."""
        return await repo.delete_claimed_idempotency(data)

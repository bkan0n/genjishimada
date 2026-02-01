import uuid

from genjishimada_sdk.internal import ClaimCreateRequest, ClaimResponse, JobStatusResponse, JobStatusUpdateRequest
from litestar import Controller, delete, get, patch, post
from litestar.di import Provide

from repository.jobs_repository import InternalJobsRepository, provide_internal_jobs_repository


class InternalJobsController(Controller):
    path = "/internal"
    tags = ["Internal"]
    dependencies = {"repo": Provide(provide_internal_jobs_repository)}

    @get("/jobs/{job_id:str}")
    async def get_job(self, repo: InternalJobsRepository, job_id: uuid.UUID) -> JobStatusResponse:
        """Get job status."""
        return await repo.get_job(job_id)

    @patch("/jobs/{job_id:str}", include_in_schema=False)
    async def update_job(self, repo: InternalJobsRepository, job_id: uuid.UUID, data: JobStatusUpdateRequest) -> None:
        """Update pending job."""
        return await repo.update_job(job_id, data)

    @post("/idempotency/claim")
    async def claim_idempotency(self, repo: InternalJobsRepository, data: ClaimCreateRequest) -> ClaimResponse:
        """Claim a idempotency key."""
        resp = await repo.claim_idempotency(data)
        return resp

    @delete("/idempotency/claim")
    async def delete_claimed_idempotency(self, repo: InternalJobsRepository, data: ClaimCreateRequest) -> None:
        """Delete a idempotency key."""
        resp = await repo.delete_claimed_idempotency(data)
        return resp

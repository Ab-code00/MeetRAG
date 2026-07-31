from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select

from app.api.deps import AuthContext, DbSession, correlation_id, require_roles
from app.models import ProcessingJob
from app.models.enums import JobStage, JobStatus, UserRole
from app.schemas.meetings import JobResponse
from app.services.audit import add_audit_log
from app.workers.tasks import enqueue_pipeline

router = APIRouter(prefix="/admin", tags=["administration"])
AdminAuth = Annotated[
    AuthContext, Depends(require_roles(UserRole.OWNER, UserRole.ADMIN))
]


@router.get("/jobs")
async def inspect_jobs(
    auth: AdminAuth,
    db: DbSession,
    job_status: Annotated[JobStatus | None, Query(alias="status")] = None,
    stage: JobStage | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    filters = [ProcessingJob.tenant_id == auth.tenant_id]
    if job_status:
        filters.append(ProcessingJob.status == job_status)
    if stage:
        filters.append(ProcessingJob.stage == stage)
    total = await db.scalar(select(func.count(ProcessingJob.id)).where(*filters))
    jobs = list(
        (
            await db.scalars(
                select(ProcessingJob)
                .where(*filters)
                .order_by(ProcessingJob.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    return {
        "items": [JobResponse.model_validate(item).model_dump(mode="json") for item in jobs],
        "total": total or 0,
        "limit": limit,
        "offset": offset,
    }


@router.post("/jobs/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_job(
    job_id: str, request: Request, auth: AdminAuth, db: DbSession
) -> dict[str, str]:
    job = await db.scalar(
        select(ProcessingJob).where(
            ProcessingJob.id == job_id, ProcessingJob.tenant_id == auth.tenant_id
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in {JobStatus.FAILED, JobStatus.DEAD_LETTERED, JobStatus.RETRYING}:
        raise HTTPException(status_code=409, detail="Only failed jobs can be retried manually")
    add_audit_log(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="JOB_MANUAL_RETRY",
        resource_type="processing_job",
        resource_id=job.id,
        correlation_id=correlation_id(request),
        details={"stage": job.stage.value, "meeting_id": job.meeting_id},
    )
    await db.commit()
    task_id = enqueue_pipeline(
        job.meeting_id,
        auth.tenant_id,
        correlation_id(request),
        job.stage,
        force=True,
    )
    return {"task_id": task_id, "status": "accepted"}


"""File Intelligence Background Job Service with Database-Enforced Concurrency."""

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional
import uuid
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.errors import EntityNotFoundError, OperationInProgressError
from app.core.logging import logger
from app.db.models.file_job import FileJob, FileJobStatus, FileJobType
from app.db.session import async_session_factory
from app.schemas.file import FileJobResponse, JobSubmissionResponse
from app.runtime.events import event_hub


class FileJobService:
    """Dedicated authority for asynchronous file intelligence background operations."""

    async def create_job(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        job_type: str,
        file_id: Optional[uuid.UUID] = None,
        user_id: Optional[uuid.UUID] = None,
    ) -> FileJob:
        """Atomically register an active background job or fail with 409 Conflict."""
        # 1. Proactive active check (read phase)
        stmt_check = select(FileJob).where(
            FileJob.workspace_id == workspace_id,
            FileJob.file_id == file_id,
            FileJob.job_type == job_type,
            FileJob.status.in_([FileJobStatus.QUEUED.value, FileJobStatus.PROCESSING.value]),
        )
        res = await db.execute(stmt_check)
        existing = res.scalar_one_or_none()
        if existing:
            raise OperationInProgressError(
                f"An active '{job_type}' job is already in progress for this file",
                details={
                    "existing_job_id": str(existing.id),
                    "workspace_id": str(workspace_id),
                    "file_id": str(file_id) if file_id else None,
                    "job_type": job_type,
                    "status": existing.status,
                },
            )

        # 2. Atomic INSERT attempt
        job = FileJob(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            file_id=file_id,
            job_type=job_type,
            status=FileJobStatus.QUEUED.value,
            progress_pct=0,
            created_by=user_id,
            result_metadata={},
        )
        db.add(job)

        try:
            await db.commit()
            await db.refresh(job)
        except IntegrityError as exc:
            await db.rollback()
            logger.warning(
                f"FileJobService: Concurrency race detected on active job ({workspace_id}, {file_id}, {job_type}): {exc}"
            )
            raise OperationInProgressError(
                f"An active '{job_type}' job is already in progress for this file",
                details={
                    "workspace_id": str(workspace_id),
                    "file_id": str(file_id) if file_id else None,
                    "job_type": job_type,
                },
            ) from exc

        logger.info(f"FileJobService: Created active job {job.id} ({job_type}) for file {file_id} in workspace {workspace_id}")
        return job

    async def get_job(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        job_id: uuid.UUID,
    ) -> FileJob:
        """Authoritative status lookup with strict workspace scoping."""
        stmt = select(FileJob).where(
            FileJob.id == job_id,
            FileJob.workspace_id == workspace_id,
        )
        res = await db.execute(stmt)
        job = res.scalar_one_or_none()
        if not job:
            raise EntityNotFoundError(f"File job {job_id} not found in workspace {workspace_id}")
        return job

    async def update_job_status(
        self,
        db: AsyncSession,
        job_id: uuid.UUID,
        status: str,
        progress_pct: Optional[int] = None,
        error_summary: Optional[str] = None,
        result_metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[FileJob]:
        """Update job lifecycle state."""
        stmt = select(FileJob).where(FileJob.id == job_id)
        res = await db.execute(stmt)
        job = res.scalar_one_or_none()
        if not job:
            return None

        job.status = status
        now_utc = datetime.now(timezone.utc)
        if progress_pct is not None:
            job.progress_pct = progress_pct
        if error_summary is not None:
            job.error_summary = error_summary
        if result_metadata is not None:
            job.result_metadata = {**job.result_metadata, **result_metadata}

        if status == FileJobStatus.PROCESSING.value and not job.started_at:
            job.started_at = now_utc
        elif status in [FileJobStatus.COMPLETED.value, FileJobStatus.FAILED.value, FileJobStatus.CANCELLED.value]:
            job.completed_at = now_utc

        await db.commit()
        await db.refresh(job)
        return job

    async def recover_stuck_jobs(self, db: AsyncSession) -> int:
        """Startup crash recovery sweep marking interrupted in-flight jobs as failed."""
        now_utc = datetime.now(timezone.utc)
        stmt = (
            update(FileJob)
            .where(FileJob.status.in_([FileJobStatus.QUEUED.value, FileJobStatus.PROCESSING.value]))
            .values(
                status=FileJobStatus.FAILED.value,
                error_summary="Job interrupted by server restart; retry available",
                completed_at=now_utc,
            )
        )
        res = await db.execute(stmt)
        await db.commit()
        recovered_count = res.rowcount or 0
        if recovered_count > 0:
            logger.warning(f"FileJobService: Recovered {recovered_count} orphaned background jobs on server startup")
        return recovered_count

    def to_submission_response(self, job: FileJob) -> JobSubmissionResponse:
        """Format persistent job into canonical 202 submission response."""
        return JobSubmissionResponse(
            job_id=job.id,
            workspace_id=job.workspace_id,
            file_id=job.file_id,
            job_type=job.job_type,
            status=job.status,
            created_at=job.created_at,
        )

    def to_job_response(self, job: FileJob) -> FileJobResponse:
        """Format persistent job into canonical status response."""
        return FileJobResponse(
            job_id=job.id,
            workspace_id=job.workspace_id,
            file_id=job.file_id,
            job_type=job.job_type,
            status=job.status,
            progress_pct=job.progress_pct,
            error_summary=job.error_summary,
            result_metadata=job.result_metadata,
            started_at=job.started_at,
            completed_at=job.completed_at,
            created_at=job.created_at,
        )


file_job_service = FileJobService()

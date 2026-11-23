"""Job queue coordinator managing persistent job lifecycle and state transitions."""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import List, Optional
from app.database import db
from app.models import JobItem, JobStatus, ImageItem, PromptItem
from app.utils.logger import logger
from app.utils.signals import signals


class JobQueue:
    """Coordinates queue state, job population, and status persistence."""

    def __init__(self):
        self._is_paused: bool = False
        self._is_stopped: bool = False

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    @property
    def is_stopped(self) -> bool:
        return self._is_stopped

    def pause(self) -> None:
        """Pauses processing queue execution."""
        self._is_paused = True
        logger.info("JobQueue execution paused by user.")
        signals.queue_state_changed.emit("PAUSED")

    def resume(self) -> None:
        """Resumes processing queue execution."""
        self._is_paused = False
        logger.info("JobQueue execution resumed.")
        signals.queue_state_changed.emit("RUNNING")

    def stop(self) -> None:
        """Stops/cancels ongoing queue execution."""
        self._is_stopped = True
        self._is_paused = False
        logger.info("JobQueue execution stopped.")
        signals.queue_state_changed.emit("STOPPED")

    def reset_state(self) -> None:
        self._is_paused = False
        self._is_stopped = False

    def retry_jobs(self, job_ids: List[int]) -> int:
        """Resets specified jobs back to PENDING and notifies UI."""
        count = db.reset_jobs_to_pending(job_ids)
        if count > 0:
            logger.info("Reset %d jobs back to PENDING for retry.", count)
            signals.jobs_updated.emit()
        return count

    def retry_failed_jobs(self) -> int:
        """Resets all FAILED jobs back to PENDING and notifies UI."""
        count = db.reset_failed_jobs()
        if count > 0:
            logger.info("Reset %d failed jobs back to PENDING for retry.", count)
            signals.jobs_updated.emit()
        return count

    def populate_jobs(self, images: List[ImageItem], prompts: List[PromptItem]) -> List[JobItem]:
        """
        Creates matrix jobs (images x enabled prompts) in SQLite.
        Prompts are executed according to their execution_order.
        """
        enabled_prompts = [p for p in prompts if p.is_enabled]
        # Sort prompts by execution order
        enabled_prompts.sort(key=lambda p: (p.execution_order, p.id or 0))

        created_jobs: List[JobItem] = []
        for img in images:
            for p in enabled_prompts:
                job = JobItem(
                    id=None,
                    image_id=img.id,  # type: ignore
                    image_path=img.original_path,
                    prompt_id=p.id,  # type: ignore
                    prompt_text=p.content,
                    status=JobStatus.PENDING,
                )
                job_id = db.insert_job(job)
                job.id = job_id
                created_jobs.append(job)

        logger.info("Created %d new jobs in processing queue.", len(created_jobs))
        signals.jobs_updated.emit()
        return created_jobs

    def get_pending_jobs(self) -> List[JobItem]:
        return db.get_pending_jobs()

    def get_all_jobs(self) -> List[JobItem]:
        return db.get_all_jobs()

    def mark_job_status(
        self,
        job_id: int,
        status: JobStatus,
        output_path: Optional[str] = None,
        error_message: Optional[str] = None,
        increment_retry: bool = False,
    ) -> None:
        started_at = datetime.now().isoformat() if status == JobStatus.UPLOADING else None
        completed_at = datetime.now().isoformat() if status in (JobStatus.COMPLETED, JobStatus.FAILED) else None

        db.update_job_status(
            job_id=job_id,
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            output_path=output_path,
            error_message=error_message,
            increment_retry=increment_retry,
        )
        signals.job_status_changed.emit(job_id, status.value, error_message or "")
        signals.jobs_updated.emit()


job_queue = JobQueue()

"""Background Task Manager running asyncio event loop in a dedicated QThread."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional
from PySide6.QtCore import QThread, Signal
from app.config import config
from app.database import db
from app.models import JobStatus, OutputItem
from app.automation.job_queue import job_queue
from app.automation.image_processor import image_processor
from app.browser.browser_manager import browser_manager
from app.browser.download_manager import download_manager
from app.utils.logger import logger
from app.utils.signals import signals


class TaskManagerThread(QThread):
    """
    Dedicated QThread hosting an asyncio event loop.
    Ensures non-blocking GUI while Playwright and Download workers run seamlessly.
    """

    def __init__(self):
        super().__init__()
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._is_active = False

    def run(self) -> None:
        """Thread entry point: initializes and starts asyncio event loop."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self._is_active = True

        # Setup download manager callbacks
        download_manager.on_success = self._on_download_success
        download_manager.on_failure = self._on_download_failure

        # Start download workers
        download_manager.start(self.loop)

        logger.info("TaskManagerThread asyncio loop started.")
        try:
            self.loop.run_forever()
        finally:
            self.loop.close()
            logger.info("TaskManagerThread asyncio loop terminated.")

    def stop_loop(self) -> None:
        """Stops the asyncio loop and thread cleanly."""
        self._is_active = False
        if self.loop and self.loop.is_running():
            try:
                fut = asyncio.run_coroutine_threadsafe(download_manager.stop(), self.loop)
                fut.result(timeout=2.0)
            except Exception as e:
                logger.debug("Error awaiting download manager stop: %s", e)
            self.loop.call_soon_threadsafe(self.loop.stop)
        self.wait(5000)

    def dispatch_coroutine(self, coro):
        """Schedules a coroutine on the background thread's asyncio loop."""
        if not self.loop or not self.loop.is_running():
            raise RuntimeError("Asyncio loop is not running.")
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def start_pipeline(self) -> None:
        """Launches the sequential generation pipeline."""
        job_queue.reset_state()
        self.dispatch_coroutine(self._run_queue_pipeline())

    async def _run_queue_pipeline(self) -> None:
        """Asynchronously iterates through pending jobs sequentially."""
        logger.info("Starting processing queue pipeline...")
        signals.queue_state_changed.emit("RUNNING")

        # Recover any interrupted jobs if necessary
        db.recover_interrupted_jobs()

        while not job_queue.is_stopped:
            # Handle pause
            while job_queue.is_paused:
                if job_queue.is_stopped:
                    break
                await asyncio.sleep(1.0)

            if job_queue.is_stopped:
                break

            pending_jobs = job_queue.get_pending_jobs()
            all_jobs = job_queue.get_all_jobs()
            total_jobs = len(all_jobs)
            completed_jobs = len([j for j in all_jobs if j.status == JobStatus.COMPLETED])
            signals.queue_progress.emit(completed_jobs, total_jobs)

            if not pending_jobs:
                logger.info("All pending jobs have been processed.")
                break

            current_job = pending_jobs[0]

            # Fetch prompt metadata for clean naming
            prompts = db.get_all_prompts()
            prompt_map = {p.id: p for p in prompts}
            prompt_item = prompt_map.get(current_job.prompt_id)
            prompt_order = prompt_item.execution_order if prompt_item else 1
            prompt_name = prompt_item.name if prompt_item else "Prompt"

            # Execute sequential generation
            success = await image_processor.process_job(
                current_job, prompt_order=prompt_order, prompt_name=prompt_name
            )

            # Polling pause between jobs to be gentle with browser
            await asyncio.sleep(2.0)

        signals.queue_state_changed.emit("IDLE")
        signals.jobs_updated.emit()
        logger.info("Pipeline run cycle completed.")

    async def _on_download_success(self, job_id: int, final_path: Path, meta: dict) -> None:
        """Invoked when an image download and verification succeeds."""
        logger.info("Download verified successfully for Job #%d: %s", job_id, final_path)

        # Performance measurements aggregation
        perf = getattr(image_processor, "last_performance_report", {})
        upload_d = perf.get("upload_duration", 0.0)
        gen_d = perf.get("generation_duration", 0.0)
        extract_d = perf.get("extraction_duration", 0.0)
        dl_d = meta.get("download_duration", 0.0)
        val_d = meta.get("validation_duration", 0.0)
        total_d = upload_d + gen_d + extract_d + dl_d + val_d

        logger.info("================ PERFORMANCE AUDIT REPORT ================")
        logger.info(" Job ID:               #%d", job_id)
        logger.info(" Output Path:          %s", final_path.name)
        logger.info(" Dimensions:           %dx%d", meta.get("width", 0), meta.get("height", 0))
        logger.info(" Format:               %s", meta.get("detected_format", "PNG"))
        logger.info(" File Size:            %d bytes (%.2f KB)", meta.get("file_size", 0), meta.get("file_size", 0)/1024.0)
        logger.info(" ---------------------------------------------------------")
        logger.info(" 1. Upload Duration:     %.4f s", upload_d)
        logger.info(" 2. Generation Duration: %.4f s", gen_d)
        logger.info(" 3. Extraction Duration: %.4f s", extract_d)
        logger.info(" 4. Download Duration:   %.4f s", dl_d)
        logger.info(" 5. Validation Duration: %.4f s", val_d)
        logger.info(" TOTAL DURATION:         %.4f s", total_d)
        logger.info("==========================================================")

        # Get job info to create output item
        job = db.get_job(job_id)
        if job:
            output_item = OutputItem(
                id=None,
                job_id=job_id,
                image_id=job.image_id,
                prompt_id=job.prompt_id,
                file_path=str(final_path),
                file_size=meta.get("file_size", 0),
                width=meta.get("width", 0),
                height=meta.get("height", 0),
            )
            db.insert_output(output_item)

        # Mark job as COMPLETED
        job_queue.mark_job_status(job_id, JobStatus.COMPLETED, output_path=str(final_path))
        signals.download_completed.emit(job_id, str(final_path))

    async def _on_download_failure(self, job_id: int, error_message: str) -> None:
        """Invoked when an image download fails permanently."""
        logger.error("Download failed permanently for Job #%d: %s", job_id, error_message)
        job_queue.mark_job_status(job_id, JobStatus.FAILED, error_message=error_message)
        signals.download_failed.emit(job_id, error_message)


task_manager = TaskManagerThread()

"""Sequential processor executing image generation pipeline on ChatGPT."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Optional, Dict, Any
from app.config import config
from app.database import db
from app.models import JobItem, JobStatus, OutputItem
from app.browser.browser_manager import browser_manager
from app.browser.chatgpt_controller import chatgpt_controller, ChatGPTControllerError
from app.browser.download_manager import download_manager, DownloadTask
from app.storage.file_manager import file_manager
from app.utils.logger import logger
from app.utils.signals import signals


class ImageProcessor:
    """Executes single-job browser generation with high-resolution lifecycle metrics."""

    def __init__(self):
        self.last_performance_report: Dict[str, Any] = {}

    async def process_job(self, job: JobItem, prompt_order: int, prompt_name: str) -> bool:
        """
        Executes generation workflow for one JobItem:
        1. Ensures browser page is ready on ChatGPT.
        2. Copies original image safely into product folder structure.
        3. Uploads original image (measures upload duration).
        4. Submits prompt.
        5. Observes generation completion (measures generation duration).
        6. Captures download event or extracts high-res source (measures extraction duration).
        7. Enqueues download task to asynchronous download workers.
        """
        t_job_start = time.perf_counter()
        logger.info("=== Starting Execution for Job #%d ===", job.id)
        signals.job_status_changed.emit(job.id, JobStatus.UPLOADING.value, "")
        db.update_job_status(job.id, JobStatus.UPLOADING)

        page = browser_manager.page
        if not page or page.is_closed():
            err = "Browser is not running or page is closed."
            logger.error(err)
            db.update_job_status(job.id, JobStatus.FAILED, error_message=err)
            signals.job_status_changed.emit(job.id, JobStatus.FAILED.value, err)
            return False

        # Get or create active batch folder (Desktop/XInvora Photos/Batch N - Date)
        batch_folder = file_manager.get_or_create_batch_folder()

        # Compute sequential product index (Product 1, Product 2, ... Product 50)
        all_imgs = db.get_all_images()
        img_id_to_idx = {img.id: idx + 1 for idx, img in enumerate(all_imgs)}
        image_index = img_id_to_idx.get(job.image_id, job.image_id)

        try:
            # 1. Upload original image with high-resolution timing
            t_upload_start = time.perf_counter()
            upload_duration = await chatgpt_controller.upload_image(page, Path(job.image_path))

            # 2. Enter and submit prompt
            await chatgpt_controller.enter_and_submit_prompt(page, job.prompt_text)

            # 3. Transition to GENERATING
            db.update_job_status(job.id, JobStatus.GENERATING)
            signals.job_status_changed.emit(job.id, JobStatus.GENERATING.value, "")

            # 4. Wait for generation to complete with high-res measurement
            t_extract_start = time.perf_counter()
            success, image_results, err_msg, gen_duration = (
                await chatgpt_controller.wait_for_generation_complete(
                    page, timeout_seconds=config.generation_timeout_seconds
                )
            )
            extraction_duration = time.perf_counter() - t_extract_start

            if not success or not image_results:
                err = err_msg or "Generation finished without detectable output image or download."
                logger.error("Job #%d failed: %s", job.id, err)
                db.update_job_status(job.id, JobStatus.FAILED, error_message=err, increment_retry=True)
                signals.job_status_changed.emit(job.id, JobStatus.FAILED.value, err)
                return False

            # 5. Hand over to Download Manager (status: DOWNLOADING)
            db.update_job_status(job.id, JobStatus.DOWNLOADING)
            signals.job_status_changed.emit(job.id, JobStatus.DOWNLOADING.value, "")

            is_multi = len(image_results) > 1
            if is_multi:
                logger.info(
                    "ChatGPT generated %d outputs for Job #%d! Enqueueing all to product folder.",
                    len(image_results), job.id
                )

            # Enqueue all generated outputs (images, markdown files, file downloads)
            for i, res in enumerate(image_results):
                res_type = res.get("type", "image")
                dl_obj = res.get("download")
                img_src = res.get("src")
                md_content = res.get("content")
                variant_label = f"v{i+1}" if is_multi else None

                if res_type == "markdown":
                    source_type = "markdown_text"
                elif res_type == "file" or dl_obj:
                    source_type = "playwright_download"
                else:
                    source_type = "image_url"

                download_task = DownloadTask(
                    job_id=job.id,  # type: ignore
                    batch_folder=batch_folder,
                    image_index=image_index,
                    prompt_order=prompt_order,
                    prompt_name=prompt_name,
                    source_type=source_type,
                    download_obj=dl_obj,
                    image_url=img_src,
                    markdown_content=md_content,
                    context_page=page,
                    variant=variant_label,
                    max_retries=config.max_retries_per_job,
                )
                await download_manager.enqueue(download_task)

            # Store preliminary timings
            total_duration_so_far = time.perf_counter() - t_job_start
            self.last_performance_report = {
                "job_id": job.id,
                "upload_duration": upload_duration,
                "generation_duration": gen_duration,
                "extraction_duration": extraction_duration,
                "total_browser_duration": total_duration_so_far,
                "variants_count": len(image_results),
            }

            logger.info(
                "Job #%d Browser Phase Complete: Upload: %.2fs | Gen: %.2fs | Extract: %.2fs | Variants: %d | Browser Total: %.2fs",
                job.id, upload_duration, gen_duration, extraction_duration, len(image_results), total_duration_so_far
            )
            return True

        except Exception as e:
            logger.exception("Unexpected error during Job #%d: %s", job.id, e)
            db.update_job_status(job.id, JobStatus.FAILED, error_message=str(e), increment_retry=True)
            signals.job_status_changed.emit(job.id, JobStatus.FAILED.value, str(e))
            return False


image_processor = ImageProcessor()

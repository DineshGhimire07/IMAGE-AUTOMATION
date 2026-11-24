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
        # URLs of images captured in the last job — read by task_manager to populate seen_image_srcs
        self.last_seen_image_srcs: set = set()

    @staticmethod
    def _is_markdown_job(job: JobItem, prompt_order: int, prompt_name: str) -> bool:
        """Determines if a prompt is intended to produce a .md file instead of an image."""
        name_lower = (prompt_name or "").lower()
        text_lower = (job.prompt_text or "").lower()

        md_indicators = [
            "markdown", ".md", "seo generator", "seo + markdown", "seo specialist",
            "daraz poster seo", "product listing in a downloadable", "yaml frontmatter"
        ]
        for ind in md_indicators:
            if ind in name_lower or ind in text_lower:
                return True

        if prompt_order == 3 and any(k in text_lower for k in ("listing", "seo", "description", "daraz", "markdown")):
            return True

        return False

    async def process_job(
        self,
        job: JobItem,
        prompt_order: int,
        prompt_name: str,
        is_new_product: bool = True,
        known_image_srcs: Optional[set] = None,
    ) -> bool:
        """
        Executes ONE step in the pipeline for a single JobItem.

        The pipeline follows this EXACT sequence per product:
        ┌─────────────────────────────────────────────────────────┐
        │  Prompt 1:  Upload photo  → Send Prompt 1 → Wait → Save  │
        │  Prompt 2:  (no upload)   → Send Prompt 2 → Wait → Save  │
        │  Prompt 3:  (no upload)   → Send Prompt 3 → Wait → Save .md │
        │  Next product:                                            │
        │  Prompt 1:  Upload photo2 → Send Prompt 1 → Wait → Save  │
        │  ...                                                      │
        └─────────────────────────────────────────────────────────┘

        Rules:
        - Image is uploaded ONLY for Prompt 1 of each product (is_new_product=True).
        - Prompts 2 and 3 are sent as text ONLY inside the same chat; ChatGPT already
          has the image in context.
        - Prompt text is NEVER modified; it is sent exactly as stored in the library.
        - Prompt 3 is detected as markdown; timeout is extended to 480 seconds for it.
        """
        t_job_start = time.perf_counter()
        logger.info(
            "=== STEP START: Job #%d | Product Prompt %d ('%s') | New Product: %s ===",
            job.id, prompt_order, prompt_name, is_new_product
        )

        signals.job_status_changed.emit(job.id, JobStatus.UPLOADING.value, "")
        db.update_job_status(job.id, JobStatus.UPLOADING)

        page = browser_manager.page
        if not page or page.is_closed():
            err = "Browser is not running or page is closed."
            logger.error(err)
            db.update_job_status(job.id, JobStatus.FAILED, error_message=err)
            signals.job_status_changed.emit(job.id, JobStatus.FAILED.value, err)
            return False

        batch_folder = file_manager.get_or_create_batch_folder()

        all_imgs = db.get_all_images()
        img_id_to_idx = {img.id: idx + 1 for idx, img in enumerate(all_imgs)}
        image_index = img_id_to_idx.get(job.image_id, job.image_id)

        is_md = self._is_markdown_job(job, prompt_order, prompt_name)

        # Markdown (Prompt 3) needs much more time — ChatGPT generates a file, not just text
        timeout_seconds = config.markdown_timeout_seconds if is_md else config.generation_timeout_seconds

        try:
            # ─────────────────────────────────────────────────────────────
            # STEP 1: Upload photo for this prompt
            # Every prompt (1, 2, 3) receives the product's source image attached,
            # so ChatGPT always references the correct image for each step.
            # ─────────────────────────────────────────────────────────────
            img_file = Path(job.image_path)
            logger.info(
                "STEP 1 — Uploading source image for Product %02d (Job #%d, Prompt %d): %s",
                image_index, job.id, prompt_order, img_file.name
            )
            upload_duration = await chatgpt_controller.upload_image(page, img_file)
            logger.info("STEP 1 — Upload complete (%.2fs)", upload_duration)

            # ─────────────────────────────────────────────────────────────
            # STEP 2: Send prompt text (exact, unmodified)
            # ─────────────────────────────────────────────────────────────
            logger.info(
                "STEP 2 — Sending Prompt %d for Product %02d (Job #%d): '%s...'",
                prompt_order, image_index, job.id, job.prompt_text[:60]
            )
            await chatgpt_controller.enter_and_submit_prompt(page, job.prompt_text)
            logger.info("STEP 2 — Prompt submitted.")

            # ─────────────────────────────────────────────────────────────
            # STEP 3: Transition status → GENERATING
            # ─────────────────────────────────────────────────────────────
            db.update_job_status(job.id, JobStatus.GENERATING)
            signals.job_status_changed.emit(job.id, JobStatus.GENERATING.value, "")
            logger.info(
                "STEP 3 — Waiting for ChatGPT to generate (timeout: %ds, mode: %s)...",
                timeout_seconds, "MARKDOWN" if is_md else "IMAGE"
            )

            # ─────────────────────────────────────────────────────────────
            # STEP 4: Wait for generation to complete
            # ─────────────────────────────────────────────────────────────
            t_extract_start = time.perf_counter()
            success, image_results, err_msg, gen_duration = (
                await chatgpt_controller.wait_for_generation_complete(
                    page,
                    timeout_seconds=timeout_seconds,
                    is_markdown=is_md,
                    known_image_srcs=known_image_srcs,
                )
            )
            extraction_duration = time.perf_counter() - t_extract_start

            if not success or not image_results:
                err = err_msg or ("Markdown generation failed" if is_md else "Image generation failed without detectable output")
                logger.error("STEP 4 — Job #%d FAILED: %s", job.id, err)
                db.update_job_status(job.id, JobStatus.FAILED, error_message=err, increment_retry=True)
                signals.job_status_changed.emit(job.id, JobStatus.FAILED.value, err)
                return False

            logger.info(
                "STEP 4 — Generation complete in %.2fs. Got %d output(s).",
                gen_duration, len(image_results)
            )

            # ─────────────────────────────────────────────────────────────
            # STEP 5: Download & save output to product folder
            # ─────────────────────────────────────────────────────────────
            db.update_job_status(job.id, JobStatus.DOWNLOADING)
            signals.job_status_changed.emit(job.id, JobStatus.DOWNLOADING.value, "")
            logger.info(
                "STEP 5 — Saving output(s) to Product %02d folder...",
                image_index
            )

            is_multi = len(image_results) > 1
            # Record this job's image URLs so the next prompt knows to skip them
            self.last_seen_image_srcs = {
                res.get("src") for res in image_results if res.get("src")
            }
            for i, res in enumerate(image_results):
                res_type = res.get("type", "image")
                dl_obj = res.get("download")
                img_src = res.get("src")
                md_content = res.get("content")
                variant_label = f"v{i+1}" if is_multi else None

                if is_md or res_type == "markdown":
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
                "=== STEP DONE: Job #%d | Upload: %.2fs | Gen: %.2fs | Total: %.2fs ===",
                job.id, upload_duration, gen_duration, total_duration_so_far
            )
            return True

        except Exception as e:
            logger.exception("Unexpected error during Job #%d: %s", job.id, e)
            db.update_job_status(job.id, JobStatus.FAILED, error_message=str(e), increment_retry=True)
            signals.job_status_changed.emit(job.id, JobStatus.FAILED.value, str(e))
            return False


image_processor = ImageProcessor()

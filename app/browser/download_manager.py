"""Asynchronous Image Download Manager with validation and worker pool."""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Callable, Awaitable
from app.config import config
from app.utils.logger import logger
from app.storage.image_validator import ImageValidator
from app.storage.file_manager import file_manager


@dataclass
class DownloadTask:
    job_id: int
    batch_folder: Path
    image_index: int
    prompt_order: int
    prompt_name: str
    source_type: str  # "playwright_download", "image_url", "markdown_text"
    download_obj: Optional[Any] = None  # playwright.async_api.Download
    image_url: Optional[str] = None
    markdown_content: Optional[str] = None
    context_page: Optional[Any] = None  # page reference to evaluate fetch if needed
    variant: Optional[str] = None  # e.g. "v1", "v2" when multiple options generated
    retries: int = 0
    max_retries: int = 3


class DownloadManager:
    """
    Decoupled asynchronous download queue and worker pool.
    Saves via .part files, runs Pillow validation, and atomically renames.
    """

    def __init__(self, num_workers: int = 2):
        self.num_workers = num_workers
        self.queue: asyncio.Queue[DownloadTask] = asyncio.Queue()
        self.worker_tasks: list[asyncio.Task] = []
        self._is_running = False
        self.on_success: Optional[Callable[[int, Path, dict], Awaitable[None]]] = None
        self.on_failure: Optional[Callable[[int, str], Awaitable[None]]] = None

    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        """Starts background download workers on the given event loop."""
        if self._is_running:
            return

        self._is_running = True
        current_loop = loop or asyncio.get_event_loop()
        self.worker_tasks = [
            current_loop.create_task(self._worker(f"worker-{i+1}"))
            for i in range(self.num_workers)
        ]
        logger.info("DownloadManager started with %d workers.", self.num_workers)

    async def stop(self) -> None:
        """Gracefully stops download workers."""
        self._is_running = False
        for task in self.worker_tasks:
            task.cancel()
        await asyncio.gather(*self.worker_tasks, return_exceptions=True)
        self.worker_tasks.clear()
        logger.info("DownloadManager workers stopped.")

    async def enqueue(self, task: DownloadTask) -> None:
        """Pushes a download job to the async queue."""
        logger.info("Enqueued download task for job #%d (%s)", task.job_id, task.prompt_name)
        await self.queue.put(task)

    async def _worker(self, worker_name: str) -> None:
        logger.debug("Download worker %s initialized.", worker_name)
        while self._is_running:
            try:
                task = await self.queue.get()
            except asyncio.CancelledError:
                break

            try:
                logger.info("[%s] Processing download for job #%d", worker_name, task.job_id)
                success, target_path, meta = await self._process_task(task)
                if success and target_path and meta:
                    if self.on_success:
                        await self.on_success(task.job_id, target_path, meta)
                else:
                    if task.retries < task.max_retries:
                        task.retries += 1
                        logger.warning(
                            "[%s] Retrying download for job #%d (attempt %d/%d)",
                            worker_name, task.job_id, task.retries, task.max_retries
                        )
                        await asyncio.sleep(2.0)
                        await self.queue.put(task)
                    else:
                        err_msg = f"Failed to download and verify output after {task.max_retries} attempts."
                        logger.error("[%s] %s for job #%d", worker_name, err_msg, task.job_id)
                        if self.on_failure:
                            await self.on_failure(task.job_id, err_msg)
            except Exception as e:
                logger.exception("[%s] Unexpected exception during download for job #%d: %s", worker_name, task.job_id, e)
                if self.on_failure:
                    await self.on_failure(task.job_id, str(e))
            finally:
                self.queue.task_done()

    async def _process_task(self, task: DownloadTask) -> tuple[bool, Optional[Path], Optional[dict]]:
        """
        Executes saving to .part file, running Pillow validation, and atomically renaming.
        """
        # Ensure target batch folder exists
        task.batch_folder.mkdir(parents=True, exist_ok=True)
        temp_dir = task.batch_folder / ".temp"
        temp_dir.mkdir(parents=True, exist_ok=True)

        part_id = uuid.uuid4().hex[:8]
        part_path = temp_dir / f"download_{task.job_id}_{part_id}.part"

        t_dl_start = time.perf_counter()
        try:
            # 1. Markdown text output directly from ChatGPT response
            if task.source_type == "markdown_text" or task.markdown_content:
                logger.info("Writing generated markdown output for Job #%d...", task.job_id)
                part_path.write_text(task.markdown_content or "", encoding="utf-8")
                dl_duration = time.perf_counter() - t_dl_start

                t_val_start = time.perf_counter()
                meta = ImageValidator.validate_markdown_file(part_path)
                val_duration = time.perf_counter() - t_val_start
                ext = ".md"
                detected_fmt = "MD"

            # 2. Download via Playwright Download Event (Original Quality)
            elif task.source_type == "playwright_download" and task.download_obj:
                logger.info("Saving via Playwright native download event...")
                await task.download_obj.save_as(str(part_path))
                dl_duration = time.perf_counter() - t_dl_start

                suggested = getattr(task.download_obj, "suggested_filename", "") or ""
                t_val_start = time.perf_counter()
                if suggested.lower().endswith((".md", ".txt", ".markdown")):
                    meta = ImageValidator.validate_markdown_file(part_path)
                    ext = ".md"
                    detected_fmt = "MD"
                else:
                    meta = ImageValidator.validate_image_file(part_path, allow_part=True)
                    detected_fmt = meta.get("format", "PNG").upper()
                    if detected_fmt in ("JPEG", "JPG"):
                        ext = ".jpg"
                    elif detected_fmt == "WEBP":
                        ext = ".webp"
                    else:
                        ext = ".png"
                val_duration = time.perf_counter() - t_val_start

            # 3. Download via image URL inside page context (bypasses CORS/cookies)
            elif task.source_type == "image_url" and task.image_url and task.context_page:
                logger.info("Fetching original image bytes via page context...")
                image_bytes = await self._fetch_image_bytes(task.context_page, task.image_url)
                if not image_bytes or len(image_bytes) == 0:
                    logger.warning("Empty response received fetching image URL: %s", task.image_url)
                    return False, None, None
                part_path.write_bytes(image_bytes)
                dl_duration = time.perf_counter() - t_dl_start

                t_val_start = time.perf_counter()
                meta = ImageValidator.validate_image_file(part_path, allow_part=True)
                val_duration = time.perf_counter() - t_val_start

                detected_fmt = meta.get("format", "PNG").upper()
                if detected_fmt in ("JPEG", "JPG"):
                    ext = ".jpg"
                elif detected_fmt == "WEBP":
                    ext = ".webp"
                else:
                    ext = ".png"

            else:
                logger.error("Unknown download task configuration: %s", task)
                return False, None, None

            # Verify .part file exists and size > 0
            if not part_path.exists() or part_path.stat().st_size == 0:
                logger.warning("Downloaded part file is empty or missing: %s", part_path)
                return False, None, None

            # Atomic save directly into product folder inside batch folder
            target_path = file_manager.get_output_target_path(
                batch_folder=task.batch_folder,
                image_index=task.image_index,
                prompt_order=task.prompt_order,
                variant=task.variant,
                ext=ext
            )

            final_path = file_manager.atomic_save_part(part_path, target_path, allow_overwrite=True)
            meta["final_path"] = str(final_path)
            meta["download_duration"] = dl_duration
            meta["validation_duration"] = val_duration
            meta["detected_format"] = detected_fmt

            logger.info(
                "Verified and saved output: %s (%dx%d %s, %d bytes) [DL: %.2fs, Val: %.4fs]",
                final_path.name, meta["width"], meta["height"], detected_fmt, meta["file_size"],
                dl_duration, val_duration
            )
            return True, final_path, meta

        except Exception as e:
            logger.error("Download processing error for job #%d: %s", task.job_id, e)
            if part_path.exists():
                try:
                    part_path.unlink()
                except OSError:
                    pass
            return False, None, None

    async def _fetch_image_bytes(self, page: Any, url: str) -> Optional[bytes]:
        """Fetches binary image data via Playwright authenticated API request context or in-page blob evaluation."""
        if not url.startswith("blob:"):
            try:
                response = await page.context.request.get(url, timeout=30000)
                if response.status == 200:
                    return await response.body()
                logger.warning("Failed to fetch image bytes from %s: HTTP %d", url, response.status)
            except Exception as e:
                logger.warning("Error fetching image bytes from page context: %s", e)

        # In-page fetch fallback (essential for blob: URLs and CORS restricted sessions)
        try:
            b64_data = await page.evaluate("""async (imgUrl) => {
                const res = await fetch(imgUrl);
                const blob = await res.blob();
                return new Promise((resolve, reject) => {
                    const reader = new FileReader();
                    reader.onloadend = () => resolve(reader.result.split(',')[1]);
                    reader.onerror = reject;
                    reader.readAsDataURL(blob);
                });
            }""", url)
            if b64_data:
                import base64
                return base64.b64decode(b64_data)
        except Exception as e:
            logger.error("In-page blob evaluation fetch failed: %s", e)

        return None


download_manager = DownloadManager(num_workers=config.download_workers_count)

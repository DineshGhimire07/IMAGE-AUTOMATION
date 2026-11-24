"""Controller for ChatGPT web conversation, file uploads, and generation lifecycle."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Optional, Tuple, Any
from playwright.async_api import Page, Locator, Download
from app.browser.page_detector import selectors
from app.utils.logger import logger


class ChatGPTControllerError(Exception):
    """Raised when an operation on the ChatGPT web interface fails."""
    pass


class ChatGPTController:
    """Interacts with ChatGPT UI via accessible, observable locators."""

    @staticmethod
    async def find_prompt_input(page: Page) -> Optional[Locator]:
        """Locates the active message input area."""
        for sel in selectors.prompt_input:
            loc = page.locator(sel)
            if await loc.count() > 0 and await loc.first.is_visible():
                return loc.first
        return None

    @staticmethod
    async def upload_image(page: Page, image_path: Path, timeout_ms: int = 30000) -> float:
        """
        Uploads an image file to ChatGPT composer using file chooser or file input.
        Verifies upload thumbnail preview appears without arbitrary long sleeps.
        Returns upload duration in seconds (high-resolution).
        """
        t0 = time.perf_counter()
        path_str = str(image_path.resolve())
        logger.info("Uploading image to ChatGPT: %s", image_path.name)

        try:
            # First strategy: look for hidden input[type="file"]
            file_input = page.locator("input[type='file']")
            if await file_input.count() > 0:
                await file_input.first.set_input_files(path_str)
                logger.debug("Set input files directly via input[type=file]")
            else:
                # Second strategy: click attach button with file chooser
                attach_btn = None
                for sel in selectors.attach_buttons:
                    loc = page.locator(sel)
                    if await loc.count() > 0 and await loc.first.is_visible():
                        attach_btn = loc.first
                        break

                if not attach_btn:
                    raise ChatGPTControllerError("Unable to locate ChatGPT file attachment button or input.")

                async with page.expect_file_chooser(timeout=timeout_ms) as fc_info:
                    await attach_btn.click()
                file_chooser = await fc_info.value
                await file_chooser.set_files(path_str)
                logger.debug("Uploaded file via Playwright file chooser.")

            # Explicit polling wait: wait until upload indicator / thumbnail is visible
            # or send button is enabled, instead of fixed sleep
            poll_start = time.perf_counter()
            uploaded = False
            while (time.perf_counter() - poll_start) < (timeout_ms / 1000.0):
                # Check for preview thumbnail / pills
                preview_loc = page.locator("[data-testid*='attachment'], [data-testid*='file'], [class*='attachment'], img[src^='blob:']")
                if await preview_loc.count() > 0:
                    uploaded = True
                    break

                # Or check if send button is now ready
                for sel in selectors.send_buttons:
                    send_loc = page.locator(sel)
                    if await send_loc.count() > 0 and await send_loc.first.is_visible():
                        uploaded = True
                        break
                if uploaded:
                    break
                await asyncio.sleep(0.3)

            duration = time.perf_counter() - t0
            logger.info("Image upload completed in %.2fs", duration)
            return duration

        except Exception as e:
            logger.error("Failed to upload image %s: %s", image_path.name, e)
            raise ChatGPTControllerError(f"Image upload failed: {e}") from e

    @staticmethod
    async def enter_and_submit_prompt(page: Page, prompt_text: str) -> None:
        """Enters prompt text into the composer and clicks Send with overlay auto-dismissal."""
        logger.info("Entering prompt: '%s...'", prompt_text[:60])

        # Dismiss any modal dialog or overlay if present
        try:
            close_btn = page.locator("button[aria-label*='Close'], button[data-testid*='close'], button:has-text('Close')")
            if await close_btn.count() > 0 and await close_btn.first.is_visible():
                await close_btn.first.click(timeout=1500)
            await page.keyboard.press("Escape")
        except Exception:
            pass

        input_loc = await ChatGPTController.find_prompt_input(page)
        if not input_loc:
            raise ChatGPTControllerError("ChatGPT prompt textarea could not be found.")

        # Focus and fill with fallback
        try:
            await input_loc.click(timeout=4000)
        except Exception:
            # Force focus directly if overlay or animation intercepts pointer
            logger.debug("Click on prompt input timed out, using direct focus.")
            await input_loc.focus()

        await input_loc.fill(prompt_text)
        await asyncio.sleep(0.3)

        # Locate send button
        send_btn = None
        for sel in selectors.send_buttons:
            loc = page.locator(sel)
            if await loc.count() > 0 and await loc.first.is_enabled():
                send_btn = loc.first
                break

        if send_btn:
            await send_btn.click()
        else:
            # Fallback: Press Enter on the input
            logger.debug("Send button not found or disabled, pressing Enter key.")
            await input_loc.press("Enter")

        logger.info("Prompt submitted successfully.")

    @staticmethod
    async def check_for_errors(page: Page) -> Optional[str]:
        """Checks if ChatGPT displayed any error banner or moderation message."""
        try:
            for sel in selectors.error_banners:
                loc = page.locator(sel)
                count = await loc.count()
                for i in range(count):
                    el = loc.nth(i)
                    if await el.is_visible():
                        text = (await el.inner_text()).strip()
                        if text and ("error" in text.lower() or "limit" in text.lower() or "wrong" in text.lower()):
                            return text
        except Exception as e:
            logger.debug("Error check locator query exception ignored: %s", e)
        return None

    @classmethod
    async def wait_for_generation_complete(
        cls,
        page: Page,
        timeout_seconds: int = 240,
        poll_interval: float = 1.0,
        is_markdown: bool = False,
    ) -> Tuple[bool, list[dict[str, Any]], Optional[str], float]:
        """
        Observes generation lifecycle:
        1. Waits for generation to start (stop button or response streaming).
        2. Waits for stop button to disappear.
        3. If is_markdown=True:
           Extracts generated .md file or markdown text listing; NEVER downloads an image.
        4. If is_markdown=False:
           Scans for all newly rendered generated images in the assistant's turn (handles 1 or 2 options).
        """
        logger.info(
            "Waiting for generation to start and complete (timeout: %ds, mode: %s)...",
            timeout_seconds, "MARKDOWN" if is_markdown else "IMAGE"
        )
        t_gen_start = time.perf_counter()
        generation_started = False

        # Phase 1: Wait up to 15s for generation to be marked active
        while (time.perf_counter() - t_gen_start) < 15.0:
            err = await cls.check_for_errors(page)
            if err:
                return False, [], f"ChatGPT Error: {err}", time.perf_counter() - t_gen_start

            for sel in selectors.stop_buttons:
                loc = page.locator(sel)
                if await loc.count() > 0 and await loc.first.is_visible():
                    generation_started = True
                    logger.debug("Generation active (stop button visible).")
                    break
            if generation_started:
                break
            await asyncio.sleep(0.5)

        # Phase 2: Monitor until generation completes
        while (time.perf_counter() - t_gen_start) < timeout_seconds:
            err = await cls.check_for_errors(page)
            if err:
                return False, [], f"Generation failed with error: {err}", time.perf_counter() - t_gen_start

            is_still_generating = False
            for sel in selectors.stop_buttons:
                loc = page.locator(sel)
                if await loc.count() > 0 and await loc.first.is_visible():
                    is_still_generating = True
                    break

            if not is_still_generating:
                # Generation finished: extract outputs
                # -------------------------------------------------------------
                # Branch A: Markdown Prompt Mode (Job is intended for .md file)
                # -------------------------------------------------------------
                if is_markdown:
                    # Check for native file download button for a .md or text file
                    file_download_obj: Optional[Download] = None
                    file_dl_loc = page.locator("a[download*='.md'], a:has-text('.md'), button:has-text('Download'), [data-testid*='download']")
                    if await file_dl_loc.count() > 0 and await file_dl_loc.first.is_visible():
                        try:
                            logger.info("Found .md file download button. Triggering expect_download()...")
                            async with page.expect_download(timeout=5000) as dl_info:
                                await file_dl_loc.first.click()
                            dl_val = await dl_info.value
                            if dl_val.suggested_filename.lower().endswith((".md", ".txt", ".markdown")):
                                file_download_obj = dl_val
                        except Exception as e:
                            logger.debug("File download expect failed: %s", e)

                    # Extract the full markdown text / YAML frontmatter from the assistant turn
                    md_content = ""
                    try:
                        md_data = await page.evaluate("""() => {
                            const turns = document.querySelectorAll("[data-message-author-role='assistant']");
                            if (!turns || turns.length === 0) return { fullText: '', codeContent: '' };
                            const turn = turns[turns.length - 1];

                            const codeBlocks = turn.querySelectorAll('pre code');
                            let codeContent = '';
                            if (codeBlocks.length > 0) {
                                const blocks = [];
                                for (const cb of codeBlocks) {
                                    blocks.push(cb.innerText);
                                }
                                codeContent = blocks.join('\\n\\n');
                            }

                            const clone = turn.cloneNode(true);
                            const removeEls = clone.querySelectorAll("button, [role='button'], svg, img, [class*='button']");
                            removeEls.forEach(el => el.remove());
                            const fullText = (clone.innerText || '').trim();

                            return { fullText: fullText, codeContent: codeContent };
                        }""")
                        if md_data:
                            md_content = md_data.get("codeContent") or md_data.get("fullText") or ""
                    except Exception as md_err:
                        logger.debug("Markdown extraction evaluation failed: %s", md_err)

                    if file_download_obj or (md_content and len(md_content.strip()) >= 5):
                        gen_duration = time.perf_counter() - t_gen_start
                        logger.info(
                            "Generation finished in %.2fs. Captured Markdown output (%d chars).",
                            gen_duration, len(md_content)
                        )
                        results = [{
                            "type": "markdown",
                            "content": md_content.strip(),
                            "download": file_download_obj,
                        }]
                        return True, results, None, gen_duration

                # -------------------------------------------------------------
                # Branch B: Image Prompt Mode (Default: Job expects photo)
                # -------------------------------------------------------------
                else:
                    img_candidates: list[tuple[Locator, str]] = []

                    # First check images inside the latest assistant message turn
                    assistant_turns = page.locator("[data-message-author-role='assistant']")
                    if await assistant_turns.count() > 0:
                        turn_imgs = assistant_turns.last.locator("img")
                        count = await turn_imgs.count()
                        for idx in range(count):
                            el = turn_imgs.nth(idx)
                            if await el.is_visible():
                                src_val = await el.get_attribute("src")
                                if src_val and not src_val.startswith("data:image/svg"):
                                    img_candidates.append((el, src_val))

                    # Fallback to general selectors if assistant turn locator found nothing
                    if not img_candidates:
                        for sel in selectors.generated_images:
                            loc = page.locator(sel)
                            cnt = await loc.count()
                            if cnt > 0:
                                candidate = loc.nth(cnt - 1)
                                if await candidate.is_visible():
                                    src_val = await candidate.get_attribute("src")
                                    if src_val and not src_val.startswith("data:image/svg"):
                                        img_candidates.append((candidate, src_val))
                                        break

                    if img_candidates:
                        gen_duration = time.perf_counter() - t_gen_start
                        logger.info(
                            "Generation finished in %.2fs. Detected %d image output(s).",
                            gen_duration, len(img_candidates)
                        )

                        image_results: list[dict[str, Any]] = []
                        for idx, (img_loc, src) in enumerate(img_candidates):
                            # Hover over image to reveal download button overlay
                            try:
                                await img_loc.hover(timeout=1000)
                            except Exception:
                                pass

                            download_obj: Optional[Download] = None
                            for dl_sel in selectors.download_buttons:
                                dl_loc = page.locator(dl_sel)
                                if await dl_loc.count() > 0 and await dl_loc.first.is_visible():
                                    try:
                                        logger.info("Found native download button (%s). Triggering expect_download()...", dl_sel)
                                        async with page.expect_download(timeout=6000) as dl_info:
                                            await dl_loc.first.click()
                                        download_obj = await dl_info.value
                                        logger.info("Playwright download event captured: %s", download_obj.suggested_filename)
                                        break
                                    except Exception as dl_err:
                                        logger.warning("Download event trigger failed or timed out: %s. Using image URL fallback.", dl_err)
                                        break

                            image_results.append({
                                "type": "image",
                                "src": src,
                                "download": download_obj,
                            })

                        return True, image_results, None, gen_duration

            await asyncio.sleep(poll_interval)

        return False, [], f"Generation timed out after {timeout_seconds} seconds.", time.perf_counter() - t_gen_start


chatgpt_controller = ChatGPTController()

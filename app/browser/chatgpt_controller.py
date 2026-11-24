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

    @classmethod
    async def dismiss_overlays(cls, page: Page) -> None:
        """Dismisses any active modals, lightboxes, backdrops, or floating banners."""
        try:
            # 1. Close any visible modal/dialog close or dismiss buttons
            close_selectors = [
                "button[aria-label*='Close']",
                "button[aria-label*='close']",
                "button[data-testid*='close']",
                "[role='dialog'] button[aria-label*='Close']",
                "[role='dialog'] button:has-text('Close')",
                "button:has-text('Close')",
                "button:has-text('Dismiss')",
                "button:has-text('Not now')",
                "button:has-text('Stay logged out')",
                "button:has-text('Cancel')",
            ]
            for sel in close_selectors:
                try:
                    loc = page.locator(sel)
                    cnt = await loc.count()
                    for i in range(cnt):
                        btn = loc.nth(i)
                        if await btn.is_visible():
                            await btn.click(timeout=800)
                            await asyncio.sleep(0.1)
                except Exception:
                    pass

            # 2. Press Escape key twice to dismiss image lightboxes / popups
            try:
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.1)
                await page.keyboard.press("Escape")
            except Exception:
                pass

            # 3. Click scroll to bottom if ChatGPT shows floating scroll-to-bottom arrow
            scroll_btn = page.locator("button[aria-label*='Scroll to bottom'], button:has-text('Scroll to bottom'), button[class*='scroll-bottom']")
            if await scroll_btn.count() > 0 and await scroll_btn.first.is_visible():
                try:
                    await scroll_btn.first.click(timeout=800)
                except Exception:
                    pass

            # 4. Remove any stuck inert or aria-hidden on main content / prompt textarea
            await page.evaluate("""() => {
                const el = document.querySelector('#prompt-textarea, [contenteditable="true"][role="textbox"], textarea');
                if (el) {
                    let parent = el.parentElement;
                    while (parent && parent !== document.body) {
                        if (parent.getAttribute('aria-hidden') === 'true') {
                            parent.removeAttribute('aria-hidden');
                        }
                        if (parent.hasAttribute('inert')) {
                            parent.removeAttribute('inert');
                        }
                        parent = parent.parentElement;
                    }
                }
            }""")
        except Exception as e:
            logger.debug("Overlay dismissal pass exception ignored: %s", e)

    @classmethod
    async def find_prompt_input(cls, page: Page, timeout_seconds: float = 15.0) -> Optional[Locator]:
        """
        Locates the active message input area with resilient polling,
        modal auto-dismissal, and DOM presence fallbacks.
        """
        poll_start = time.perf_counter()
        while (time.perf_counter() - poll_start) < timeout_seconds:
            # Dismiss any blocking overlays
            await cls.dismiss_overlays(page)

            # Check accessible & visible selectors
            for sel in selectors.prompt_input:
                loc = page.locator(sel)
                if await loc.count() > 0:
                    first = loc.first
                    if await first.is_visible():
                        return first

            # Fallback check: Element exists in DOM
            try:
                found_in_dom = await page.evaluate("""() => {
                    const el = document.querySelector('#prompt-textarea, [contenteditable="true"][role="textbox"], textarea[placeholder*="Ask"], textarea[placeholder*="Message"]');
                    if (el) {
                        el.scrollIntoView({ block: 'nearest' });
                        return true;
                    }
                    return false;
                }""")
                if found_in_dom:
                    for sel in selectors.prompt_input:
                        loc = page.locator(sel)
                        if await loc.count() > 0:
                            return loc.first
            except Exception:
                pass

            await asyncio.sleep(0.5)

        logger.warning("Prompt input could not be found within %.1fs timeout.", timeout_seconds)
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

    @classmethod
    async def enter_and_submit_prompt(cls, page: Page, prompt_text: str) -> None:
        """Enters prompt text into the composer and clicks Send with overlay auto-dismissal."""
        logger.info("Entering prompt: '%s...'", prompt_text[:60])

        input_loc = await cls.find_prompt_input(page, timeout_seconds=15.0)
        if not input_loc:
            # One final scroll down attempt
            try:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await cls.dismiss_overlays(page)
                for sel in selectors.prompt_input:
                    loc = page.locator(sel)
                    if await loc.count() > 0:
                        input_loc = loc.first
                        break
            except Exception:
                pass

        if not input_loc:
            raise ChatGPTControllerError("ChatGPT prompt textarea could not be found.")

        # Focus input
        try:
            await input_loc.click(timeout=1500)
        except Exception:
            logger.debug("Click on prompt input timed out, using direct focus.")
            await input_loc.focus()

        # Multi-strategy prompt entry for ChatGPT ProseMirror editor:
        # Prevents newline characters from triggering early message submission.
        filled = False

        # Strategy 1: Fast fill with short timeout
        try:
            await input_loc.fill(prompt_text, timeout=2000)
            filled = True
            logger.debug("Prompt filled via locator.fill")
        except Exception as fill_err:
            logger.debug("Locator fill bypassed or timed out (%s), using native paste event", fill_err)

        # Strategy 2: Dispatch native clipboard paste event into ProseMirror (instantly pastes full multiline text)
        if not filled:
            try:
                paste_ok = await page.evaluate("""(text) => {
                    const el = document.querySelector('#prompt-textarea') || document.querySelector('[contenteditable="true"]');
                    if (!el) return false;
                    el.focus();
                    const dt = new DataTransfer();
                    dt.setData('text/plain', text);
                    const pasteEvent = new ClipboardEvent('paste', {
                        clipboardData: dt,
                        bubbles: true,
                        cancelable: true
                    });
                    el.dispatchEvent(pasteEvent);
                    return true;
                }""", prompt_text)
                if paste_ok:
                    filled = True
                    logger.debug("Prompt entered via simulated ClipboardEvent")
            except Exception as paste_err:
                logger.debug("ClipboardEvent entry failed: %s", paste_err)

        # Strategy 3: Type line-by-line using Shift+Enter for newlines so Enter never submits prematurely
        if not filled:
            logger.debug("Falling back to line-by-line keyboard typing with Shift+Enter for newlines")
            await input_loc.focus()
            lines = prompt_text.split("\n")
            for i, line in enumerate(lines):
                if line:
                    await page.keyboard.insert_text(line)
                if i < len(lines) - 1:
                    await page.keyboard.press("Shift+Enter")

        await asyncio.sleep(0.4)

        # Locate send button with brief polling for enablement
        send_btn = None
        send_poll_start = time.perf_counter()
        while (time.perf_counter() - send_poll_start) < 4.0:
            for sel in selectors.send_buttons:
                loc = page.locator(sel)
                if await loc.count() > 0 and await loc.first.is_enabled():
                    send_btn = loc.first
                    break
            if send_btn:
                break
            await asyncio.sleep(0.2)

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
                    assistant_turns = page.locator("[data-message-author-role='assistant']")
                    if await assistant_turns.count() > 0:
                        last_turn_loc = assistant_turns.last

                        # Check for native file download link strictly inside this latest assistant turn
                        file_download_obj: Optional[Download] = None
                        file_dl_loc = last_turn_loc.locator("a[download], a[href*='download'], a:has-text('.md')")
                        if await file_dl_loc.count() > 0 and await file_dl_loc.first.is_visible():
                            try:
                                logger.info("Found .md file download link in latest turn. Triggering expect_download()...")
                                async with page.expect_download(timeout=4000) as dl_info:
                                    await file_dl_loc.first.click()
                                dl_val = await dl_info.value
                                if dl_val.suggested_filename.lower().endswith((".md", ".txt", ".markdown")):
                                    file_download_obj = dl_val
                            except Exception as dl_err:
                                logger.debug("File download expect failed: %s", dl_err)

                        # Extract clean markdown text directly from the latest assistant turn
                        md_content = ""
                        try:
                            md_content = await page.evaluate("""() => {
                                const turns = document.querySelectorAll("[data-message-author-role='assistant']");
                                if (!turns || turns.length === 0) return '';
                                const turn = turns[turns.length - 1];

                                // 1. Check if formatted in code block (e.g. ```markdown ... ```)
                                const code = turn.querySelector('pre code');
                                if (code && code.innerText.trim().length > 20) {
                                    return code.innerText.trim();
                                }

                                // 2. Extract from markdown container
                                const mdContainer = turn.querySelector('.markdown') || turn.querySelector('[class*="prose"]') || turn;
                                return (mdContainer.innerText || '').trim();
                            }""") or ""
                        except Exception as md_err:
                            logger.debug("Markdown extraction evaluation failed: %s", md_err)

                        if file_download_obj or (md_content and len(md_content.strip()) >= 10):
                            gen_duration = time.perf_counter() - t_gen_start
                            logger.info(
                                "Generation finished in %.2fs. Successfully captured Markdown output (%d chars).",
                                gen_duration, len(md_content)
                            )
                            results = [{
                                "type": "markdown",
                                "content": md_content.strip(),
                                "download": file_download_obj,
                            }]
                            await cls.dismiss_overlays(page)
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
                            download_obj: Optional[Download] = None
                            # Strictly check for download button inside the latest turn if present
                            if await assistant_turns.count() > 0:
                                last_turn = assistant_turns.last
                                for dl_sel in selectors.download_buttons:
                                    dl_loc = last_turn.locator(dl_sel)
                                    if await dl_loc.count() > 0 and await dl_loc.first.is_visible():
                                        try:
                                            logger.info("Found native download button (%s) in turn. Triggering expect_download()...", dl_sel)
                                            async with page.expect_download(timeout=3000) as dl_info:
                                                await dl_loc.first.click()
                                            download_obj = await dl_info.value
                                            logger.info("Playwright download event captured: %s", download_obj.suggested_filename)
                                            break
                                        except Exception as dl_err:
                                            logger.debug("Turn download trigger failed (%s), using URL download fallback.", dl_err)
                                            break

                            image_results.append({
                                "type": "image",
                                "src": src,
                                "download": download_obj,
                            })

                        # Clean any lingering overlays or lightboxes
                        await cls.dismiss_overlays(page)
                        return True, image_results, None, gen_duration

            await asyncio.sleep(poll_interval)

        return False, [], f"Generation timed out after {timeout_seconds} seconds.", time.perf_counter() - t_gen_start


chatgpt_controller = ChatGPTController()

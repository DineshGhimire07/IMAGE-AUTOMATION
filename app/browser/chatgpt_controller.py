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
            # Clear any previously attached files/pills in composer so only ONE image is attached
            try:
                remove_btns = page.locator("button[aria-label*='Remove'], button[aria-label*='Delete'], [data-testid*='attachment'] button, [data-testid*='close']")
                cnt = await remove_btns.count()
                for i in range(cnt):
                    btn = remove_btns.nth(i)
                    if await btn.is_visible():
                        await btn.click(timeout=500)
                        await asyncio.sleep(0.1)
            except Exception:
                pass

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
        """
        Enters prompt text into the composer and clicks Send.

        Strategy (in order):
        1. Find and focus the input area (with 15s polling + modal dismissal).
        2. Clear any existing content.
        3. Insert text via document.execCommand('insertText') — the most reliable
           method for ProseMirror / ContentEditable editors used by ChatGPT.
        4. Verify the box actually has content before clicking Send.
        5. Click Send button (or press Enter as fallback).
        """
        logger.info("Entering prompt: '%s...'", prompt_text[:70])

        input_loc = await cls.find_prompt_input(page, timeout_seconds=15.0)
        if not input_loc:
            # Last-ditch: scroll to bottom and try again
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

        # Focus the input
        try:
            await input_loc.click(timeout=1500)
        except Exception:
            logger.debug("Click on prompt input timed out, using direct focus.")
            await input_loc.focus()

        # Clear any existing content (previous failed attempt may have left residue)
        try:
            await input_loc.fill("")
        except Exception:
            try:
                await page.keyboard.press("Control+a")
                await page.keyboard.press("Delete")
            except Exception:
                pass

        await asyncio.sleep(0.2)

        # Insert text using execCommand — works with ProseMirror contenteditable editors.
        # This is the ONLY method that correctly handles multiline text without
        # triggering early Enter submission.
        inserted = await page.evaluate("""(text) => {
            const el = document.querySelector('#prompt-textarea') ||
                       document.querySelector('[contenteditable="true"][role="textbox"]') ||
                       document.querySelector('[contenteditable="true"]');
            if (!el) return false;
            el.focus();
            // Select all existing content and replace with our text
            document.execCommand('selectAll', false, null);
            document.execCommand('delete', false, null);
            return document.execCommand('insertText', false, text);
        }""", prompt_text)

        if not inserted:
            # Fallback: Shift+Enter line-by-line typing (slower but reliable)
            logger.debug("execCommand did not insert text, falling back to line-by-line Shift+Enter")
            await input_loc.focus()
            try:
                await input_loc.fill("")
            except Exception:
                pass
            lines = prompt_text.split("\n")
            for i, line in enumerate(lines):
                if line:
                    await page.keyboard.insert_text(line)
                if i < len(lines) - 1:
                    await page.keyboard.press("Shift+Enter")
        else:
            logger.debug("Prompt inserted via execCommand")

        await asyncio.sleep(0.5)

        # Verify that the input box actually has content before we Send.
        # If the box is empty, do NOT click Send (would submit blank / just the image).
        actual_content = ""
        try:
            actual_content = await page.evaluate("""() => {
                const el = document.querySelector('#prompt-textarea') ||
                           document.querySelector('[contenteditable="true"][role="textbox"]') ||
                           document.querySelector('[contenteditable="true"]');
                return el ? (el.innerText || el.value || '').trim() : '';
            }""") or ""
        except Exception:
            pass

        if not actual_content:
            logger.warning("Input box appears empty after prompt entry — trying clipboard paste fallback")
            try:
                await page.evaluate("""(text) => {
                    const el = document.querySelector('#prompt-textarea') ||
                               document.querySelector('[contenteditable="true"][role="textbox"]') ||
                               document.querySelector('[contenteditable="true"]');
                    if (!el) return;
                    el.focus();
                    const dt = new DataTransfer();
                    dt.setData('text/plain', text);
                    el.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true}));
                }""", prompt_text)
                await asyncio.sleep(0.5)
                actual_content = await page.evaluate("""() => {
                    const el = document.querySelector('#prompt-textarea') ||
                               document.querySelector('[contenteditable="true"][role="textbox"]') ||
                               document.querySelector('[contenteditable="true"]');
                    return el ? (el.innerText || el.value || '').trim() : '';
                }""") or ""
            except Exception:
                pass

        if not actual_content:
            raise ChatGPTControllerError(
                "Prompt text could not be entered into ChatGPT input box — box is still empty after all strategies."
            )

        logger.debug("Input box verified with %d chars.", len(actual_content))

        # Find and click the Send button (poll up to 4 seconds for it to enable)
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
            logger.info("Prompt submitted via Send button.")
        else:
            logger.debug("Send button not found — pressing Enter as fallback.")
            await input_loc.press("Enter")
            logger.info("Prompt submitted via Enter key.")

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
        known_image_srcs: Optional[set] = None,
    ) -> Tuple[bool, list[dict[str, Any]], Optional[str], float]:
        """
        Observes generation lifecycle:
        1. Waits for generation to start (stop button or response streaming).
        2. Waits for stop button to disappear.
        3. If is_markdown=True:
           Extracts generated .md file or markdown text listing; NEVER downloads an image.
        4. If is_markdown=False:
           Scans for all newly rendered generated images in the assistant's turn (handles 1 or 2 options).

        Args:
            known_image_srcs: Set of image src URLs already seen from previous prompts.
                              Any image whose src is in this set is SKIPPED so we never
                              re-download the same image for a different prompt.
        """
        logger.info(
            "Waiting for generation to start and complete (timeout: %ds, mode: %s)...",
            timeout_seconds, "MARKDOWN" if is_markdown else "IMAGE"
        )
        t_gen_start = time.perf_counter()
        generation_started = False

        # Phase 1: Wait up to 20s for generation to be marked active (stop button appears)
        # Markdown prompts may take longer to start processing after submission
        phase1_timeout = 20.0
        while (time.perf_counter() - t_gen_start) < phase1_timeout:
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
        # If generation never started (phase 1 timed out without stop button),
        # we still enter phase 2 to check if content appeared immediately.
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

            # Only check for outputs once generation_started flag was set OR after phase 1 timeout.
            # This prevents triggering extraction before ChatGPT even starts.
            can_extract = generation_started or (time.perf_counter() - t_gen_start) > 20.0

            if not is_still_generating and can_extract:
                # Generation finished: extract outputs
                # -------------------------------------------------------------
                # Branch A: Markdown Prompt Mode (Job is intended for .md file)
                # -------------------------------------------------------------
                if is_markdown:
                    file_download_obj: Optional[Download] = None
                    md_content = ""

                    # == STEP 1: Scroll every ChatGPT scroll container to the very bottom ==
                    logger.info("MD: Scrolling to bottom...")
                    try:
                        await page.evaluate("""
                            () => {
                                document.querySelectorAll(
                                    'main, [role="main"], div[class*="overflow-y"], ' +
                                    'div[class*="overflow-x"], div[class*="scroll"]'
                                ).forEach(el => {
                                    try { el.scrollTop = el.scrollHeight; } catch(_) {}
                                });
                                window.scrollTo(0, document.body.scrollHeight);
                            }
                        """)
                        await page.keyboard.press("End")
                    except Exception:
                        pass
                    await asyncio.sleep(2.0)

                    # == STEP 2: Find the .md card via WHOLE-PAGE search (no assistant-turn scope) ==
                    logger.info("MD: Searching for the .md document card (whole-page)...")
                    card_coords = await page.evaluate("""
                        () => {
                            // Try multiple assistant-turn selectors first
                            const turnSelectors = [
                                "[data-message-author-role='assistant']",
                                "[data-message-role='assistant']",
                                "article[data-testid*='conversation-turn']",
                                "div.agent-turn",
                            ];
                            let searchRoot = null;
                            for (const sel of turnSelectors) {
                                const els = document.querySelectorAll(sel);
                                if (els.length > 0) { searchRoot = els[els.length - 1]; break; }
                            }
                            // Ultimate fallback: search entire page body
                            if (!searchRoot) searchRoot = document.body;

                            const candidates = Array.from(searchRoot.querySelectorAll('*'));
                            for (const el of candidates) {
                                const text = el.innerText || el.textContent || '';
                                if (!text.includes('.md')) continue;
                                if (!text.includes('Document') && !text.includes('Open file')) continue;

                                const rect = el.getBoundingClientRect();
                                if (rect.width  < 100 || rect.width  > 800) continue;
                                if (rect.height <  20  || rect.height > 180) continue;
                                if (rect.top < -100 || rect.top > window.innerHeight + 100) continue;

                                el.scrollIntoView({ behavior: 'instant', block: 'center' });
                                const r2 = el.getBoundingClientRect();
                                return { x: r2.left + r2.width / 2,
                                         y: r2.top  + r2.height / 2 };
                            }
                            return null;
                        }
                    """)

                    if card_coords:
                        cx = card_coords["x"]
                        cy = card_coords["y"]
                        logger.info("MD: Found card at (%.0f, %.0f) — waiting 1s then clicking...", cx, cy)
                        await asyncio.sleep(1.0)

                        # Strategy A: Try the download button on the card itself (visible in DOM)
                        logger.info("MD: Trying direct card download button...")
                        CARD_DL_SELECTORS = [
                            "[data-testid='download-file-button']",
                            "[data-testid*='download']",
                            "button[aria-label='Download']",
                            "button[aria-label*='Download']",
                            "button[aria-label*='download']",
                            "button[title*='Download']",
                            "button[title*='download']",
                        ]
                        for dl_sel in CARD_DL_SELECTORS:
                            if file_download_obj:
                                break
                            try:
                                dl_loc = page.locator(dl_sel).first
                                if await dl_loc.count() > 0 and await dl_loc.is_visible():
                                    logger.info("MD: Card dl button (%s) — clicking...", dl_sel)
                                    async with page.expect_download(timeout=15000) as dl_info:
                                        await dl_loc.click(timeout=3000)
                                    file_download_obj = await dl_info.value
                                    logger.info("MD: Card-button download: %s",
                                                file_download_obj.suggested_filename)
                            except Exception as e:
                                logger.debug("MD: card dl btn %s -> %s", dl_sel, e)

                        # Strategy B: Click the card -> preview panel -> panel download button
                        if not file_download_obj:
                            logger.info("MD: Clicking card to open preview panel...")
                            await page.mouse.click(cx, cy)
                            await asyncio.sleep(2.5)

                            logger.info("MD: Preview open — searching for download button...")
                            PREVIEW_DL_SELECTORS = [
                                "button[aria-label='Download']",
                                "button[aria-label*='Download']",
                                "button[aria-label*='download']",
                                "button[title='Download']",
                                "button[title*='Download']",
                                "button[title*='download']",
                                "[data-testid='download-file-button']",
                                "[data-testid*='download']",
                                "a[download]",
                            ]
                            for dl_sel in PREVIEW_DL_SELECTORS:
                                if file_download_obj:
                                    break
                                try:
                                    dl_loc = page.locator(dl_sel).first
                                    if await dl_loc.count() > 0 and await dl_loc.is_visible():
                                        logger.info("MD: Preview dl button (%s)...", dl_sel)
                                        async with page.expect_download(timeout=15000) as dl_info:
                                            await dl_loc.click(timeout=3000)
                                        file_download_obj = await dl_info.value
                                        logger.info("MD: Preview download: %s",
                                                    file_download_obj.suggested_filename)
                                except Exception as e:
                                    logger.debug("MD: preview dl %s -> %s", dl_sel, e)

                            # Strategy C: JS-evaluate click any download button
                            if not file_download_obj:
                                logger.info("MD: Trying JS-evaluate download button click...")
                                try:
                                    async with page.expect_download(timeout=10000) as dl_info:
                                        await page.evaluate("""
                                            () => {
                                                const btns = Array.from(document.querySelectorAll('button, a'));
                                                for (const b of btns) {
                                                    const lbl = (b.getAttribute('aria-label') || '').toLowerCase();
                                                    const ttl = (b.getAttribute('title') || '').toLowerCase();
                                                    const dtid = (b.getAttribute('data-testid') || '').toLowerCase();
                                                    const txt = (b.innerText || b.textContent || '').trim();
                                                    if (lbl.includes('download') || ttl.includes('download') ||
                                                        dtid.includes('download') || txt === '\u2193') {
                                                        b.click(); return;
                                                    }
                                                }
                                            }
                                        """)
                                    file_download_obj = await dl_info.value
                                    logger.info("MD: JS-click download: %s",
                                                file_download_obj.suggested_filename)
                                except Exception as e:
                                    logger.debug("MD: JS-click download -> %s", e)

                            # Close preview panel
                            logger.info("MD: Closing preview panel (Escape)...")
                            try:
                                await page.keyboard.press("Escape")
                                await asyncio.sleep(0.5)
                            except Exception:
                                pass
                    else:
                        logger.warning("MD: Card not found in full DOM — skipping card click.")

                    # == STEP 5: Fallback — inline text link (whole-page, no turn scope) ==
                    if not file_download_obj:
                        logger.info("MD: Trying inline text link fallback (whole-page)...")
                        try:
                            for link_sel in ["a[href*='.md']", "a[download]", "a:has-text('.md')"]:
                                lnk = page.locator(link_sel).first
                                if await lnk.count() > 0 and await lnk.is_visible():
                                    async with page.expect_download(timeout=15000) as dl_info:
                                        await lnk.click(timeout=3000)
                                    dl_val = await dl_info.value
                                    if dl_val.suggested_filename.lower().endswith(
                                        (".md", ".txt", ".markdown")
                                    ):
                                        file_download_obj = dl_val
                                        logger.info("MD: Link download: %s",
                                                    file_download_obj.suggested_filename)
                                    break
                        except Exception as e:
                            logger.debug("MD: link fallback -> %s", e)

                    # == STEP 6: Guaranteed fallback — scrape text from DOM ==
                    try:
                        md_content = await page.evaluate("""
                            () => {
                                const selectors = [
                                    "[data-message-author-role='assistant']",
                                    "[data-message-role='assistant']",
                                    "article[data-testid*='conversation-turn']",
                                    "div.agent-turn",
                                ];
                                let turn = null;
                                for (const sel of selectors) {
                                    const els = document.querySelectorAll(sel);
                                    if (els.length > 0) { turn = els[els.length - 1]; break; }
                                }
                                if (!turn) {
                                    const main = document.querySelector('main') || document.body;
                                    return (main.innerText || '').slice(-8000).trim();
                                }
                                for (const code of turn.querySelectorAll('pre code')) {
                                    const t = code.innerText.trim();
                                    if (t.length > 50) return t;
                                }
                                const prose =
                                    turn.querySelector('.markdown, [class*="prose"]') || turn;
                                return (prose.innerText || turn.innerText || '').trim();
                            }
                        """) or ""
                    except Exception as e:
                        logger.debug("MD: DOM scrape -> %s", e)

                    # == ALWAYS RETURN — never loop after generation is confirmed complete ==
                    gen_duration = time.perf_counter() - t_gen_start
                    # Validate md_content: reject prompt text / ChatGPT questions.
                    # A real generated listing will contain product_id/XINVORA/YAML markers.
                    md_valid = False
                    if md_content:
                        _mds = md_content.strip()
                        md_valid = len(_mds) >= 50 and any(k in _mds for k in [
                            "product_id:", "XINVORA", "seller_sku:",
                            "special_price:", "highlights:", "---",
                        ])
                    if file_download_obj or md_valid:
                        logger.info(
                            "MD done in %.2fs — file_downloaded=%s  text_chars=%d",
                            gen_duration, bool(file_download_obj), len(md_content)
                        )
                        results = [{
                            "type": "markdown",
                            "content": md_content.strip(),
                            "download": file_download_obj,
                        }]
                        await cls.dismiss_overlays(page)
                        return True, results, None, gen_duration

                    # Generation text not ready yet — keep polling
                    logger.debug("MD: generation output not yet ready, continuing poll...")

                # -------------------------------------------------------------
                # Branch B: Image Prompt Mode (Default: Job expects photo)
                # -------------------------------------------------------------
                else:
                    # Scroll to bottom so the latest generated image is in view
                    try:
                        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        await asyncio.sleep(0.5)
                    except Exception:
                        pass

                    img_candidates: list[tuple[Locator, str]] = []
                    _known = known_image_srcs or set()

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
                                    if src_val in _known:
                                        logger.debug(
                                            "Skipping already-seen image src (Prompt %d duplicate): %.80s",
                                            idx, src_val
                                        )
                                        continue
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
                                    if src_val and not src_val.startswith("data:image/svg") and src_val not in _known:
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

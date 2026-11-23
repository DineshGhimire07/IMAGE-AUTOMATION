"""Dedicated Browser Manager using Playwright persistent context."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional, Dict, Any
from playwright.async_api import async_playwright, BrowserContext, Page, Playwright
from app.config import config
from app.utils.logger import logger
from app.browser.page_detector import selectors


class BrowserManager:
    """
    Manages a dedicated persistent browser profile context.
    Allows manual ChatGPT login and preserves cookies across restarts.
    """

    def __init__(self, profile_dir: Optional[Path] = None):
        self.profile_dir = profile_dir or config.browser_profile_dir
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.playwright: Optional[Playwright] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._is_launching = False

    @property
    def is_running(self) -> bool:
        return self.context is not None and self.page is not None and not self.page.is_closed()

    async def launch(
        self,
        headless: bool = False,
        executable_path: Optional[str] = None,
        slow_mo: int = 50,
    ) -> Page:
        """
        Launches the persistent browser context with dedicated profile.
        """
        if self.is_running:
            logger.info("Browser is already running.")
            return self.page  # type: ignore

        self._is_launching = True
        logger.info("Launching dedicated browser (headless=%s)...", headless)

        try:
            self.playwright = await async_playwright().start()

            launch_args = [
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
                "--no-default-browser-check",
            ]

            custom_exec = executable_path or config.browser_executable_path
            kwargs: Dict[str, Any] = {
                "user_data_dir": str(self.profile_dir),
                "headless": headless,
                "slow_mo": slow_mo,
                "args": launch_args,
                "accept_downloads": True,
                "no_viewport": True,
            }

            if custom_exec and Path(custom_exec).exists():
                logger.info("Using custom browser executable: %s", custom_exec)
                kwargs["executable_path"] = custom_exec

            self.context = await self.playwright.chromium.launch_persistent_context(**kwargs)

            # Retrieve existing page or open a new one
            if self.context.pages:
                self.page = self.context.pages[0]
            else:
                self.page = await self.context.new_page()

            # Set realistic user agent / attributes
            await self.page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)

            logger.info("Dedicated browser launched successfully.")
            return self.page

        except Exception as e:
            logger.exception("Failed to launch browser: %s", e)
            await self.close()
            raise
        finally:
            self._is_launching = False

    async def close(self) -> None:
        """Closes browser context and shuts down Playwright."""
        logger.info("Closing browser context...")
        try:
            if self.page and not self.page.is_closed():
                await self.page.close()
        except Exception:
            pass
        self.page = None

        try:
            if self.context:
                await self.context.close()
        except Exception:
            pass
        self.context = None

        try:
            if self.playwright:
                await self.playwright.stop()
        except Exception:
            pass
        self.playwright = None
        logger.info("Browser context closed.")

    async def navigate_to_chatgpt(self, timeout_ms: int = 60000) -> bool:
        """Navigates to ChatGPT home URL."""
        if not self.is_running or not self.page:
            raise RuntimeError("Browser is not running.")

        try:
            current_url = self.page.url
            if "chatgpt.com" in current_url:
                logger.debug("Already on ChatGPT domain (%s)", current_url)
                return True

            logger.info("Navigating to %s...", config.chatgpt_url)
            await self.page.goto(config.chatgpt_url, timeout=timeout_ms, wait_until="domcontentloaded")
            return True
        except Exception as e:
            logger.error("Navigation to ChatGPT failed: %s", e)
            return False

    async def check_connection(self) -> Dict[str, Any]:
        """
        Inspects browser state, current page URL, accessibility, and login status.
        """
        if not self.is_running or not self.page:
            return {
                "browser_running": False,
                "chatgpt_accessible": False,
                "is_logged_in": False,
                "url": "N/A",
                "message": "Browser is not running.",
            }

        url = self.page.url
        is_chatgpt = "chatgpt.com" in url or "openai.com" in url

        if not is_chatgpt:
            return {
                "browser_running": True,
                "chatgpt_accessible": False,
                "is_logged_in": False,
                "url": url,
                "message": f"Browser active, but not on ChatGPT ({url})",
            }

        # Check login status and ready state
        is_logged_in = False
        page_ready = False

        try:
            # Check if prompt textarea exists (strongest indicator of readiness and login)
            for sel in selectors.prompt_input:
                loc = self.page.locator(sel)
                if await loc.count() > 0 and await loc.first.is_visible():
                    is_logged_in = True
                    page_ready = True
                    break

            if not is_logged_in:
                # Check for login buttons
                for sel in selectors.login_buttons:
                    loc = self.page.locator(sel)
                    if await loc.count() > 0 and await loc.first.is_visible():
                        return {
                            "browser_running": True,
                            "chatgpt_accessible": True,
                            "is_logged_in": False,
                            "url": url,
                            "message": "ChatGPT loaded, but login required.",
                        }

                # Check user profile indicator
                for sel in selectors.user_indicators:
                    loc = self.page.locator(sel)
                    if await loc.count() > 0 and await loc.first.is_visible():
                        is_logged_in = True
                        break

            return {
                "browser_running": True,
                "chatgpt_accessible": True,
                "is_logged_in": is_logged_in,
                "page_ready": page_ready,
                "url": url,
                "message": "Connected and ready." if (is_logged_in and page_ready) else "Waiting for login / page ready.",
            }

        except Exception as e:
            return {
                "browser_running": True,
                "chatgpt_accessible": True,
                "is_logged_in": False,
                "url": url,
                "message": f"Error inspecting page: {e}",
            }


browser_manager = BrowserManager()

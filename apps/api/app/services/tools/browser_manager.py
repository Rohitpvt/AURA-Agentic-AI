"""Playwright Headless Browser Lifecycle and Isolation Manager."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Optional
from app.core.logging import logger


if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Playwright

MAX_CONCURRENT_EXTRACTIONS = 2


class PlaywrightBrowserManager:
    """Manages the local Playwright Chromium headless lifecycle and isolated BrowserContexts."""

    def __init__(self):
        self._playwright: Optional["Playwright"] = None
        self._browser: Optional["Browser"] = None
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(MAX_CONCURRENT_EXTRACTIONS)
        self._lock: asyncio.Lock = asyncio.Lock()
        self._is_closing: bool = False

    @property
    def semaphore(self) -> asyncio.Semaphore:
        """Concurrency gate limiting concurrent extractions to MAX_CONCURRENT_EXTRACTIONS."""
        return self._semaphore

    async def get_browser(self) -> "Browser":
        """Get or lazily initialize the shared headless Chromium browser instance."""
        if self._browser and self._browser.is_connected():
            return self._browser

        async with self._lock:
            if self._browser and self._browser.is_connected():
                return self._browser

            if self._playwright is None:
                from playwright.async_api import async_playwright
                self._playwright = await async_playwright().start()

                try:
                    driver_proc = getattr(getattr(getattr(self._playwright, "_impl_obj", None), "_connection", None), "_transport", None)
                    proc = getattr(driver_proc, "_proc", None)
                    if proc and getattr(proc, "pid", None):
                        from app.core.process import managed_process_registry
                        await managed_process_registry.register_process(
                            process=proc,
                            category="playwright_driver",
                            command=["playwright", "driver"],
                        )
                except Exception as e:
                    logger.debug(f"BrowserManager: Playwright driver registration notice: {e}")

            logger.info("BrowserManager: Launching headless Chromium extraction browser...")
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-extensions",
                    "--disable-default-apps",
                    "--disable-component-extensions-with-background-pages",
                ],
            )
            logger.info(f"BrowserManager: Chromium {self._browser.version} ready.")
            return self._browser

    async def create_isolated_context(self) -> BrowserContext:
        """Create a fresh, non-persistent, strictly isolated BrowserContext.
        
        Security constraints enforced:
        - accept_downloads = False (prohibit arbitrary file downloads)
        - service_workers = 'block' (prevent route interception bypass)
        - permissions = [] (no geolocation, camera, mic, clipboard, notifications)
        - ephemeral storage (cookies, cache wiped on context close)
        """
        browser = await self.get_browser()
        context = await browser.new_context(
            accept_downloads=False,
            java_script_enabled=True,
            ignore_https_errors=False,
            permissions=[],
            service_workers="block",
            user_agent="AURA-WebExtract/1.0 (+https://aura.local; headless extraction)",
            viewport={"width": 1280, "height": 800},
        )
        return context

    async def close(self) -> None:
        """Cleanly close all browser resources and stop Playwright process."""
        async with self._lock:
            self._is_closing = True
            if self._browser:
                try:
                    logger.info("BrowserManager: Closing Chromium browser...")
                    await self._browser.close()
                except Exception as e:
                    logger.warning(f"BrowserManager: Error closing browser: {e}")
                finally:
                    self._browser = None

            if self._playwright:
                try:
                    logger.info("BrowserManager: Stopping Playwright engine...")
                    await self._playwright.stop()
                except Exception as e:
                    logger.warning(f"BrowserManager: Error stopping Playwright: {e}")
                finally:
                    self._playwright = None
            self._is_closing = False


browser_manager = PlaywrightBrowserManager()

"""Playwright Headless Browser Lifecycle and Isolation Manager.

Maintains backward-compatibility by delegating to the Phase 10 PlaywrightBrowserEngine.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from app.services.browser.engine import PlaywrightBrowserEngine, browser_engine

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext

# Backward-compatible alias
MAX_CONCURRENT_EXTRACTIONS = 2
PlaywrightBrowserManager = PlaywrightBrowserEngine
browser_manager = browser_engine

__all__ = [
    "MAX_CONCURRENT_EXTRACTIONS",
    "PlaywrightBrowserManager",
    "browser_manager",
]

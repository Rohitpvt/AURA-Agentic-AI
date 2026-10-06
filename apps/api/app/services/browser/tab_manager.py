"""Workspace-scoped BrowserContext and Multi-Tab Management (AURA-1001)."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page

from app.core.errors import EntityNotFoundError, ValidationError
from app.core.logging import logger
from app.services.browser.models import TabInfo

MAX_TABS_PER_CONTEXT = 4
DEFAULT_VIEWPORT = {"width": 1280, "height": 800}
DEFAULT_TIMEOUT_MS = 25000


class WorkspaceBrowserContext:
    """Manages an isolated BrowserContext and tracks up to 4 tabs for a specific workspace."""

    def __init__(self, workspace_id: uuid.UUID, context: "BrowserContext"):
        self.workspace_id: uuid.UUID = workspace_id
        self._context: "BrowserContext" = context
        self._tabs: Dict[str, Tuple[TabInfo, "Page"]] = {}
        self._active_tab_id: Optional[str] = None
        self._lock: asyncio.Lock = asyncio.Lock()
        self._is_closed: bool = False

    @property
    def is_closed(self) -> bool:
        return self._is_closed

    @property
    def context(self) -> "BrowserContext":
        return self._context

    @property
    def active_tab_id(self) -> Optional[str]:
        return self._active_tab_id

    @property
    def tab_count(self) -> int:
        return len(self._tabs)

    async def create_tab(self, url: Optional[str] = None) -> TabInfo:
        """Create a new page/tab within this workspace context up to MAX_TABS_PER_CONTEXT."""
        async with self._lock:
            if self._is_closed:
                raise ValidationError("Cannot create tab on closed workspace browser context")

            if len(self._tabs) >= MAX_TABS_PER_CONTEXT:
                raise ValidationError(
                    f"Maximum concurrent tab limit ({MAX_TABS_PER_CONTEXT}) reached for workspace {self.workspace_id}"
                )

            page = await self._context.new_page()
            page.set_default_navigation_timeout(DEFAULT_TIMEOUT_MS)
            page.set_default_timeout(DEFAULT_TIMEOUT_MS)

            tab_id = str(uuid.uuid4())
            now = time.time()
            tab_info = TabInfo(
                tab_id=tab_id,
                url="about:blank",
                title="New Tab",
                is_active=True,
                created_at=now,
                updated_at=now,
            )

            # Block popups and extra tabs
            page.on("popup", lambda p: asyncio.create_task(p.close()))

            # Auto-cleanup on unexpected page close
            def _on_page_close() -> None:
                if tab_id in self._tabs:
                    logger.debug(f"WorkspaceBrowserContext: Tab {tab_id} closed externally.")
                    self._tabs.pop(tab_id, None)
                    if self._active_tab_id == tab_id:
                        self._active_tab_id = next(iter(self._tabs.keys())) if self._tabs else None

            page.on("close", _on_page_close)

            # Mark all existing tabs as inactive
            for existing_id, (info, _) in self._tabs.items():
                info.is_active = False

            self._tabs[tab_id] = (tab_info, page)
            self._active_tab_id = tab_id

            logger.info(f"WorkspaceBrowserContext: Created Tab {tab_id} for Workspace {self.workspace_id} (Total: {len(self._tabs)})")
            return tab_info

    def get_page(self, tab_id: Optional[str] = None) -> "Page":
        """Get Playwright Page instance for specified tab_id or the active tab."""
        if self._is_closed:
            raise ValidationError("Workspace browser context is closed")

        target_id = tab_id or self._active_tab_id
        if not target_id or target_id not in self._tabs:
            if not self._tabs:
                raise EntityNotFoundError(resource="BrowserTab", identifier="none_active")
            target_id = next(iter(self._tabs.keys()))

        tab_info, page = self._tabs[target_id]
        if page.is_closed():
            self._tabs.pop(target_id, None)
            raise ValidationError(f"Browser tab {target_id} is already closed")

        return page

    def get_tab_info(self, tab_id: Optional[str] = None) -> TabInfo:
        """Get metadata summary for specified tab_id or the active tab."""
        target_id = tab_id or self._active_tab_id
        if not target_id or target_id not in self._tabs:
            raise EntityNotFoundError(resource="BrowserTab", identifier=str(target_id))
        return self._tabs[target_id][0]

    def list_tabs(self) -> List[TabInfo]:
        """List all open tabs in this workspace context."""
        return [info for info, _ in self._tabs.values()]

    def switch_tab(self, tab_id: str) -> TabInfo:
        """Switch active tab to the specified tab_id."""
        if tab_id not in self._tabs:
            raise EntityNotFoundError(resource="BrowserTab", identifier=tab_id)

        for tid, (info, _) in self._tabs.items():
            info.is_active = (tid == tab_id)

        self._active_tab_id = tab_id
        return self._tabs[tab_id][0]

    def update_tab_metadata(self, tab_id: str, url: str, title: str) -> None:
        """Update URL and title metadata after navigation."""
        if tab_id in self._tabs:
            info, _ = self._tabs[tab_id]
            info.url = url
            info.title = title
            info.updated_at = time.time()

    async def close_tab(self, tab_id: str) -> None:
        """Close specified tab and update active tab tracking."""
        async with self._lock:
            if tab_id not in self._tabs:
                return

            tab_info, page = self._tabs.pop(tab_id)
            try:
                if not page.is_closed():
                    await page.close()
            except Exception as e:
                logger.warning(f"WorkspaceBrowserContext: Error closing page for Tab {tab_id}: {e}")

            if self._active_tab_id == tab_id:
                self._active_tab_id = next(iter(self._tabs.keys())) if self._tabs else None
                if self._active_tab_id and self._active_tab_id in self._tabs:
                    self._tabs[self._active_tab_id][0].is_active = True

            logger.info(f"WorkspaceBrowserContext: Closed Tab {tab_id} for Workspace {self.workspace_id} (Remaining: {len(self._tabs)})")

    async def close(self) -> None:
        """Close all pages and the underlying BrowserContext."""
        async with self._lock:
            if self._is_closed:
                return

            self._is_closed = True
            for tab_id, (info, page) in list(self._tabs.items()):
                try:
                    if not page.is_closed():
                        await page.close()
                except Exception as e:
                    logger.debug(f"WorkspaceBrowserContext: Error closing tab {tab_id}: {e}")

            self._tabs.clear()
            self._active_tab_id = None

            try:
                await self._context.close()
            except Exception as e:
                logger.warning(f"WorkspaceBrowserContext: Error closing context: {e}")

            logger.info(f"WorkspaceBrowserContext: Closed isolated context for Workspace {self.workspace_id}")

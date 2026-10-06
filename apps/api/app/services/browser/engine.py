"""Playwright/Chromium Advanced Browser Engine with Concurrency & Workspace Isolation (AURA-1001)."""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Playwright, Request, Response, Route

import psutil

from app.core.errors import AuthorizationError, EntityNotFoundError, ValidationError
from app.core.logging import logger
from app.core.network import ssrf_guard
from app.core.sanitization import prompt_sanitizer
from app.services.browser.axtree_extractor import AXTreeExtractor
from app.services.browser.models import (
    BrowserResourceMetrics,
    BrowserState,
    PageObservation,
    TabInfo,
)
from app.services.browser.tab_manager import WorkspaceBrowserContext

MAX_CONCURRENT_CONTEXTS = 2
MAX_REDIRECTS = 10
DEFAULT_NAVIGATION_TIMEOUT_MS = 25000
MAX_NAVIGATION_TIMEOUT_MS = 30000
ALLOWED_RESOURCE_TYPES = {"document", "script", "stylesheet", "xhr", "fetch", "ping", "image", "font"}
DISALLOWED_SCHEMES = {"javascript", "file", "data", "vbscript", "chrome", "edge", "about", "blob"}


class PlaywrightBrowserEngine:
    """Advanced, local-first Playwright Chromium engine with strict workspace isolation and governance."""

    def __init__(self):
        self._state: BrowserState = BrowserState.CREATED
        self._playwright: Optional["Playwright"] = None
        self._browser: Optional["Browser"] = None
        self._contexts: Dict[uuid.UUID, WorkspaceBrowserContext] = {}
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(MAX_CONCURRENT_CONTEXTS)
        self._lock: asyncio.Lock = asyncio.Lock()
        self._is_closing: bool = False

    @property
    def state(self) -> BrowserState:
        return self._state

    @property
    def semaphore(self) -> asyncio.Semaphore:
        return self._semaphore

    async def get_browser(self) -> "Browser":
        """Get or lazily initialize the shared headless Chromium browser instance."""
        if self._browser and self._browser.is_connected():
            self._state = BrowserState.READY
            return self._browser

        async with self._lock:
            if self._browser and self._browser.is_connected():
                self._state = BrowserState.READY
                return self._browser

            self._state = BrowserState.STARTING
            if self._playwright is None:
                from playwright.async_api import async_playwright
                try:
                    self._playwright = await async_playwright().start()
                except Exception as e:
                    self._state = BrowserState.DEGRADED
                    logger.error(f"BrowserEngine: Failed starting Playwright: {e}")
                    raise

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
                    logger.debug(f"BrowserEngine: Driver registration notice: {e}")

            logger.info("BrowserEngine: Launching local headless Chromium instance...")
            try:
                self._browser = await self._playwright.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-extensions",
                        "--disable-default-apps",
                        "--disable-component-extensions-with-background-pages",
                        "--no-default-browser-check",
                    ],
                )
                self._state = BrowserState.READY
                logger.info(f"BrowserEngine: Chromium {self._browser.version} ready.")
                return self._browser
            except Exception as e:
                self._state = BrowserState.DEGRADED
                logger.error(f"BrowserEngine: Failed launching Chromium: {e}")
                raise

    async def create_isolated_context(self) -> "BrowserContext":
        """Create a fresh, non-persistent, strictly isolated ephemeral BrowserContext (for backward-compat)."""
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

    async def get_or_create_workspace_context(self, workspace_id: uuid.UUID) -> WorkspaceBrowserContext:
        """Get or initialize a WorkspaceBrowserContext respecting max concurrent contexts."""
        from app.services.kill_switch import kill_switch
        if kill_switch.is_active(workspace_id):
            raise AuthorizationError(f"Emergency Kill Switch is active for workspace {workspace_id}. Browser actions prohibited.")

        browser = await self.get_browser()

        async with self._lock:
            if workspace_id in self._contexts:
                ws_ctx = self._contexts[workspace_id]
                if not ws_ctx.is_closed:
                    return ws_ctx
                self._contexts.pop(workspace_id, None)

            # Check concurrency ceiling
            if len(self._contexts) >= MAX_CONCURRENT_CONTEXTS:
                raise ValidationError(
                    f"Maximum concurrent browser contexts ({MAX_CONCURRENT_CONTEXTS}) reached. Close an active workspace context."
                )

            raw_context = await browser.new_context(
                accept_downloads=True,
                java_script_enabled=True,
                ignore_https_errors=False,
                permissions=[],
                service_workers="block",
                user_agent="AURA-BrowserEngine/1.0 (+https://aura.local; local-first autonomous assistant)",
                viewport={"width": 1280, "height": 800},
            )

            # Subresource SSRF Routing Filter
            async def _route_handler(route: "Route") -> None:
                req = route.request
                res_type = req.resource_type
                if res_type not in ALLOWED_RESOURCE_TYPES:
                    await route.abort("blockedbyclient")
                    return

                try:
                    ssrf_guard.validate_url(req.url)
                    await route.continue_()
                except Exception:
                    await route.abort("accessdenied")

            await raw_context.route("**/*", _route_handler)

            ws_ctx = WorkspaceBrowserContext(workspace_id=workspace_id, context=raw_context)
            self._contexts[workspace_id] = ws_ctx
            return ws_ctx

    async def navigate(
        self,
        workspace_id: uuid.UUID,
        url: str,
        tab_id: Optional[str] = None,
        wait_until: str = "domcontentloaded",
        timeout_ms: int = DEFAULT_NAVIGATION_TIMEOUT_MS,
    ) -> Dict[str, Any]:
        """Navigate to a target URL in the workspace context with multi-layer SSRF and kill-switch governance."""
        start_time = time.perf_counter()
        from app.services.kill_switch import kill_switch
        if kill_switch.is_active(workspace_id):
            raise AuthorizationError(f"Emergency Kill Switch is active for workspace {workspace_id}. Navigation aborted.")

        # 1. Scheme validation
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        if scheme in DISALLOWED_SCHEMES or scheme not in {"http", "https"}:
            raise ValidationError(f"Disallowed URL scheme '{scheme}'. Only http and https are permitted.")

        # 2. Pre-navigation SSRF Validation
        ssrf_guard.validate_url(url)

        # 3. Clamp timeout
        clamped_timeout = min(max(1000, timeout_ms), MAX_NAVIGATION_TIMEOUT_MS)

        # 4. Get workspace context
        ws_ctx = await self.get_or_create_workspace_context(workspace_id)

        # 5. Acquire page (create tab if none open)
        if ws_ctx.tab_count == 0:
            tab_info = await ws_ctx.create_tab()
            target_tab_id = tab_info.tab_id
        else:
            target_tab_id = tab_id or ws_ctx.active_tab_id
            if not target_tab_id:
                tab_info = await ws_ctx.create_tab()
                target_tab_id = tab_info.tab_id

        page = ws_ctx.get_page(target_tab_id)
        redirect_urls: List[str] = []

        # 6. Redirect validation listener
        def _handle_response(resp: "Response") -> None:
            if 300 <= resp.status < 400:
                location = resp.headers.get("location")
                if location:
                    if not location.startswith("http://") and not location.startswith("https://"):
                        parsed_orig = urlparse(resp.url)
                        base = f"{parsed_orig.scheme}://{parsed_orig.netloc}"
                        location = f"{base}/{location.lstrip('/')}"
                    redirect_urls.append(location)
                    try:
                        ssrf_guard.validate_url(location)
                    except Exception as e:
                        logger.error(f"BrowserEngine: Intercepted prohibited redirect to '{location}': {e}")
                        raise AuthorizationError(f"Prohibited redirect destination: {location}")

        page.on("response", _handle_response)

        try:
            response = await page.goto(
                url,
                wait_until=wait_until, # type: ignore
                timeout=clamped_timeout,
            )
            # Brief hydration pause
            await asyncio.sleep(0.3)

            if len(redirect_urls) > MAX_REDIRECTS:
                raise ValidationError(f"Redirect limit exceeded ({len(redirect_urls)} > {MAX_REDIRECTS})")

            title = await page.title()
            final_url = page.url
            status_code = response.status if response else 200

            ws_ctx.update_tab_metadata(target_tab_id, url=final_url, title=title)
            duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

            return {
                "status": "success",
                "tab_id": target_tab_id,
                "url": url,
                "final_url": final_url,
                "title": title,
                "status_code": status_code,
                "redirect_count": len(redirect_urls),
                "duration_ms": duration_ms,
                "is_untrusted_content": True,
            }
        except Exception as e:
            if "Prohibited redirect" in str(e) or "SSRF" in str(e):
                raise AuthorizationError(f"Navigation aborted due to SSRF redirect policy: {e}")
            raise

    async def observe_page(
        self,
        workspace_id: uuid.UUID,
        tab_id: Optional[str] = None,
        max_elements: int = 100,
        max_chars: int = 8000,
    ) -> PageObservation:
        """Observe active page state, extract AXTree snapshot, and format untrusted content envelope."""
        from app.services.kill_switch import kill_switch
        if kill_switch.is_active(workspace_id):
            raise AuthorizationError(f"Emergency Kill Switch is active for workspace {workspace_id}.")

        ws_ctx = await self.get_or_create_workspace_context(workspace_id)
        target_tab_id = tab_id or ws_ctx.active_tab_id
        page = ws_ctx.get_page(target_tab_id)

        # 1. AXTree extraction
        nodes, formatted_xml, security_flags = await AXTreeExtractor.extract(
            page=page,
            max_elements=max_elements,
            max_chars=max_chars,
        )

        # 2. Text extraction
        try:
            raw_text = await page.inner_text("body")
            clean_text = prompt_sanitizer.clean_unicode_and_controls(raw_text)
            clean_text = prompt_sanitizer.escape_delimiters(clean_text)[:max_chars]
        except Exception:
            clean_text = ""

        # 3. Metadata
        url = page.url or "about:blank"
        try:
            title = await page.title()
        except Exception:
            title = ""

        now_iso = datetime.now(timezone.utc).isoformat()
        ws_ctx.update_tab_metadata(target_tab_id or "", url=url, title=title)

        return PageObservation(
            url=url,
            final_url=url,
            title=title,
            status_code=200,
            tab_id=target_tab_id or "",
            tabs_count=ws_ctx.tab_count,
            viewport={"width": 1280, "height": 800},
            axtree_nodes=nodes,
            axtree_formatted=formatted_xml,
            text_content=clean_text,
            is_untrusted_content=True,
            security_flags=security_flags,
            captured_at=now_iso,
        )

    async def capture_screenshot(
        self,
        workspace_id: uuid.UUID,
        tab_id: Optional[str] = None,
        full_page: bool = False,
    ) -> bytes:
        """Capture bounded viewport or full-page screenshot as raw PNG bytes without disk persistence."""
        from app.services.kill_switch import kill_switch
        if kill_switch.is_active(workspace_id):
            raise AuthorizationError(f"Emergency Kill Switch is active for workspace {workspace_id}.")

        ws_ctx = await self.get_or_create_workspace_context(workspace_id)
        page = ws_ctx.get_page(tab_id)

        try:
            screenshot_bytes = await page.screenshot(
                full_page=full_page,
                type="png",
                timeout=10000,
            )
            return screenshot_bytes
        except Exception as e:
            logger.error(f"BrowserEngine: Screenshot capture failed: {e}")
            raise

    async def create_tab(self, workspace_id: uuid.UUID, url: Optional[str] = None) -> TabInfo:
        """Create a new tab in the workspace context, optionally navigating to url."""
        ws_ctx = await self.get_or_create_workspace_context(workspace_id)
        tab_info = await ws_ctx.create_tab(url=url)
        if url:
            await self.navigate(workspace_id, url=url, tab_id=tab_info.tab_id)
            tab_info = ws_ctx.get_tab_info(tab_info.tab_id)
        return tab_info

    def list_tabs(self, workspace_id: uuid.UUID) -> List[TabInfo]:
        """List open tabs in workspace context."""
        if workspace_id not in self._contexts:
            return []
        return self._contexts[workspace_id].list_tabs()

    def switch_tab(self, workspace_id: uuid.UUID, tab_id: str) -> TabInfo:
        """Switch active tab in workspace context."""
        if workspace_id not in self._contexts:
            raise EntityNotFoundError(resource="WorkspaceBrowserContext", identifier=str(workspace_id))
        return self._contexts[workspace_id].switch_tab(tab_id)

    async def close_tab(self, workspace_id: uuid.UUID, tab_id: str) -> None:
        """Close a specific tab in workspace context."""
        if workspace_id in self._contexts:
            await self._contexts[workspace_id].close_tab(tab_id)

    async def close_workspace_context(self, workspace_id: uuid.UUID) -> None:
        """Close context for specific workspace."""
        async with self._lock:
            if workspace_id in self._contexts:
                ctx = self._contexts.pop(workspace_id)
                await ctx.close()

    async def close(self) -> None:
        """Cleanly close all workspace contexts, browser instance, and stop Playwright process."""
        async with self._lock:
            self._is_closing = True
            self._state = BrowserState.STOPPING

            for ws_id, ctx in list(self._contexts.items()):
                try:
                    await ctx.close()
                except Exception as e:
                    logger.warning(f"BrowserEngine: Error closing workspace context {ws_id}: {e}")
            self._contexts.clear()

            if self._browser:
                try:
                    logger.info("BrowserEngine: Closing Chromium browser...")
                    await self._browser.close()
                except Exception as e:
                    logger.warning(f"BrowserEngine: Error closing browser: {e}")
                finally:
                    self._browser = None

            if self._playwright:
                try:
                    logger.info("BrowserEngine: Stopping Playwright engine...")
                    await self._playwright.stop()
                except Exception as e:
                    logger.warning(f"BrowserEngine: Error stopping Playwright: {e}")
                finally:
                    self._playwright = None

            self._is_closing = False
            self._state = BrowserState.STOPPED
            logger.info("BrowserEngine: Stopped cleanly.")

    def get_resource_metrics(self) -> BrowserResourceMetrics:
        """Gather memory and concurrency telemetry."""
        total_tabs = sum(ctx.tab_count for ctx in self._contexts.values())
        active_contexts = len(self._contexts)

        pid: Optional[int] = None
        rss_mb: float = 0.0

        if self._browser:
            try:
                # Get browser PID
                driver_proc = getattr(getattr(getattr(self._playwright, "_impl_obj", None), "_connection", None), "_transport", None)
                proc = getattr(driver_proc, "_proc", None)
                if proc and getattr(proc, "pid", None):
                    pid = proc.pid
                    p = psutil.Process(pid)
                    rss_mb = round(p.memory_info().rss / (1024 * 1024), 2)
                    for child in p.children(recursive=True):
                        try:
                            rss_mb += round(child.memory_info().rss / (1024 * 1024), 2)
                        except Exception:
                            pass
            except Exception as e:
                logger.debug(f"BrowserEngine: Resource metrics inspect notice: {e}")

        is_over = rss_mb > 1024.0

        return BrowserResourceMetrics(
            state=self._state,
            active_contexts=active_contexts,
            max_contexts_limit=MAX_CONCURRENT_CONTEXTS,
            total_tabs=total_tabs,
            max_tabs_per_context_limit=4,
            browser_pid=pid,
            memory_rss_mb=rss_mb,
            memory_target_limit_mb=1024.0,
            is_over_target_budget=is_over,
        )


browser_engine = PlaywrightBrowserEngine()

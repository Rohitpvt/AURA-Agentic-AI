"""AURA Advanced Browser Engine Package (AURA-1001)."""

from app.services.browser.models import (
    BrowserResourceMetrics,
    BrowserState,
    PageObservation,
    TabInfo,
    AXTreeNode,
)
from app.services.browser.axtree_extractor import AXTreeExtractor
from app.services.browser.tab_manager import WorkspaceBrowserContext, MAX_TABS_PER_CONTEXT
from app.services.browser.engine import PlaywrightBrowserEngine, browser_engine

__all__ = [
    "BrowserState",
    "TabInfo",
    "AXTreeNode",
    "PageObservation",
    "BrowserResourceMetrics",
    "AXTreeExtractor",
    "WorkspaceBrowserContext",
    "MAX_TABS_PER_CONTEXT",
    "PlaywrightBrowserEngine",
    "browser_engine",
]

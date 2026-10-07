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

from app.services.browser.governance import (
    ALLOWED_BROWSER_KEYS,
    FORBIDDEN_KEY_PATTERNS,
    MAX_BROWSER_ACTIONS_PER_TASK,
    DEFAULT_OBSERVATION_TTL_SECONDS,
    BrowserRiskLevel,
    ObservationRecord,
    ObservationFreshnessStore,
    BrowserActionBudgetManager,
    BrowserRiskClassifier,
    freshness_store,
    action_budget_manager,
    browser_risk_classifier,
)

from app.services.browser.file_transfer import (
    BrowserFileTransferService,
    browser_file_transfer_service,
    sanitize_url_provenance,
    is_sensitive_file,
    is_sensitive_content,
)

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
    "ALLOWED_BROWSER_KEYS",
    "FORBIDDEN_KEY_PATTERNS",
    "MAX_BROWSER_ACTIONS_PER_TASK",
    "DEFAULT_OBSERVATION_TTL_SECONDS",
    "BrowserRiskLevel",
    "ObservationRecord",
    "ObservationFreshnessStore",
    "BrowserActionBudgetManager",
    "BrowserRiskClassifier",
    "freshness_store",
    "action_budget_manager",
    "browser_risk_classifier",
    "BrowserFileTransferService",
    "browser_file_transfer_service",
    "sanitize_url_provenance",
    "is_sensitive_file",
    "is_sensitive_content",
]

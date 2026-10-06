"""Data models and enums for AURA Advanced Browser Engine (AURA-1001)."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class BrowserState(str, Enum):
    """Canonical 6-state lifecycle for PlaywrightBrowserEngine."""
    CREATED = "created"
    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
    STOPPING = "stopping"
    STOPPED = "stopped"


class TabInfo(BaseModel):
    """Metadata summary of an open browser tab/page."""
    tab_id: str = Field(description="Unique UUID identifier for the tab")
    url: str = Field(default="about:blank", description="Current URL of the tab")
    title: str = Field(default="", description="Current page title")
    is_active: bool = Field(default=False, description="Whether this tab is currently the active tab in its context")
    created_at: float = Field(description="Epoch timestamp of tab creation")
    updated_at: float = Field(description="Epoch timestamp of last navigation / interaction")


class AXTreeNode(BaseModel):
    """Structured representation of an actionable or informative Accessibility Tree node."""
    node_id: int = Field(description="Deterministic 1-indexed identifier assigned during observation")
    role: str = Field(description="Accessibility role (e.g. button, link, textbox, heading, checkbox)")
    name: str = Field(default="", description="Accessible name/label")
    value: Optional[str] = Field(default=None, description="Current value for form controls")
    description: Optional[str] = Field(default=None, description="Accessible description or tooltip")
    disabled: bool = Field(default=False, description="Whether the element is disabled")
    focused: bool = Field(default=False, description="Whether the element currently has input focus")
    checked: Optional[bool] = Field(default=None, description="Checked state for checkboxes/radios")
    pressed: Optional[bool] = Field(default=None, description="Pressed state for toggle buttons")
    selected: Optional[bool] = Field(default=None, description="Selected state for tabs/options")
    bounding_box: Optional[Dict[str, float]] = Field(
        default=None,
        description="Spatial coordinates on viewport {'x': float, 'y': float, 'width': float, 'height': float}"
    )


class PageObservation(BaseModel):
    """Structured observation of a page state including accessibility tree and prompt-sanitized representation."""
    url: str = Field(description="Original requested URL")
    final_url: str = Field(description="Final URL after any client/server redirects")
    title: str = Field(default="", description="Page title")
    status_code: int = Field(default=200, description="HTTP response status code")
    tab_id: str = Field(description="ID of the tab that was observed")
    tabs_count: int = Field(default=1, description="Total number of open tabs in the workspace context")
    viewport: Dict[str, int] = Field(default_factory=lambda: {"width": 1280, "height": 800})
    axtree_nodes: List[AXTreeNode] = Field(default_factory=list, description="Structured accessibility nodes")
    axtree_formatted: str = Field(description="XML formatted representation wrapped in untrusted containment envelope")
    text_content: str = Field(default="", description="Cleaned, sanitized human-readable text")
    is_untrusted_content: bool = Field(default=True, description="Strict classification: untrusted external data")
    security_flags: List[str] = Field(default_factory=list, description="Security screening flags applied")
    captured_at: str = Field(description="ISO-8601 UTC timestamp of observation")


class BrowserResourceMetrics(BaseModel):
    """Resource consumption and concurrency telemetry for the local browser engine."""
    state: BrowserState
    active_contexts: int
    max_contexts_limit: int = 2
    total_tabs: int
    max_tabs_per_context_limit: int = 4
    browser_pid: Optional[int] = None
    memory_rss_mb: float = 0.0
    memory_target_limit_mb: float = 1024.0
    is_over_target_budget: bool = False

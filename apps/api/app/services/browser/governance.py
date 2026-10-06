"""AURA Browser Governance, Semantic Risk Policy, Freshness & Budgeting (AURA-1002)."""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from app.core.errors import AuthorizationError, EntityNotFoundError, ValidationError
from app.core.logging import logger
from app.services.browser.models import AXTreeNode

# Maximum allowed browser interaction actions per task session
MAX_BROWSER_ACTIONS_PER_TASK = 30

# Maximum observation TTL before interaction is rejected as stale
DEFAULT_OBSERVATION_TTL_SECONDS = 15.0

# Allowed browser keyboard keys for governed press_key
ALLOWED_BROWSER_KEYS: Set[str] = {
    "Enter",
    "Tab",
    "Escape",
    "ArrowDown",
    "ArrowUp",
    "ArrowLeft",
    "ArrowRight",
    "PageDown",
    "PageUp",
    "Home",
    "End",
    "Backspace",
    "Delete",
    "Space",
}

# Forbidden dangerous shortcuts and key combinations
FORBIDDEN_KEY_PATTERNS = [
    re.compile(r"control\+alt\+delete", re.IGNORECASE),
    re.compile(r"alt\+f4", re.IGNORECASE),
    re.compile(r"meta", re.IGNORECASE),
    re.compile(r"win", re.IGNORECASE),
    re.compile(r"cmd", re.IGNORECASE),
    re.compile(r"super", re.IGNORECASE),
]

# Sensitive input field patterns requiring High Risk HITL and text redaction
SENSITIVE_FIELD_PATTERNS = [
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"passcode", re.IGNORECASE),
    re.compile(r"pin", re.IGNORECASE),
    re.compile(r"credit_?card", re.IGNORECASE),
    re.compile(r"card_?number", re.IGNORECASE),
    re.compile(r"cvv", re.IGNORECASE),
    re.compile(r"cvc", re.IGNORECASE),
    re.compile(r"ssn", re.IGNORECASE),
    re.compile(r"social_?security", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"api_?key", re.IGNORECASE),
    re.compile(r"auth_?token", re.IGNORECASE),
    re.compile(r"private_?key", re.IGNORECASE),
]

# High-risk button / interaction semantic keywords
HIGH_RISK_ACTION_PATTERNS = [
    re.compile(r"\b(submit|order|checkout|pay|payment|purchase|buy)\b", re.IGNORECASE),
    re.compile(r"\b(delete|remove|destroy|purge|erase)\b", re.IGNORECASE),
    re.compile(r"\b(confirm|send|transfer|authorize|apply)\b", re.IGNORECASE),
    re.compile(r"\b(save changes|update password|reset password|deactivate|unsubscribe|terminate)\b", re.IGNORECASE),
    re.compile(r"\b(post comment|publish|send message|send email)\b", re.IGNORECASE),
]

# Critical-risk action patterns (Financial / Account Deletion / Master Credentials)
CRITICAL_ACTION_PATTERNS = [
    re.compile(r"\b(transfer funds|wire transfer|execute transaction)\b", re.IGNORECASE),
    re.compile(r"\b(delete account|close account|wipe data)\b", re.IGNORECASE),
    re.compile(r"\b(change master password|rotate root key)\b", re.IGNORECASE),
]


class BrowserRiskLevel(str, Enum):
    """Semantic risk classification for browser actions."""
    READ_ONLY = "low"
    LOW_RISK_INTERACTION = "low"
    MEDIUM_RISK_INTERACTION = "medium"
    HIGH_RISK_INTERACTION = "high"
    CRITICAL_ACTION = "critical"


@dataclass
class ObservationRecord:
    """Stored page observation snapshot with freshness TTL tracking."""
    workspace_id: uuid.UUID
    tab_id: str
    url: str
    title: str
    captured_at: float
    nodes: Dict[int, AXTreeNode]
    ttl_seconds: float = DEFAULT_OBSERVATION_TTL_SECONDS

    @property
    def is_fresh(self) -> bool:
        return (time.time() - self.captured_at) <= self.ttl_seconds

    @property
    def age_seconds(self) -> float:
        return time.time() - self.captured_at


class ObservationFreshnessStore:
    """Tracks and validates page observation snapshots to prevent stale element execution."""

    def __init__(self):
        # Key: (workspace_id, tab_id) -> ObservationRecord
        self._observations: Dict[Tuple[uuid.UUID, str], ObservationRecord] = {}

    def record_observation(
        self,
        workspace_id: uuid.UUID,
        tab_id: str,
        url: str,
        title: str,
        nodes: List[AXTreeNode],
        ttl_seconds: float = DEFAULT_OBSERVATION_TTL_SECONDS,
    ) -> ObservationRecord:
        """Record a fresh page observation snapshot."""
        nodes_dict = {n.node_id: n for n in nodes}
        rec = ObservationRecord(
            workspace_id=workspace_id,
            tab_id=tab_id,
            url=url,
            title=title,
            captured_at=time.time(),
            nodes=nodes_dict,
            ttl_seconds=ttl_seconds,
        )
        self._observations[(workspace_id, tab_id)] = rec
        return rec

    def get_observation(self, workspace_id: uuid.UUID, tab_id: str) -> Optional[ObservationRecord]:
        """Retrieve stored observation if available."""
        return self._observations.get((workspace_id, tab_id))

    def get_element(
        self,
        workspace_id: uuid.UUID,
        tab_id: str,
        node_id: int,
    ) -> AXTreeNode:
        """Fetch element by node_id ensuring observation freshness and workspace binding."""
        rec = self._observations.get((workspace_id, tab_id))
        if not rec:
            raise ValidationError(
                f"No active page observation found for workspace {workspace_id} tab {tab_id}. "
                "Execute browser_get_page_state before interacting with elements."
            )

        if not rec.is_fresh:
            raise ValidationError(
                f"Page observation is stale ({round(rec.age_seconds, 1)}s old > {rec.ttl_seconds}s TTL). "
                "Execute browser_get_page_state to obtain fresh element references before interacting."
            )

        if node_id not in rec.nodes:
            raise ValidationError(
                f"Element ID {node_id} does not exist in current observation for tab {tab_id} "
                f"(Total observed elements: {len(rec.nodes)})."
            )

        return rec.nodes[node_id]

    def invalidate(self, workspace_id: uuid.UUID, tab_id: Optional[str] = None) -> None:
        """Invalidate observation for tab or entire workspace on navigation/tab close."""
        if tab_id:
            self._observations.pop((workspace_id, tab_id), None)
        else:
            keys_to_remove = [k for k in self._observations.keys() if k[0] == workspace_id]
            for k in keys_to_remove:
                self._observations.pop(k, None)

    def clear(self) -> None:
        """Clear all stored observations."""
        self._observations.clear()


class BrowserActionBudgetManager:
    """Enforces deterministic task-level and workspace-level browser action limits."""

    def __init__(self, max_actions_per_task: int = MAX_BROWSER_ACTIONS_PER_TASK):
        self.max_actions = max_actions_per_task
        # Key: task_id (str) or workspace_id (str) -> int count
        self._counts: Dict[str, int] = {}

    def _get_key(self, workspace_id: uuid.UUID, task_id: Optional[str]) -> str:
        return task_id if task_id else str(workspace_id)

    def consume_action(
        self,
        workspace_id: uuid.UUID,
        task_id: Optional[str] = None,
        action_name: str = "browser_action",
    ) -> int:
        """Increment action count and verify budget ceiling."""
        key = self._get_key(workspace_id, task_id)
        current = self._counts.get(key, 0)

        if current >= self.max_actions:
            logger.warning(
                f"BrowserBudgetManager: Budget exceeded ({current}/{self.max_actions}) for key '{key}' on {action_name}"
            )
            raise ValidationError(
                f"Browser action budget exceeded ({current}/{self.max_actions} actions used). "
                "Further browser interactions are blocked for this task session to prevent runaway automation."
            )

        self._counts[key] = current + 1
        return self._counts[key]

    def get_count(self, workspace_id: uuid.UUID, task_id: Optional[str] = None) -> int:
        """Get current consumed action count."""
        key = self._get_key(workspace_id, task_id)
        return self._counts.get(key, 0)

    def reset_budget(self, workspace_id: uuid.UUID, task_id: Optional[str] = None) -> None:
        """Reset action count for task or workspace."""
        key = self._get_key(workspace_id, task_id)
        self._counts.pop(key, None)

    def clear(self) -> None:
        """Clear all budget counters."""
        self._counts.clear()


class BrowserRiskClassifier:
    """Evaluates deterministic semantic risk for agent-directed browser interactions."""

    @staticmethod
    def is_sensitive_field(node: AXTreeNode) -> bool:
        """Detect whether an input field represents passwords, financial tokens, or credentials."""
        combined_text = f"{node.role} {node.name} {node.description or ''}"
        for pat in SENSITIVE_FIELD_PATTERNS:
            if pat.search(combined_text):
                return True
        return False

    @classmethod
    def evaluate_risk(
        cls,
        tool_name: str,
        arguments: Dict[str, Any],
        workspace_id: uuid.UUID,
        observation_store: Optional[ObservationFreshnessStore] = None,
    ) -> str:
        """Evaluate deterministic risk tier for a tool invocation."""
        store = observation_store or freshness_store

        # 1. Read-Only Tools
        if tool_name in ["browser_navigate", "browser_get_page_state", "browser_screenshot"]:
            return "low"

        # 2. Scroll & Tab Management Tools
        if tool_name in ["browser_scroll", "browser_tab_manage"]:
            return "low"

        # 3. Key Press Tool
        if tool_name == "browser_press_key":
            key = str(arguments.get("key", "")).strip()
            # Check forbidden shortcuts
            for pat in FORBIDDEN_KEY_PATTERNS:
                if pat.search(key):
                    raise ValidationError(f"Forbidden browser keyboard combination: '{key}'")
            if key not in ALLOWED_BROWSER_KEYS:
                raise ValidationError(
                    f"Disallowed browser key '{key}'. Allowed keys: {sorted(list(ALLOWED_BROWSER_KEYS))}"
                )
            if key in ["Enter"]:
                return "medium"
            return "low"

        # 4. Form Select Tool
        if tool_name == "browser_select":
            return "medium"

        # 5. Type Text Tool
        if tool_name == "browser_type":
            tab_id = arguments.get("tab_id")
            element_id = arguments.get("element_id")
            text = str(arguments.get("text", ""))

            # Basic input sanitization check
            if "\x00" in text:
                raise ValidationError("Typed text contains prohibited NUL characters")
            if len(text) > 2000:
                raise ValidationError(f"Typed text length ({len(text)}) exceeds maximum allowed limit (2000 chars)")

            if tab_id and element_id is not None:
                try:
                    node = store.get_element(workspace_id, tab_id, int(element_id))
                    if cls.is_sensitive_field(node):
                        return "high"
                except Exception:
                    pass
            return "medium"

        # 6. Click Element Tool (Semantic Evaluation)
        if tool_name == "browser_click":
            tab_id = arguments.get("tab_id")
            element_id = arguments.get("element_id")

            if tab_id and element_id is not None:
                try:
                    node = store.get_element(workspace_id, tab_id, int(element_id))
                    node_text = f"{node.role} {node.name} {node.description or ''}".strip()

                    # Critical action check
                    for pat in CRITICAL_ACTION_PATTERNS:
                        if pat.search(node_text):
                            return "critical"

                    # High risk action check
                    for pat in HIGH_RISK_ACTION_PATTERNS:
                        if pat.search(node_text):
                            return "high"

                    # Submit button check
                    if node.role == "button" and ("submit" in node.name.lower() or "submit" in node.role.lower()):
                        return "high"

                except Exception:
                    # If element resolution fails here, it will be validated during execution
                    pass

            return "low"

        # 7. Credential & Session Vault Tools (AURA-1003)
        if tool_name == "browser_inject_credential":
            return "high"

        if tool_name == "browser_list_credentials":
            return "low"

        if tool_name in ["browser_save_session", "browser_restore_session"]:
            return "medium"

        # Default fallback
        return "low"

    @staticmethod
    def mask_sensitive_value(text: str, role: str = "field") -> str:
        """Create privacy-preserving summary of sensitive content without persisting plaintext."""
        return f"[REDACTED_{role.upper()}: {len(text)} chars]"


# Global Singleton Instances
freshness_store = ObservationFreshnessStore()
action_budget_manager = BrowserActionBudgetManager()
browser_risk_classifier = BrowserRiskClassifier()

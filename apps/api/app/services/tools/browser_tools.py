"""Governed Browser Interaction Tools (AURA-1002).

Implements strictly governed, agent-callable browser interaction tools:
- browser_navigate
- browser_get_page_state
- browser_screenshot
- browser_click
- browser_type
- browser_select
- browser_scroll
- browser_press_key
- browser_tab_manage
"""

from __future__ import annotations

import asyncio
import base64
import time
import uuid
from typing import Any, Dict, List, Optional

from app.core.errors import AuthorizationError, EntityNotFoundError, ValidationError
from app.core.logging import logger
from app.services.browser.engine import browser_engine
from app.services.browser.governance import (
    ALLOWED_BROWSER_KEYS,
    FORBIDDEN_KEY_PATTERNS,
    action_budget_manager,
    browser_risk_classifier,
    freshness_store,
)


def _check_kill_switch(workspace_id: uuid.UUID) -> None:
    """Helper to check kill switch without module-level circular import."""
    from app.services.kill_switch import kill_switch
    if kill_switch.is_active(workspace_id):
        raise AuthorizationError(f"Emergency Kill Switch is active for workspace {workspace_id}.")


async def execute_browser_navigate(
    workspace_id: uuid.UUID,
    url: str,
    tab_id: Optional[str] = None,
    wait_until: str = "domcontentloaded",
    timeout_ms: int = 25000,
    task_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Governed browser navigation tool."""
    # 1. Kill Switch Check
    _check_kill_switch(workspace_id)

    # 2. Consume Action Budget
    action_budget_manager.consume_action(workspace_id, task_id, "browser_navigate")

    # 3. Invalidate prior observations on navigation
    freshness_store.invalidate(workspace_id, tab_id)

    # 4. Perform Navigation
    res = await browser_engine.navigate(
        workspace_id=workspace_id,
        url=url,
        tab_id=tab_id,
        wait_until=wait_until,
        timeout_ms=timeout_ms,
    )

    return res


async def execute_browser_get_page_state(
    workspace_id: uuid.UUID,
    tab_id: Optional[str] = None,
    max_elements: int = 100,
    max_chars: int = 8000,
    task_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Governed page observation and AXTree snapshot extraction tool."""
    # 1. Kill Switch Check
    _check_kill_switch(workspace_id)

    # 2. Consume Action Budget
    action_budget_manager.consume_action(workspace_id, task_id, "browser_get_page_state")

    # 3. Observe Page
    obs = await browser_engine.observe_page(
        workspace_id=workspace_id,
        tab_id=tab_id,
        max_elements=max_elements,
        max_chars=max_chars,
    )

    # 4. Record fresh observation snapshot for element reference validation
    freshness_store.record_observation(
        workspace_id=workspace_id,
        tab_id=obs.tab_id,
        url=obs.final_url,
        title=obs.title,
        nodes=obs.axtree_nodes,
    )

    return obs.model_dump()


async def execute_browser_screenshot(
    workspace_id: uuid.UUID,
    tab_id: Optional[str] = None,
    full_page: bool = False,
    task_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Governed viewport/full-page screenshot capture tool with zero disk persistence."""
    # 1. Kill Switch Check
    _check_kill_switch(workspace_id)

    # 2. Consume Action Budget
    action_budget_manager.consume_action(workspace_id, task_id, "browser_screenshot")

    # 3. Capture Screenshot bytes
    screenshot_bytes = await browser_engine.capture_screenshot(
        workspace_id=workspace_id,
        tab_id=tab_id,
        full_page=full_page,
    )

    b64_data = base64.b64encode(screenshot_bytes).decode("ascii")

    return {
        "status": "success",
        "tab_id": tab_id or "active",
        "format": "png",
        "size_bytes": len(screenshot_bytes),
        "data_base64_preview": b64_data[:120] + "...[truncated]",
        "is_untrusted_content": True,
    }


async def execute_browser_click(
    workspace_id: uuid.UUID,
    element_id: int,
    tab_id: Optional[str] = None,
    click_count: int = 1,
    button: str = "left",
    task_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Governed click on observed element by numeric ID."""
    # 1. Kill Switch Check
    _check_kill_switch(workspace_id)

    # 2. Validate Parameters
    if click_count not in [1, 2, 3]:
        raise ValidationError("click_count must be 1, 2, or 3")
    if button not in ["left", "right", "middle"]:
        raise ValidationError("button must be 'left', 'right', or 'middle'")

    # 3. Consume Action Budget
    action_budget_manager.consume_action(workspace_id, task_id, "browser_click")

    # 4. Fail-fast Element & Freshness check if tab_id provided
    if tab_id:
        target_tab_id = tab_id
        node = freshness_store.get_element(workspace_id, target_tab_id, element_id)
        if node.disabled:
            raise ValidationError(f"Element ID {element_id} ('{node.name}') is disabled and cannot be clicked.")
        _check_kill_switch(workspace_id)
        ws_ctx = await browser_engine.get_or_create_workspace_context(workspace_id)
    else:
        ws_ctx = await browser_engine.get_or_create_workspace_context(workspace_id)
        target_tab_id = ws_ctx.active_tab_id
        if not target_tab_id:
            raise ValidationError("No active tab found for workspace context")
        node = freshness_store.get_element(workspace_id, target_tab_id, element_id)
        if node.disabled:
            raise ValidationError(f"Element ID {element_id} ('{node.name}') is disabled and cannot be clicked.")
        _check_kill_switch(workspace_id)

    # 5. Execute Native Click
    page = ws_ctx.get_page(target_tab_id)

    if node.bounding_box:
        center_x = node.bounding_box["x"] + (node.bounding_box["width"] / 2.0)
        center_y = node.bounding_box["y"] + (node.bounding_box["height"] / 2.0)
        await page.mouse.click(center_x, center_y, click_count=click_count, button=button) # type: ignore
    else:
        # Fallback click on active element or locator if bounding box not resolved
        await page.keyboard.press("Enter")

    # Brief hydration pause
    await asyncio.sleep(0.15)

    return {
        "status": "success",
        "action": "click",
        "element_id": element_id,
        "role": node.role,
        "name": node.name,
        "tab_id": target_tab_id,
        "url": page.url,
        "is_untrusted_content": True,
    }


async def execute_browser_type(
    workspace_id: uuid.UUID,
    element_id: int,
    text: str,
    clear_first: bool = True,
    press_enter: bool = False,
    tab_id: Optional[str] = None,
    task_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Governed typing into input field by numeric element ID."""
    # 1. Kill Switch Check
    _check_kill_switch(workspace_id)

    # 2. Input Validation
    if "\x00" in text:
        raise ValidationError("Prohibited NUL byte in typed text")
    if len(text) > 2000:
        raise ValidationError(f"Text length ({len(text)}) exceeds maximum allowed (2000 chars)")

    # 3. Consume Action Budget
    action_budget_manager.consume_action(workspace_id, task_id, "browser_type")

    # 4. Fail-fast Element & Freshness check
    if tab_id:
        target_tab_id = tab_id
        node = freshness_store.get_element(workspace_id, target_tab_id, element_id)
        if node.disabled:
            raise ValidationError(f"Element ID {element_id} ('{node.name}') is disabled and cannot receive text input.")
        is_sensitive = browser_risk_classifier.is_sensitive_field(node)
        _check_kill_switch(workspace_id)
        ws_ctx = await browser_engine.get_or_create_workspace_context(workspace_id)
    else:
        ws_ctx = await browser_engine.get_or_create_workspace_context(workspace_id)
        target_tab_id = ws_ctx.active_tab_id
        if not target_tab_id:
            raise ValidationError("No active tab found for workspace context")
        node = freshness_store.get_element(workspace_id, target_tab_id, element_id)
        if node.disabled:
            raise ValidationError(f"Element ID {element_id} ('{node.name}') is disabled and cannot receive text input.")
        is_sensitive = browser_risk_classifier.is_sensitive_field(node)
        _check_kill_switch(workspace_id)

    # 5. Execute Native Type
    page = ws_ctx.get_page(target_tab_id)

    # Focus element
    if node.bounding_box:
        center_x = node.bounding_box["x"] + (node.bounding_box["width"] / 2.0)
        center_y = node.bounding_box["y"] + (node.bounding_box["height"] / 2.0)
        await page.mouse.click(center_x, center_y)

    if clear_first:
        # Standard select all and clear
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Backspace")

    await page.keyboard.type(text)

    if press_enter:
        await page.keyboard.press("Enter")

    await asyncio.sleep(0.1)

    text_summary = (
        browser_risk_classifier.mask_sensitive_value(text, node.role)
        if is_sensitive
        else (text if len(text) <= 50 else text[:50] + "...")
    )

    return {
        "status": "success",
        "action": "type",
        "element_id": element_id,
        "role": node.role,
        "character_count": len(text),
        "is_sensitive": is_sensitive,
        "text_summary": text_summary,
        "tab_id": target_tab_id,
        "is_untrusted_content": True,
    }


async def execute_browser_select(
    workspace_id: uuid.UUID,
    element_id: int,
    value: str,
    tab_id: Optional[str] = None,
    task_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Governed option selection in dropdowns."""
    # 1. Kill Switch Check
    _check_kill_switch(workspace_id)

    # 2. Consume Action Budget
    action_budget_manager.consume_action(workspace_id, task_id, "browser_select")

    # 3. Fail-fast Element & Freshness check
    if tab_id:
        target_tab_id = tab_id
        node = freshness_store.get_element(workspace_id, target_tab_id, element_id)
        if node.disabled:
            raise ValidationError(f"Element ID {element_id} ('{node.name}') is disabled.")
        _check_kill_switch(workspace_id)
        ws_ctx = await browser_engine.get_or_create_workspace_context(workspace_id)
    else:
        ws_ctx = await browser_engine.get_or_create_workspace_context(workspace_id)
        target_tab_id = ws_ctx.active_tab_id
        if not target_tab_id:
            raise ValidationError("No active tab found for workspace context")
        node = freshness_store.get_element(workspace_id, target_tab_id, element_id)
        if node.disabled:
            raise ValidationError(f"Element ID {element_id} ('{node.name}') is disabled.")
        _check_kill_switch(workspace_id)

    page = ws_ctx.get_page(target_tab_id)

    # Click element to open dropdown
    if node.bounding_box:
        center_x = node.bounding_box["x"] + (node.bounding_box["width"] / 2.0)
        center_y = node.bounding_box["y"] + (node.bounding_box["height"] / 2.0)
        await page.mouse.click(center_x, center_y)

    await page.keyboard.type(value)
    await page.keyboard.press("Enter")

    await asyncio.sleep(0.1)

    return {
        "status": "success",
        "action": "select",
        "element_id": element_id,
        "value": value,
        "tab_id": target_tab_id,
        "is_untrusted_content": True,
    }


async def execute_browser_scroll(
    workspace_id: uuid.UUID,
    direction: str = "down",
    amount: int = 300,
    tab_id: Optional[str] = None,
    task_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Governed bounded scrolling on active webpage."""
    # 1. Kill Switch Check
    _check_kill_switch(workspace_id)

    # 2. Parameter Validation
    dir_clean = direction.lower().strip()
    if dir_clean not in ["down", "up", "top", "bottom"]:
        raise ValidationError(f"Invalid direction '{direction}'. Supported: down, up, top, bottom")

    clamped_amount = min(max(10, amount), 2000)

    # 3. Consume Action Budget
    action_budget_manager.consume_action(workspace_id, task_id, "browser_scroll")

    # 4. Resolve Context & Tab
    ws_ctx = await browser_engine.get_or_create_workspace_context(workspace_id)
    target_tab_id = tab_id or ws_ctx.active_tab_id
    page = ws_ctx.get_page(target_tab_id)

    # 5. Scroll using mouse wheel
    if dir_clean == "down":
        await page.mouse.wheel(0, clamped_amount)
    elif dir_clean == "up":
        await page.mouse.wheel(0, -clamped_amount)
    elif dir_clean == "top":
        await page.keyboard.press("Home")
    elif dir_clean == "bottom":
        await page.keyboard.press("End")

    await asyncio.sleep(0.15)

    return {
        "status": "success",
        "action": "scroll",
        "direction": dir_clean,
        "amount": clamped_amount,
        "tab_id": target_tab_id,
        "is_untrusted_content": True,
    }


async def execute_browser_press_key(
    workspace_id: uuid.UUID,
    key: str,
    tab_id: Optional[str] = None,
    task_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Governed keyboard key press with strict allowlist and OS-bypass defense."""
    # 1. Kill Switch Check
    _check_kill_switch(workspace_id)

    # 2. Validate Key
    key_clean = key.strip()
    for pat in FORBIDDEN_KEY_PATTERNS:
        if pat.search(key_clean):
            raise ValidationError(f"Forbidden keyboard combination '{key_clean}'. OS shortcuts are disallowed.")

    if key_clean not in ALLOWED_BROWSER_KEYS:
        raise ValidationError(
            f"Disallowed browser key '{key_clean}'. Allowed keys: {sorted(list(ALLOWED_BROWSER_KEYS))}"
        )

    # 3. Consume Action Budget
    action_budget_manager.consume_action(workspace_id, task_id, "browser_press_key")

    # 4. Resolve Context & Tab
    ws_ctx = await browser_engine.get_or_create_workspace_context(workspace_id)
    target_tab_id = tab_id or ws_ctx.active_tab_id
    page = ws_ctx.get_page(target_tab_id)

    # 5. Press Key
    await page.keyboard.press(key_clean)
    await asyncio.sleep(0.1)

    return {
        "status": "success",
        "action": "press_key",
        "key": key_clean,
        "tab_id": target_tab_id,
        "is_untrusted_content": True,
    }


async def execute_browser_tab_manage(
    workspace_id: uuid.UUID,
    action: str = "list",
    tab_id: Optional[str] = None,
    url: Optional[str] = None,
    task_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Governed tab lifecycle management (create, switch, close, list) up to 4 tabs/context."""
    # 1. Kill Switch Check
    _check_kill_switch(workspace_id)

    # 2. Validate Action
    act = action.lower().strip()
    if act not in ["create", "switch", "close", "list"]:
        raise ValidationError(f"Invalid tab action '{action}'. Supported: create, switch, close, list")

    # 3. Consume Action Budget
    action_budget_manager.consume_action(workspace_id, task_id, "browser_tab_manage")

    # 4. Dispatch Action
    if act == "create":
        tab_info = await browser_engine.create_tab(workspace_id=workspace_id, url=url)
        return {
            "status": "success",
            "action": "create",
            "tab": tab_info.model_dump(),
            "total_tabs": len(browser_engine.list_tabs(workspace_id)),
        }

    elif act == "switch":
        if not tab_id:
            raise ValidationError("tab_id is required for switch action")
        tab_info = browser_engine.switch_tab(workspace_id=workspace_id, tab_id=tab_id)
        return {
            "status": "success",
            "action": "switch",
            "tab": tab_info.model_dump(),
            "total_tabs": len(browser_engine.list_tabs(workspace_id)),
        }

    elif act == "close":
        if not tab_id:
            raise ValidationError("tab_id is required for close action")
        freshness_store.invalidate(workspace_id, tab_id)
        await browser_engine.close_tab(workspace_id=workspace_id, tab_id=tab_id)
        return {
            "status": "success",
            "action": "close",
            "closed_tab_id": tab_id,
            "total_tabs": len(browser_engine.list_tabs(workspace_id)),
        }

    else:  # list
        tabs = browser_engine.list_tabs(workspace_id=workspace_id)
        return {
            "status": "success",
            "action": "list",
            "tabs": [t.model_dump() for t in tabs],
            "total_tabs": len(tabs),
        }

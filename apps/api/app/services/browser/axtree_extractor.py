"""Accessibility Tree (AXTree) snapshot extraction and XML prompt containment."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from playwright.async_api import Page

from app.core.logging import logger
from app.core.sanitization import prompt_sanitizer
from app.services.browser.models import AXTreeNode

DOM_EXTRACTOR_JS = """
() => {
    const actionableTags = ['A', 'BUTTON', 'INPUT', 'SELECT', 'TEXTAREA', 'SUMMARY'];
    const informativeTags = ['H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'P', 'LI', 'LABEL'];
    const results = [];
    const elements = document.querySelectorAll('*');

    for (const el of elements) {
        const tag = el.tagName;
        let role = el.getAttribute('role');
        if (!role) {
            if (tag === 'A') role = 'link';
            else if (tag === 'BUTTON') role = 'button';
            else if (tag === 'INPUT') {
                const type = (el.type || 'text').toLowerCase();
                if (type === 'submit' || type === 'button' || type === 'reset') role = 'button';
                else if (type === 'checkbox') role = 'checkbox';
                else if (type === 'radio') role = 'radio';
                else role = 'textbox';
            } else if (tag === 'SELECT') role = 'combobox';
            else if (tag === 'TEXTAREA') role = 'textbox';
            else if (tag.startsWith('H') && tag.length === 2) role = 'heading';
            else role = tag.toLowerCase();
        }

        const ariaLabel = el.getAttribute('aria-label');
        const placeholder = el.getAttribute('placeholder');
        const title = el.getAttribute('title');
        const alt = el.getAttribute('alt');
        
        let directText = '';
        for (const child of el.childNodes) {
            if (child.nodeType === 3) { // Node.TEXT_NODE
                directText += child.textContent;
            }
        }
        directText = directText.trim();
        let fullText = (el.innerText || el.textContent || '').trim();
        if (fullText.length > 200) fullText = fullText.substring(0, 200);

        const name = ariaLabel || placeholder || title || alt || directText || (tag === 'BUTTON' || tag === 'A' || tag.startsWith('H') ? fullText : '') || '';
        const value = (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') ? el.value : null;

        const isActionable = actionableTags.includes(tag) || el.hasAttribute('onclick') || role === 'button' || role === 'link';
        const isInformative = (informativeTags.includes(tag) || role === 'heading') && (directText.length > 0 || fullText.length > 0);

        if (isActionable || isInformative) {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            const isVisible = rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
            if (isVisible) {
                results.push({
                    role: role,
                    name: name,
                    value: value,
                    disabled: Boolean(el.disabled),
                    checked: el.checked !== undefined ? Boolean(el.checked) : null,
                    focused: document.activeElement === el,
                    boundingBox: {
                        x: Math.round(rect.x),
                        y: Math.round(rect.y),
                        width: Math.round(rect.width),
                        height: Math.round(rect.height)
                    }
                });
            }
        }
    }
    return results;
}
"""


class AXTreeExtractor:
    """Extracts and formats compact, deterministic, prompt-sanitized Accessibility Tree representations."""

    @staticmethod
    async def extract(
        page: "Page",
        max_elements: int = 100,
        max_chars: int = 8000,
    ) -> Tuple[List[AXTreeNode], str, List[str]]:
        """Extract AXTree snapshot from page, return structured nodes, formatted XML, and security flags."""
        security_flags: List[str] = ["axtree_extracted"]
        clamped_max_elements = min(max(10, max_elements), 200)
        clamped_max_chars = min(max(500, max_chars), 20000)

        nodes: List[AXTreeNode] = []
        node_counter = 1

        url = page.url or "about:blank"
        try:
            title = await page.title()
        except Exception:
            title = ""

        # 1. Primary Extraction: DOM Accessibility Evaluation
        raw_items: List[Dict[str, Any]] = []
        try:
            raw_items = await page.evaluate(DOM_EXTRACTOR_JS)
        except Exception as e:
            logger.warning(f"AXTreeExtractor: DOM evaluation failed: {e}")

        # 2. Process extracted elements
        for item in raw_items:
            if len(nodes) >= clamped_max_elements:
                break

            role = str(item.get("role", "")).lower()
            name = str(item.get("name", "")).strip()
            value = item.get("value")
            disabled = bool(item.get("disabled", False))
            focused = bool(item.get("focused", False))
            checked = item.get("checked")
            bb = item.get("boundingBox")

            # Clean and sanitize strings
            clean_name = prompt_sanitizer.clean_unicode_and_controls(name) if name else ""
            escaped_name = prompt_sanitizer.escape_delimiters(clean_name)
            has_inj_name, name_flags = prompt_sanitizer.detect_injection_signatures(escaped_name)
            if has_inj_name:
                for flag in name_flags:
                    if flag not in security_flags:
                        security_flags.append(flag)

            clean_val = None
            if value is not None:
                clean_val = prompt_sanitizer.clean_unicode_and_controls(str(value))
                clean_val = prompt_sanitizer.escape_delimiters(clean_val)
                has_inj_val, val_flags = prompt_sanitizer.detect_injection_signatures(clean_val)
                if has_inj_val:
                    for flag in val_flags:
                        if flag not in security_flags:
                            security_flags.append(flag)

            node = AXTreeNode(
                node_id=node_counter,
                role=role or "element",
                name=escaped_name,
                value=clean_val,
                disabled=disabled,
                focused=focused,
                checked=checked if isinstance(checked, bool) else None,
                bounding_box=bb if isinstance(bb, dict) else None,
            )
            nodes.append(node)
            node_counter += 1

        # 3. Format XML envelope
        now_iso = datetime.now(timezone.utc).isoformat()
        clean_title = prompt_sanitizer.escape_delimiters(prompt_sanitizer.clean_unicode_and_controls(title))
        lines: List[str] = [
            f'<untrusted_web_content source="{url}" title="{clean_title}" timestamp="{now_iso}">'
        ]

        if not nodes:
            lines.append("  [No interactive or accessible accessibility elements detected on page]")
        else:
            for n in nodes:
                role_str = n.role
                name_part = f' "{n.name}"' if n.name else ""
                val_part = f' [value="{n.value}"]' if n.value is not None else ""
                check_part = f' [checked={str(n.checked).lower()}]' if n.checked is not None else ""
                dis_part = " [disabled]" if n.disabled else ""
                foc_part = " [focused]" if n.focused else ""
                bb_part = f' (x: {int(n.bounding_box["x"])}, y: {int(n.bounding_box["y"])})' if n.bounding_box else ""
                line = f"  [{n.node_id}] {role_str}{name_part}{val_part}{check_part}{dis_part}{foc_part}{bb_part}"
                lines.append(line)

        lines.append("</untrusted_web_content>")
        formatted_xml = "\n".join(lines)[:clamped_max_chars]

        return nodes, formatted_xml, security_flags

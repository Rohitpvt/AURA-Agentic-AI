"""HTML Cleaner and Deterministic Markdown Conversion Utility for Headless Web Extraction."""

import re
from typing import Optional
from bs4 import BeautifulSoup, Comment, NavigableString, Tag

# Elements to completely strip from DOM before extraction
STRIP_ELEMENTS = {
    "script",
    "style",
    "noscript",
    "iframe",
    "svg",
    "canvas",
    "audio",
    "video",
    "source",
    "track",
    "embed",
    "object",
    "applet",
    "meta",
    "link",
    "form",
    "input",
    "button",
    "select",
    "textarea",
    "dialog",
    "template",
}

# Elements that typically represent boilerplate or non-content navigation
BOILERPLATE_SELECTORS = [
    "nav",
    "footer",
    "header",
    "aside",
    ".nav",
    ".navbar",
    ".footer",
    ".header",
    ".sidebar",
    ".advertisement",
    ".ad-container",
    ".cookie-banner",
    ".cookie-consent",
    ".gdpr-modal",
    "#cookie-banner",
    "#gdpr-consent",
]


class HTMLToMarkdownConverter:
    """Converts cleaned HTML to compact, structured Markdown without external dependencies."""

    def clean_html(self, html_content: str, max_html_bytes: int = 5 * 1024 * 1024) -> BeautifulSoup:
        """Clean raw HTML: remove scripts, styles, boilerplates, and comments."""
        if len(html_content.encode("utf-8")) > max_html_bytes:
            # Truncate oversized raw HTML before parsing
            html_content = html_content[:max_html_bytes]

        soup = BeautifulSoup(html_content, "html.parser")

        # 1. Remove HTML comments
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()

        # 2. Strip dangerous and non-semantic tags
        for tag_name in STRIP_ELEMENTS:
            for element in soup.find_all(tag_name):
                element.decompose()

        # 3. Strip hidden elements
        for element in soup.find_all(True):
            style = element.get("style", "")
            if isinstance(style, str) and ("display:none" in style.replace(" ", "") or "visibility:hidden" in style.replace(" ", "")):
                element.decompose()
            elif element.get("aria-hidden") == "true" or element.get("hidden") is not None:
                element.decompose()

        # 4. Strip boilerplate containers if semantic main content exists
        body = soup.find("body") or soup
        main_content = body.find("main") or body.find("article") or body.find("div", {"id": re.compile(r"content|main|article", re.I)})
        if main_content:
            # If a clear main content container exists, remove navigational boilerplates
            for selector in BOILERPLATE_SELECTORS:
                for element in body.select(selector):
                    # Do not remove if it is the main content container itself
                    if element != main_content and not main_content.find(lambda t: t == element):
                        element.decompose()

        return soup

    def extract_title(self, soup: BeautifulSoup) -> str:
        """Extract clean document title."""
        title_tag = soup.find("title")
        if title_tag and title_tag.string:
            return title_tag.string.strip()[:200]
        h1 = soup.find("h1")
        if h1:
            return h1.get_text().strip()[:200]
        return "Untitled Page"

    def convert_to_markdown(self, soup: BeautifulSoup, max_chars: int = 8000) -> str:
        """Convert cleaned DOM into readable, compact Markdown."""
        body = soup.find("body") or soup
        lines: list[str] = []

        self._traverse_node(body, lines)

        raw_md = "\n".join(lines)
        # Normalize whitespace and blank lines (max 2 consecutive newlines)
        cleaned_md = re.sub(r"\n{3,}", "\n\n", raw_md).strip()

        if len(cleaned_md) > max_chars:
            return cleaned_md[:max_chars].rstrip() + "\n\n[Content truncated due to length limits...]"
        return cleaned_md

    def _traverse_node(self, node: Tag | NavigableString, lines: list[str], prefix: str = "") -> None:
        """Recursive node traversal to generate Markdown."""
        if isinstance(node, NavigableString):
            text = str(node).strip()
            if text:
                lines.append(f"{prefix}{text}")
            return

        if not isinstance(node, Tag):
            return

        tag_name = node.name.lower()

        # Headings
        if tag_name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            level = int(tag_name[1])
            text = node.get_text().strip()
            if text:
                lines.append("")
                lines.append(f"{'#' * level} {text}")
                lines.append("")
            return

        # Paragraphs
        elif tag_name == "p":
            text = self._inline_markdown(node)
            if text:
                lines.append("")
                lines.append(f"{prefix}{text}")
                lines.append("")
            return

        # Blockquote
        elif tag_name == "blockquote":
            text = node.get_text().strip()
            if text:
                lines.append("")
                for q_line in text.split("\n"):
                    if q_line.strip():
                        lines.append(f"> {q_line.strip()}")
                lines.append("")
            return

        # Code block
        elif tag_name == "pre":
            code_tag = node.find("code")
            code_text = (code_tag or node).get_text()
            if code_text.strip():
                lines.append("")
                lines.append("```")
                lines.append(code_text.rstrip())
                lines.append("```")
                lines.append("")
            return

        # Lists
        elif tag_name == "ul":
            for li in node.find_all("li", recursive=False):
                li_text = self._inline_markdown(li)
                if li_text:
                    lines.append(f"{prefix}- {li_text}")
            lines.append("")
            return

        elif tag_name == "ol":
            for idx, li in enumerate(node.find_all("li", recursive=False), start=1):
                li_text = self._inline_markdown(li)
                if li_text:
                    lines.append(f"{prefix}{idx}. {li_text}")
            lines.append("")
            return

        # Tables
        elif tag_name == "table":
            table_md = self._render_table(node)
            if table_md:
                lines.append("")
                lines.append(table_md)
                lines.append("")
            return

        # Division / Section / Article / General Container
        elif tag_name in {"div", "section", "article", "main"}:
            for child in node.children:
                self._traverse_node(child, lines, prefix)
            return

        # Fallback for other tags
        for child in node.children:
            self._traverse_node(child, lines, prefix)

    def _inline_markdown(self, element: Tag, is_root: bool = True) -> str:
        """Convert inline tags (a, strong, em, code, span) inside an element into Markdown string."""
        parts: list[str] = []
        for child in element.children:
            if isinstance(child, NavigableString):
                parts.append(str(child))
            elif isinstance(child, Tag):
                c_name = child.name.lower()
                c_text = child.get_text()
                if c_name in {"strong", "b"}:
                    parts.append(f"**{c_text.strip()}**")
                elif c_name in {"em", "i"}:
                    parts.append(f"*{c_text.strip()}*")
                elif c_name == "code":
                    parts.append(f"`{c_text.strip()}`")
                elif c_name == "a":
                    href = child.get("href", "")
                    if href and not href.startswith("javascript:"):
                        parts.append(f"[{c_text.strip()}]({href.strip()})")
                    else:
                        parts.append(c_text)
                else:
                    parts.append(self._inline_markdown(child, is_root=False))
        result = "".join(parts)
        if is_root:
            return re.sub(r"[ \t]+", " ", result).strip()
        return result

    def _render_table(self, table_tag: Tag) -> Optional[str]:
        """Convert an HTML table to a clean Markdown table."""
        rows = table_tag.find_all("tr")
        if not rows:
            return None

        table_data: list[list[str]] = []
        for row in rows:
            cols = row.find_all(["th", "td"])
            col_texts = [re.sub(r"\s+", " ", col.get_text()).strip() for col in cols]
            if col_texts:
                table_data.append(col_texts)

        if not table_data:
            return None

        max_cols = max(len(r) for r in table_data)
        # Normalize row lengths
        for r in table_data:
            while len(r) < max_cols:
                r.append("")

        header = table_data[0]
        separator = ["---"] * max_cols
        data_rows = table_data[1:]

        md_rows = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join(separator) + " |",
        ]
        for row in data_rows[:30]:  # Limit table rows to 30
            md_rows.append("| " + " | ".join(row) + " |")

        return "\n".join(md_rows)


html_converter = HTMLToMarkdownConverter()

"""Zero-cost local DuckDuckGo Web Search Tool implementation with untrusted content isolation."""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from app.core.logging import logger

def sanitize_untrusted_snippet(text: str) -> str:
    """Sanitize retrieved web content to isolate untrusted text and mitigate prompt injection."""
    from app.core.sanitization import prompt_sanitizer
    return prompt_sanitizer.wrap_untrusted_envelope(text, source_type="duckduckgo_search")


async def execute_web_search(
    query: str,
    max_results: int = 5,
    timeout_seconds: float = 15.0,
) -> Dict[str, Any]:
    """Execute zero-cost DuckDuckGo search and normalize results into structured schema."""
    if not query or not query.strip():
        return {
            "query": query,
            "total_results": 0,
            "results": [],
            "status": "empty_query",
        }

    cleaned_query = query.strip()
    limit = min(max(1, max_results), 10)
    retrieved_at = datetime.now(timezone.utc).isoformat()

    def _sync_search() -> List[Dict[str, Any]]:
        try:
            try:
                from duckduckgo_search import DDGS
            except ImportError:
                from ddgs import DDGS
        except ImportError:
            logger.warning("duckduckgo_search package is not available")
            return []
        try:
            with DDGS() as ddgs:
                raw_results = list(ddgs.text(keywords=cleaned_query, max_results=limit))
                return raw_results
        except Exception as e:
            logger.error(f"DuckDuckGo search error for query '{cleaned_query}': {e}")
            raise


    try:
        raw_items = await asyncio.wait_for(
            asyncio.to_thread(_sync_search),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        logger.warning(f"DuckDuckGo search timed out after {timeout_seconds}s for query '{cleaned_query}'")
        return {
            "query": cleaned_query,
            "total_results": 0,
            "results": [],
            "status": "timeout",
            "retrieved_at": retrieved_at,
        }
    except Exception as e:
        logger.warning(f"DuckDuckGo search failed: {e}")
        return {
            "query": cleaned_query,
            "total_results": 0,
            "results": [],
            "status": f"error: {str(e)}",
            "retrieved_at": retrieved_at,
        }

    normalized: List[Dict[str, Any]] = []
    for idx, item in enumerate(raw_items, start=1):
        title = item.get("title", "Untitled")
        url = item.get("href", item.get("url", ""))
        raw_snippet = item.get("body", item.get("snippet", ""))
        snippet = sanitize_untrusted_snippet(raw_snippet)

        normalized.append(
            {
                "rank": idx,
                "title": title,
                "url": url,
                "snippet": snippet,
                "source": "duckduckgo",
                "retrieved_at": retrieved_at,
                "is_untrusted_content": True,
            }
        )

    return {
        "query": cleaned_query,
        "total_results": len(normalized),
        "results": normalized,
        "status": "success",
        "retrieved_at": retrieved_at,
    }

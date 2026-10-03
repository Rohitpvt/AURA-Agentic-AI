"""Local Playwright Headless Web Extraction Tool with strict SSRF, redirect, and resource governance."""

from __future__ import annotations

import asyncio
import time

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from urllib.parse import urlparse

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page, Request, Response, Route

from app.core.errors import AuthorizationError, ValidationError

from app.core.logging import logger
from app.core.network import ssrf_guard
from app.services.tools.browser_manager import browser_manager
from app.services.tools.html_cleaner import html_converter

MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_REDIRECTS = 10
NAVIGATION_TIMEOUT_MS = 25000  # 25 seconds
ALLOWED_RESOURCE_TYPES = {"document", "script", "stylesheet", "xhr", "fetch", "ping"}
SUPPORTED_CONTENT_TYPES = {"text/html", "application/xhtml+xml", "text/plain"}


async def execute_web_extract(
    url: str,
    extract_mode: str = "markdown",
    max_length: int = 8000,
    workspace_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Execute bounded, local, headless web extraction using Playwright Chromium with multi-layer SSRF defense."""
    start_time = time.perf_counter()
    clamped_length = min(max(500, max_length), 20000)
    security_flags: List[str] = ["isolated_browser_context", "downloads_disabled", "service_workers_blocked"]

    # 1. Emergency Kill Switch Verification
    from app.services.kill_switch import kill_switch
    if kill_switch.is_active(workspace_id):
        logger.warning(f"WebExtract: Aborted execution - Emergency Kill Switch is active for workspace {workspace_id}")
        return {
            "source_url": url,
            "final_url": url,
            "title": "Extraction Suspended",
            "content": "[ABORTED: Emergency Kill Switch is active in this workspace. Extraction prohibited.]",
            "content_type": "text/plain",
            "extraction_time_ms": 0.0,
            "redirect_count": 0,
            "is_untrusted_content": True,
            "security_flags": security_flags + ["kill_switch_active"],
            "truncated": False,
            "status": "error",
            "error": "Emergency Kill Switch is active. Web extraction suspended.",
        }

    # 2. Pre-navigation SSRF Validation (Layer 1)
    try:
        ssrf_guard.validate_url(url)
    except (ValidationError, AuthorizationError) as e:
        logger.warning(f"WebExtract: SSRF guard rejected initial URL '{url}': {e}")
        return {
            "source_url": url,
            "final_url": url,
            "title": "Blocked by Security Policy",
            "content": f"[REJECTED: Destination address or URL scheme violates SSRF policy: {e}]",
            "content_type": "text/plain",
            "extraction_time_ms": round((time.perf_counter() - start_time) * 1000.0, 2),
            "redirect_count": 0,
            "is_untrusted_content": True,
            "security_flags": security_flags + ["ssrf_blocked"],
            "truncated": False,
            "status": "error",
            "error": f"SSRF Security Violation: {str(e)}",
        }

    # 3. Acquire Concurrency Semaphore (Cap at 2 concurrent extractions)
    context: Optional[BrowserContext] = None
    page: Optional[Page] = None
    redirect_urls: List[str] = []
    response_content_type = "text/html"
    blocked_resources_count = 0

    try:
        async with browser_manager.semaphore:
            # 4. Create Isolated BrowserContext
            context = await browser_manager.create_isolated_context()

            # 5. Intercept and govern all subresource requests (Layer 2)
            async def _route_handler(route: Route) -> None:
                nonlocal blocked_resources_count
                req = route.request
                res_type = req.resource_type

                # A. Resource-Type Policy Enforcement
                if res_type not in ALLOWED_RESOURCE_TYPES:
                    blocked_resources_count += 1
                    await route.abort("blockedbyclient")
                    return

                # B. Subresource SSRF Validation
                try:
                    ssrf_guard.validate_url(req.url)
                    await route.continue_()
                except Exception:
                    blocked_resources_count += 1
                    await route.abort("accessdenied")

            await context.route("**/*", _route_handler)

            # 6. Create Page and Configure Handlers
            page = await context.new_page()
            page.set_default_navigation_timeout(NAVIGATION_TIMEOUT_MS)
            page.set_default_timeout(NAVIGATION_TIMEOUT_MS)

            # Block popups and extra tabs
            page.on("popup", lambda p: asyncio.create_task(p.close()))

            # 7. Navigation Redirect Validation (Layer 3)
            def _handle_response(resp: Response) -> None:
                if 300 <= resp.status < 400:
                    location = resp.headers.get("location")
                    if location:
                        # Construct absolute URL if relative
                        if not location.startswith("http://") and not location.startswith("https://"):
                            parsed_orig = urlparse(resp.url)
                            base = f"{parsed_orig.scheme}://{parsed_orig.netloc}"
                            location = f"{base}/{location.lstrip('/')}"
                        redirect_urls.append(location)
                        # Validate redirect destination immediately
                        try:
                            ssrf_guard.validate_url(location)
                        except Exception as e:
                            logger.error(f"WebExtract: SSRF guard intercepted prohibited redirect to '{location}': {e}")
                            raise AuthorizationError(f"Prohibited redirect target: {location}")

            page.on("response", _handle_response)

            # 8. Execute Navigation
            try:
                nav_response = await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=NAVIGATION_TIMEOUT_MS,
                )
            except Exception as e:
                if "Prohibited redirect" in str(e) or "SSRF" in str(e):
                    raise AuthorizationError(f"Navigation aborted due to SSRF redirect policy: {e}")
                raise

            # Small rendering buffer for client-side hydration (500ms)
            await asyncio.sleep(0.5)

            # Check redirect count limit
            if len(redirect_urls) > MAX_REDIRECTS:
                raise ValidationError(f"Redirect limit exceeded ({len(redirect_urls)} > {MAX_REDIRECTS})")

            # 9. Response Validation (Content-Length and Content-Type)
            if nav_response:
                headers = nav_response.headers
                content_len = headers.get("content-length")
                if content_len and content_len.isdigit():
                    if int(content_len) > MAX_RESPONSE_BYTES:
                        raise ValidationError(f"Response size ({content_len} bytes) exceeds 5 MB limit")

                raw_ct = headers.get("content-type", "text/html").lower()
                response_content_type = raw_ct.split(";")[0].strip()
                if response_content_type not in SUPPORTED_CONTENT_TYPES:
                    raise ValidationError(f"Unsupported content type '{response_content_type}'. Only HTML and text are supported.")

            # 10. Extract Title and Content
            raw_html = await page.content()
            final_url = page.url

            # 11. Clean DOM and Convert
            cleaned_soup = html_converter.clean_html(raw_html, max_html_bytes=MAX_RESPONSE_BYTES)
            page_title = html_converter.extract_title(cleaned_soup)

            if extract_mode == "raw_html":
                extracted_content = str(cleaned_soup)[:clamped_length]
            elif extract_mode == "text":
                extracted_content = cleaned_soup.get_text(separator="\n", strip=True)[:clamped_length]
            else:  # markdown
                extracted_content = html_converter.convert_to_markdown(cleaned_soup, max_chars=clamped_length)

            from app.core.sanitization import prompt_sanitizer
            cleaned_content = prompt_sanitizer.clean_unicode_and_controls(extracted_content)
            escaped_content = prompt_sanitizer.escape_delimiters(cleaned_content)
            has_inj, inj_flags = prompt_sanitizer.detect_injection_signatures(escaped_content)
            if has_inj:
                security_flags.extend(inj_flags)

            duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            is_truncated = len(extracted_content) >= clamped_length

            if blocked_resources_count > 0:
                security_flags.append(f"blocked_subresources_{blocked_resources_count}")

            return {
                "source_url": url,
                "final_url": final_url,
                "title": page_title,
                "content": escaped_content,
                "content_type": response_content_type,
                "extraction_time_ms": duration_ms,
                "redirect_count": len(redirect_urls),
                "is_untrusted_content": True,
                "security_flags": security_flags,
                "truncated": is_truncated,
                "status": "success",
            }

    except AuthorizationError as e:
        duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        logger.warning(f"WebExtract: Authorization/SSRF failure for '{url}': {e}")
        return {
            "source_url": url,
            "final_url": url,
            "title": "Blocked by Security Policy",
            "content": f"[SECURITY REJECTION: {str(e)}]",
            "content_type": "text/plain",
            "extraction_time_ms": duration_ms,
            "redirect_count": len(redirect_urls),
            "is_untrusted_content": True,
            "security_flags": security_flags + ["ssrf_violation"],
            "truncated": False,
            "status": "error",
            "error": f"Security violation: {str(e)}",
        }
    except ValidationError as e:
        duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        logger.warning(f"WebExtract: Validation error for '{url}': {e}")
        return {
            "source_url": url,
            "final_url": url,
            "title": "Validation Error",
            "content": f"[VALIDATION ERROR: {str(e)}]",
            "content_type": "text/plain",
            "extraction_time_ms": duration_ms,
            "redirect_count": len(redirect_urls),
            "is_untrusted_content": True,
            "security_flags": security_flags + ["validation_error"],
            "truncated": False,
            "status": "error",
            "error": str(e),
        }
    except asyncio.TimeoutError:
        duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        logger.warning(f"WebExtract: Navigation timed out after {NAVIGATION_TIMEOUT_MS/1000}s for '{url}'")
        return {
            "source_url": url,
            "final_url": url,
            "title": "Navigation Timeout",
            "content": f"[TIMEOUT: Page navigation timed out after {NAVIGATION_TIMEOUT_MS/1000} seconds]",
            "content_type": "text/plain",
            "extraction_time_ms": duration_ms,
            "redirect_count": len(redirect_urls),
            "is_untrusted_content": True,
            "security_flags": security_flags + ["timeout"],
            "truncated": False,
            "status": "error",
            "error": f"Extraction timed out after {NAVIGATION_TIMEOUT_MS/1000}s",
        }
    except Exception as e:
        duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        logger.error(f"WebExtract: Extraction failed for '{url}': {e}")
        return {
            "source_url": url,
            "final_url": url,
            "title": "Extraction Failed",
            "content": f"[EXTRACTION FAILED: {str(e)}]",
            "content_type": "text/plain",
            "extraction_time_ms": duration_ms,
            "redirect_count": len(redirect_urls),
            "is_untrusted_content": True,
            "security_flags": security_flags + ["internal_error"],
            "truncated": False,
            "status": "error",
            "error": str(e),
        }
    finally:
        # Guaranteed cleanup of page and isolated context
        if page:
            try:
                await page.close()
            except Exception:
                pass
        if context:
            try:
                await context.close()
            except Exception:
                pass

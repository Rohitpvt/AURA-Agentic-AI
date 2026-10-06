"""Tool Registry and Execution Boundary Service."""

import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.errors import AuthorizationError, EntityNotFoundError, ValidationError
from app.core.logging import logger
from app.core.security import compute_sha256_hash, sign_approval_payload
from app.db.models.audit import AuditLog
from app.db.models.tool import Tool, ToolPermission
from app.schemas.tool import ToolExecutionRequest, ToolExecutionResponse, ToolRegisterRequest, ToolResponse
from app.services.tools.file_tools import (
    execute_analyze_spreadsheet,
    execute_codebase_analysis,
    execute_inspect_file,
    execute_search_files,
    execute_summarize_document,
)
from app.services.tools.vision_tools import (
    execute_image_inspect,
    execute_inspect_active_window,
    execute_inspect_camera_frame,
    execute_inspect_current_screen,
    execute_query_visible_text,
)
from app.services.tools.os_tools import (
    execute_click_mouse,
    execute_clipboard_read,
    execute_clipboard_write,
    execute_get_display_brightness,
    execute_get_hardware_capabilities,
    execute_get_system_telemetry,
    execute_get_system_volume,
    execute_inspect_processes,
    execute_keyboard_shortcut,
    execute_launch_application,
    execute_move_mouse,
    execute_press_key,
    execute_set_display_brightness,
    execute_set_system_volume,
    execute_terminate_process,
    execute_type_text,
)
from app.services.tools.web_extract import execute_web_extract
from app.services.tools.web_search import execute_web_search
from app.services.tools.browser_tools import (
    execute_browser_navigate,
    execute_browser_get_page_state,
    execute_browser_screenshot,
    execute_browser_click,
    execute_browser_type,
    execute_browser_select,
    execute_browser_scroll,
    execute_browser_press_key,
    execute_browser_tab_manage,
    execute_browser_list_credentials,
    execute_browser_inject_credential,
    execute_browser_save_session,
    execute_browser_restore_session,
)


# Built-in tool definitions and Python callables
BUILTIN_TOOLS: Dict[str, Dict[str, Any]] = {
    "web_search": {
        "name": "web_search",
        "display_name": "Web Search (DuckDuckGo)",
        "description": "Perform zero-cost web search using DuckDuckGo to find real-time information, documentation, and news.",
        "category": "search",
        "risk_level": "low",
        "timeout_seconds": 20,
        "rate_limit_per_minute": 60,
        "requires_approval": False,
        "is_allowed_in_background": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search terms or query string"},
                "max_results": {"type": "integer", "description": "Number of results (1-10)", "default": 5},
            },
            "required": ["query"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "total_results": {"type": "integer"},
                "results": {"type": "array"},
                "status": {"type": "string"},
            },
        },
        "handler": execute_web_search,
    },
    "web_extract": {
        "name": "web_extract",
        "display_name": "Headless Web Extraction (Playwright)",
        "description": "Extract readable content and structured Markdown from a public web page using a local sandboxed headless browser.",
        "category": "web",
        "risk_level": "medium",
        "timeout_seconds": 30,
        "rate_limit_per_minute": 30,
        "requires_approval": False,
        "is_allowed_in_background": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The HTTP or HTTPS URL to extract content from"},
                "extract_mode": {
                    "type": "string",
                    "enum": ["markdown", "text", "raw_html"],
                    "default": "markdown",
                    "description": "Extraction format mode (markdown, text, or raw_html)",
                },
                "max_length": {
                    "type": "integer",
                    "default": 8000,
                    "description": "Maximum character length of returned content (max 20000)",
                },
            },
            "required": ["url"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "source_url": {"type": "string"},
                "final_url": {"type": "string"},
                "title": {"type": "string"},
                "content": {"type": "string"},
                "content_type": {"type": "string"},
                "extraction_time_ms": {"type": "number"},
                "redirect_count": {"type": "integer"},
                "is_untrusted_content": {"type": "boolean"},
                "security_flags": {"type": "array"},
                "truncated": {"type": "boolean"},
                "status": {"type": "string"},
            },
        },
        "handler": execute_web_extract,
    },
    "inspect_file": {
        "name": "inspect_file",
        "display_name": "Inspect Workspace File",
        "description": "Inspect workspace file metadata, format dimensions, token estimates, and vector index status.",
        "category": "file_intelligence",
        "risk_level": "low",
        "timeout_seconds": 15,
        "rate_limit_per_minute": 60,
        "requires_approval": False,
        "is_allowed_in_background": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "Target workspace file UUID"},
            },
            "required": ["file_id"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string"},
                "filename": {"type": "string"},
                "mime_type": {"type": "string"},
                "size_bytes": {"type": "integer"},
                "status": {"type": "string"},
                "vector_status": {"type": "string"},
                "chunks_count": {"type": "integer"},
            },
        },
        "handler": execute_inspect_file,
    },
    "summarize_document": {
        "name": "summarize_document",
        "display_name": "Summarize Document",
        "description": "Produce a structured executive summary with section and page citations for a workspace document.",
        "category": "file_intelligence",
        "risk_level": "low",
        "timeout_seconds": 30,
        "rate_limit_per_minute": 20,
        "requires_approval": False,
        "is_allowed_in_background": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "Target workspace file UUID"},
                "max_tokens": {"type": "integer", "default": 1024, "description": "Target summary length"},
                "focus_areas": {"type": "array", "items": {"type": "string"}, "description": "Topics to focus on"},
            },
            "required": ["file_id"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string"},
                "title": {"type": "string"},
                "executive_summary": {"type": "string"},
                "key_takeaways": {"type": "array"},
                "citations": {"type": "array"},
                "status": {"type": "string"},
            },
        },
        "handler": execute_summarize_document,
    },
    "analyze_spreadsheet": {
        "name": "analyze_spreadsheet",
        "display_name": "Analyze Spreadsheet",
        "description": "Inspect structured tabular sheets, headers, sample rows, and formula counts safely with zero formula execution.",
        "category": "file_intelligence",
        "risk_level": "low",
        "timeout_seconds": 30,
        "rate_limit_per_minute": 30,
        "requires_approval": False,
        "is_allowed_in_background": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "Target spreadsheet file UUID"},
                "sheet_name": {"type": "string", "description": "Specific sheet name to analyze"},
                "sample_row_limit": {"type": "integer", "default": 25, "description": "Max rows to sample"},
            },
            "required": ["file_id"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string"},
                "total_sheets": {"type": "integer"},
                "sheets": {"type": "array"},
                "has_macros": {"type": "boolean"},
                "summary": {"type": "object"},
            },
        },
        "handler": execute_analyze_spreadsheet,
    },
    "codebase_analysis": {
        "name": "codebase_analysis",
        "display_name": "Codebase Repository Analysis",
        "description": "Explore repository directory tree, dependencies, AST classes, functions, and symbols from source code archives.",
        "category": "file_intelligence",
        "risk_level": "low",
        "timeout_seconds": 30,
        "rate_limit_per_minute": 30,
        "requires_approval": False,
        "is_allowed_in_background": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "Target codebase archive file UUID"},
                "focus_paths": {"type": "array", "items": {"type": "string"}, "description": "Path prefixes to filter"},
                "symbol_query": {"type": "string", "description": "Symbol name to query"},
            },
            "required": ["file_id"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string"},
                "total_files": {"type": "integer"},
                "languages": {"type": "object"},
                "file_tree": {"type": "array"},
                "symbols": {"type": "array"},
                "dependencies": {"type": "array"},
            },
        },
        "handler": execute_codebase_analysis,
    },
    "search_files": {
        "name": "search_files",
        "display_name": "Search Files & Documents",
        "description": "Execute workspace-scoped hybrid dense semantic + lexical vector search across indexed document chunks.",
        "category": "file_intelligence",
        "risk_level": "low",
        "timeout_seconds": 20,
        "rate_limit_per_minute": 60,
        "requires_approval": False,
        "is_allowed_in_background": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search terms or question"},
                "file_id": {"type": "string", "description": "Optional file ID filter"},
                "top_k": {"type": "integer", "default": 5, "description": "Number of results to return"},
                "min_similarity": {"type": "number", "default": 0.3, "description": "Similarity threshold floor"},
            },
            "required": ["query"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "total_candidates": {"type": "integer"},
                "returned_count": {"type": "integer"},
                "results": {"type": "array"},
            },
        },
        "handler": execute_search_files,
    },
    "image_inspect": {
        "name": "image_inspect",
        "display_name": "Inspect Image (Local VLM & OCR)",
        "description": "Inspect a static workspace image using local VLM and OCR to extract detailed visual descriptions, object relationships, and visible text into an untrusted multimodal envelope.",
        "category": "vision",
        "risk_level": "low",
        "timeout_seconds": 15,
        "rate_limit_per_minute": 30,
        "requires_approval": False,
        "is_allowed_in_background": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "Target workspace image file UUID"},
                "prompt": {"type": "string", "description": "Optional question or visual focus prompt"},
                "detail_level": {
                    "type": "string",
                    "enum": ["standard", "high", "low"],
                    "default": "standard",
                    "description": "Visual inspection detail level",
                },
                "model": {"type": "string", "description": "Optional model override (e.g. moondream, qwen2-vl:2b)"},
            },
            "required": ["file_id"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string"},
                "filename": {"type": "string"},
                "format": {"type": "string"},
                "original_dimensions": {"type": "object"},
                "processed_dimensions": {"type": "object"},
                "size_bytes": {"type": "integer"},
                "model_used": {"type": "string"},
                "processing_time_ms": {"type": "number"},
                "description": {"type": "string"},
                "untrusted_content_envelope": {"type": "string"},
                "is_untrusted_content": {"type": "boolean"},
                "security_flags": {"type": "array"},
                "ocr_available": {"type": "boolean"},
                "status": {"type": "string"},
            },
        },
        "handler": execute_image_inspect,
    },
    "inspect_current_screen": {
        "name": "inspect_current_screen",
        "display_name": "Inspect Current Screen (Local VLM)",
        "description": "Perform a read-only snapshot inspection of the current display using local VLM and OCR context.",
        "category": "vision",
        "risk_level": "low",
        "timeout_seconds": 30,
        "rate_limit_per_minute": 12,
        "requires_approval": False,
        "is_allowed_in_background": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "monitor_id": {"type": "integer", "default": 1, "description": "Monitor index to capture (1..N)"},
                "prompt": {"type": "string", "description": "Optional focus query for screen analysis"},
                "detail_level": {
                    "type": "string",
                    "enum": ["standard", "high", "low"],
                    "default": "standard",
                    "description": "Analysis granularity",
                },
                "model": {"type": "string", "description": "Optional local VLM model name"},
                "include_ocr_context": {"type": "boolean", "default": True, "description": "Whether to augment VLM with OCR text"},
            },
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "observation_id": {"type": "string"},
                "source_type": {"type": "string"},
                "source_id": {"type": "string"},
                "summary": {"type": "string"},
                "coordinate_space": {"type": "string"},
                "confidence": {"type": "number"},
                "model": {"type": "string"},
                "device": {"type": "string"},
                "processing_duration_ms": {"type": "number"},
                "degraded": {"type": "boolean"},
                "untrusted_content_envelope": {"type": "string"},
                "is_untrusted_content": {"type": "boolean"},
                "status": {"type": "string"},
            },
        },
        "handler": execute_inspect_current_screen,
    },
    "inspect_active_window": {
        "name": "inspect_active_window",
        "display_name": "Inspect Active Window (Local VLM)",
        "description": "Inspect foreground active window bounds, process, title, and visual content via local VLM.",
        "category": "vision",
        "risk_level": "low",
        "timeout_seconds": 30,
        "rate_limit_per_minute": 12,
        "requires_approval": False,
        "is_allowed_in_background": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Optional focus question for window content"},
                "detail_level": {
                    "type": "string",
                    "enum": ["standard", "high", "low"],
                    "default": "standard",
                    "description": "Analysis granularity",
                },
                "model": {"type": "string", "description": "Optional local VLM model name"},
                "include_ocr_context": {"type": "boolean", "default": True, "description": "Whether to augment VLM with OCR text"},
            },
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "observation_id": {"type": "string"},
                "source_type": {"type": "string"},
                "source_id": {"type": "string"},
                "summary": {"type": "string"},
                "window_info": {"type": "object"},
                "coordinate_space": {"type": "string"},
                "confidence": {"type": "number"},
                "model": {"type": "string"},
                "processing_duration_ms": {"type": "number"},
                "degraded": {"type": "boolean"},
                "untrusted_content_envelope": {"type": "string"},
                "is_untrusted_content": {"type": "boolean"},
                "status": {"type": "string"},
            },
        },
        "handler": execute_inspect_active_window,
    },
    "inspect_camera_frame": {
        "name": "inspect_camera_frame",
        "display_name": "Inspect Live Camera Frame (Local VLM)",
        "description": "Inspect the latest permitted camera frame from the depth-1 camera buffer via local VLM.",
        "category": "vision",
        "risk_level": "low",
        "timeout_seconds": 30,
        "rate_limit_per_minute": 12,
        "requires_approval": False,
        "is_allowed_in_background": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Optional focus question for camera frame"},
                "detail_level": {
                    "type": "string",
                    "enum": ["standard", "high", "low"],
                    "default": "standard",
                    "description": "Analysis granularity",
                },
                "model": {"type": "string", "description": "Optional local VLM model name"},
            },
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "observation_id": {"type": "string"},
                "source_type": {"type": "string"},
                "source_id": {"type": "string"},
                "summary": {"type": "string"},
                "coordinate_space": {"type": "string"},
                "confidence": {"type": "number"},
                "model": {"type": "string"},
                "processing_duration_ms": {"type": "number"},
                "degraded": {"type": "boolean"},
                "untrusted_content_envelope": {"type": "string"},
                "is_untrusted_content": {"type": "boolean"},
                "status": {"type": "string"},
            },
        },
        "handler": execute_inspect_camera_frame,
    },
    "query_visible_text": {
        "name": "query_visible_text",
        "display_name": "Query Visible Screen Text (Continuous OCR)",
        "description": "Query structured local OCR text lines and bounding geometry across screen regions.",
        "category": "vision",
        "risk_level": "low",
        "timeout_seconds": 15,
        "rate_limit_per_minute": 60,
        "requires_approval": False,
        "is_allowed_in_background": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Text substring or pattern to search for"},
                "min_confidence": {"type": "number", "default": 0.0, "description": "Confidence score filter floor (0.0 .. 1.0)"},
                "case_sensitive": {"type": "boolean", "default": False, "description": "Whether query matching is case-sensitive"},
                "monitor_id": {"type": "integer", "default": 1, "description": "Monitor index to query OCR from"},
            },
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "total_regions": {"type": "integer"},
                "matched_regions_count": {"type": "integer"},
                "matched_text": {"type": "string"},
                "regions": {"type": "array"},
                "full_text": {"type": "string"},
                "coordinate_space": {"type": "string"},
                "degraded": {"type": "boolean"},
                "untrusted_content_envelope": {"type": "string"},
                "is_untrusted_content": {"type": "boolean"},
                "status": {"type": "string"},
            },
        },
        "handler": execute_query_visible_text,
    },
    "launch_application": {
        "name": "launch_application",
        "display_name": "Launch Application (Governed OS)",
        "description": "Launch an allowlisted Windows application (e.g. notepad, calc, mspaint, write) with validated arguments strictly under deterministic policy governance.",
        "category": "os_control",
        "risk_level": "high",
        "timeout_seconds": 5,
        "rate_limit_per_minute": 5,
        "requires_approval": True,
        "is_allowed_in_background": False,
        "input_schema": {
            "type": "object",
            "properties": {
                "application_id": {
                    "type": "string",
                    "description": "Allowlisted application identifier (notepad, calc, mspaint, write)",
                },
                "arguments": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of string arguments for the application",
                },
                "working_directory": {
                    "type": "string",
                    "description": "Optional working directory path (must be within authorized workspace)",
                },
            },
            "required": ["application_id"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "application_id": {"type": "string"},
                "display_name": {"type": "string"},
                "executable_path": {"type": "string"},
                "pid": {"type": "integer"},
                "create_time": {"type": "number"},
                "start_timestamp": {"type": "number"},
                "arguments": {"type": "array"},
                "working_directory": {"type": "string"},
            },
        },
        "handler": execute_launch_application,
    },
    "inspect_processes": {
        "name": "inspect_processes",
        "display_name": "Inspect Processes (Read-Only)",
        "description": "Query running processes, PIDs, names, creation times, CPU, and memory metrics safely without leaking environment secrets.",
        "category": "os_control",
        "risk_level": "low",
        "timeout_seconds": 5,
        "rate_limit_per_minute": 60,
        "requires_approval": False,
        "is_allowed_in_background": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "filter_name": {"type": "string", "description": "Optional process name substring to filter by"},
                "pid": {"type": "integer", "description": "Optional specific PID to query"},
                "limit": {"type": "integer", "default": 50, "description": "Maximum number of processes to return (1-100)"},
            },
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "total_processes": {"type": "integer"},
                "processes": {"type": "array"},
            },
        },
        "handler": execute_inspect_processes,
    },
    "terminate_process": {
        "name": "terminate_process",
        "display_name": "Terminate Process (Governed OS)",
        "description": "Terminate a validated non-system process with strict PID + creation_time identity verification to prevent PID reuse race conditions.",
        "category": "os_control",
        "risk_level": "high",
        "timeout_seconds": 5,
        "rate_limit_per_minute": 5,
        "requires_approval": True,
        "is_allowed_in_background": False,
        "input_schema": {
            "type": "object",
            "properties": {
                "pid": {"type": "integer", "description": "Process ID to terminate"},
                "expected_creation_time": {"type": "number", "description": "Exact expected process creation timestamp from prior inspection"},
                "expected_name": {"type": "string", "description": "Expected process executable name (e.g. notepad.exe)"},
                "reason": {"type": "string", "description": "Reason for process termination"},
            },
            "required": ["pid", "expected_creation_time", "expected_name"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "pid": {"type": "integer"},
                "process_name": {"type": "string"},
                "create_time": {"type": "number"},
                "termination_requested_at": {"type": "number"},
                "termination_completed_at": {"type": "number"},
                "outcome": {"type": "string"},
            },
        },
        "handler": execute_terminate_process,
    },
    "move_mouse": {
        "name": "move_mouse",
        "display_name": "Move Mouse Cursor (Governed OS)",
        "description": "Move the mouse cursor smoothly to bounded desktop coordinates within authorized monitor bounds.",
        "category": "os_control",
        "risk_level": "low",
        "timeout_seconds": 5,
        "rate_limit_per_minute": 60,
        "requires_approval": False,
        "is_allowed_in_background": False,
        "input_schema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "Target X desktop coordinate"},
                "y": {"type": "integer", "description": "Target Y desktop coordinate"},
                "duration": {"type": "number", "default": 0.2, "description": "Movement duration in seconds (0.1 to 2.0)"},
                "monitor_id": {"type": "integer", "default": 1, "description": "Target monitor ID index"},
                "coordinate_space": {"type": "string", "default": "screen_desktop", "description": "Coordinate space (screen_desktop or captured_frame)"},
                "observation_timestamp": {"type": "number", "description": "Optional timestamp of visual observation for freshness validation"},
                "expected_window_title": {"type": "string", "description": "Optional expected active window title"},
            },
            "required": ["x", "y"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "action_id": {"type": "string"},
                "action_type": {"type": "string"},
                "outcome": {"type": "string"},
                "monitor_id": {"type": "integer"},
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "duration": {"type": "number"},
            },
        },
        "handler": execute_move_mouse,
    },
    "click_mouse": {
        "name": "click_mouse",
        "display_name": "Click Mouse (Governed OS)",
        "description": "Execute a governed single or multi-click (left, right, middle) at validated desktop coordinates.",
        "category": "os_control",
        "risk_level": "medium",
        "timeout_seconds": 5,
        "rate_limit_per_minute": 30,
        "requires_approval": False,
        "is_allowed_in_background": False,
        "input_schema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "Target X desktop coordinate"},
                "y": {"type": "integer", "description": "Target Y desktop coordinate"},
                "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left", "description": "Mouse button to click"},
                "clicks": {"type": "integer", "default": 1, "description": "Number of clicks (1 to 3)"},
                "monitor_id": {"type": "integer", "default": 1, "description": "Target monitor ID index"},
                "coordinate_space": {"type": "string", "default": "screen_desktop", "description": "Coordinate space (screen_desktop or captured_frame)"},
                "observation_timestamp": {"type": "number", "description": "Optional timestamp of visual observation for freshness validation"},
                "expected_window_title": {"type": "string", "description": "Optional expected active window title"},
            },
            "required": ["x", "y"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "action_id": {"type": "string"},
                "action_type": {"type": "string"},
                "outcome": {"type": "string"},
                "monitor_id": {"type": "integer"},
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "button": {"type": "string"},
                "clicks": {"type": "integer"},
            },
        },
        "handler": execute_click_mouse,
    },
    "type_text": {
        "name": "type_text",
        "display_name": "Type Text (Governed OS)",
        "description": "Type a bounded text string (max 256 chars) into the active window with strict privacy redaction.",
        "category": "os_control",
        "risk_level": "medium",
        "timeout_seconds": 5,
        "rate_limit_per_minute": 10,
        "requires_approval": False,
        "is_allowed_in_background": False,
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to type (max 256 characters, no control characters)"},
                "interval": {"type": "number", "default": 0.01, "description": "Interval between keystrokes in seconds"},
                "expected_window_title": {"type": "string", "description": "Optional expected active window title"},
            },
            "required": ["text"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "action_id": {"type": "string"},
                "action_type": {"type": "string"},
                "outcome": {"type": "string"},
                "typed_character_count": {"type": "integer"},
                "redacted": {"type": "boolean"},
            },
        },
        "handler": execute_type_text,
    },
    "press_key": {
        "name": "press_key",
        "display_name": "Press Key (Governed OS)",
        "description": "Press a single safe key (enter, tab, esc, backspace, arrows, etc.) from an explicit allowlist.",
        "category": "os_control",
        "risk_level": "low",
        "timeout_seconds": 5,
        "rate_limit_per_minute": 30,
        "requires_approval": False,
        "is_allowed_in_background": False,
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Safe key identifier to press"},
                "presses": {"type": "integer", "default": 1, "description": "Number of times to press the key (1 to 5)"},
                "expected_window_title": {"type": "string", "description": "Optional expected active window title"},
            },
            "required": ["key"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "action_id": {"type": "string"},
                "action_type": {"type": "string"},
                "outcome": {"type": "string"},
                "key": {"type": "string"},
                "presses": {"type": "integer"},
            },
        },
        "handler": execute_press_key,
    },
    "keyboard_shortcut": {
        "name": "keyboard_shortcut",
        "display_name": "Keyboard Shortcut (Governed OS)",
        "description": "Execute a safe keyboard shortcut (e.g. ctrl+c, ctrl+v, ctrl+z) from an explicit allowlist.",
        "category": "os_control",
        "risk_level": "medium",
        "timeout_seconds": 5,
        "rate_limit_per_minute": 10,
        "requires_approval": False,
        "is_allowed_in_background": False,
        "input_schema": {
            "type": "object",
            "properties": {
                "shortcut": {"type": "string", "description": "Safe shortcut string (e.g. 'ctrl+c', 'ctrl+v')"},
                "keys": {"type": "array", "items": {"type": "string"}, "description": "Optional list of shortcut keys"},
                "expected_window_title": {"type": "string", "description": "Optional expected active window title"},
            },
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "action_id": {"type": "string"},
                "action_type": {"type": "string"},
                "outcome": {"type": "string"},
                "shortcut": {"type": "string"},
            },
        },
        "handler": execute_keyboard_shortcut,
    },
    "get_system_telemetry": {
        "name": "get_system_telemetry",
        "display_name": "Get System Telemetry (Read-Only)",
        "description": "Query comprehensive local system metrics: CPU, RAM, Process RSS, GPU, VRAM, Storage, Battery, and Display Topology.",
        "category": "os_control",
        "risk_level": "low",
        "timeout_seconds": 5,
        "rate_limit_per_minute": 60,
        "requires_approval": False,
        "is_allowed_in_background": True,
        "input_schema": {
            "type": "object",
            "properties": {},
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "cpu": {"type": "object"},
                "ram": {"type": "object"},
                "storage": {"type": "object"},
                "battery": {"type": "object"},
                "gpu": {"type": "object"},
                "temperature": {"type": "object"},
                "displays": {"type": "object"},
            },
        },
        "handler": execute_get_system_telemetry,
    },
    "get_hardware_capabilities": {
        "name": "get_hardware_capabilities",
        "display_name": "Get Hardware Capabilities (Read-Only)",
        "description": "Inspect which hardware controls (volume, brightness, battery, GPU telemetry) are supported on this Windows host.",
        "category": "os_control",
        "risk_level": "low",
        "timeout_seconds": 5,
        "rate_limit_per_minute": 60,
        "requires_approval": False,
        "is_allowed_in_background": True,
        "input_schema": {
            "type": "object",
            "properties": {},
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "volume_supported": {"type": "boolean"},
                "brightness_supported": {"type": "boolean"},
                "display_count": {"type": "integer"},
                "displays": {"type": "array"},
                "battery_supported": {"type": "boolean"},
                "gpu_telemetry_supported": {"type": "boolean"},
                "temperature_supported": {"type": "boolean"},
            },
        },
        "handler": execute_get_hardware_capabilities,
    },
    "get_system_volume": {
        "name": "get_system_volume",
        "display_name": "Get System Volume (Read-Only)",
        "description": "Read the current master system audio volume percentage (0-100%) and mute state via Windows Core Audio.",
        "category": "os_control",
        "risk_level": "low",
        "timeout_seconds": 5,
        "rate_limit_per_minute": 60,
        "requires_approval": False,
        "is_allowed_in_background": True,
        "input_schema": {
            "type": "object",
            "properties": {},
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "volume_percent": {"type": "number"},
                "volume_scalar": {"type": "number"},
                "is_muted": {"type": "boolean"},
                "supported": {"type": "boolean"},
            },
        },
        "handler": execute_get_system_volume,
    },
    "set_system_volume": {
        "name": "set_system_volume",
        "display_name": "Set System Volume (Governed OS)",
        "description": "Adjust master system audio volume with bounded steps (max +/-10%) or toggle mute via Windows Core Audio.",
        "category": "os_control",
        "risk_level": "low",
        "timeout_seconds": 5,
        "rate_limit_per_minute": 10,
        "requires_approval": False,
        "is_allowed_in_background": False,
        "input_schema": {
            "type": "object",
            "properties": {
                "relative_step_percent": {
                    "type": "number",
                    "description": "Relative percentage volume step (strictly clamped between -10.0 and +10.0)",
                },
                "target_volume_percent": {
                    "type": "number",
                    "description": "Absolute target volume percentage (0.0 to 100.0, step clamped)",
                },
                "mute": {
                    "type": "boolean",
                    "description": "Optional mute state toggle (true = muted, false = unmuted)",
                },
            },
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "previous_volume_percent": {"type": "number"},
                "current_volume_percent": {"type": "number"},
                "is_muted": {"type": "boolean"},
                "delta_percent": {"type": "number"},
                "rollback_available": {"type": "boolean"},
            },
        },
        "handler": execute_set_system_volume,
    },
    "get_display_brightness": {
        "name": "get_display_brightness",
        "display_name": "Get Display Brightness (Read-Only)",
        "description": "Query the current brightness percentage for a target display monitor via Windows WMI / DDC-CI.",
        "category": "os_control",
        "risk_level": "low",
        "timeout_seconds": 5,
        "rate_limit_per_minute": 60,
        "requires_approval": False,
        "is_allowed_in_background": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "monitor_id": {
                    "type": "integer",
                    "default": 1,
                    "description": "Target monitor ID index (1-based)",
                },
            },
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "brightness_percent": {"type": "integer"},
                "monitor_id": {"type": "integer"},
                "supported": {"type": "boolean"},
            },
        },
        "handler": execute_get_display_brightness,
    },
    "set_display_brightness": {
        "name": "set_display_brightness",
        "display_name": "Set Display Brightness (Governed OS)",
        "description": "Adjust monitor brightness with bounded steps (max +/-10%) via Windows WMI / DDC-CI.",
        "category": "os_control",
        "risk_level": "low",
        "timeout_seconds": 5,
        "rate_limit_per_minute": 10,
        "requires_approval": False,
        "is_allowed_in_background": False,
        "input_schema": {
            "type": "object",
            "properties": {
                "monitor_id": {
                    "type": "integer",
                    "default": 1,
                    "description": "Target monitor ID index (1-based)",
                },
                "relative_step_percent": {
                    "type": "number",
                    "description": "Relative percentage brightness step (strictly clamped between -10.0 and +10.0)",
                },
                "target_brightness_percent": {
                    "type": "integer",
                    "description": "Absolute target brightness percentage (0 to 100)",
                },
            },
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "monitor_id": {"type": "integer"},
                "previous_brightness_percent": {"type": "integer"},
                "current_brightness_percent": {"type": "integer"},
                "delta_percent": {"type": "integer"},
                "rollback_available": {"type": "boolean"},
            },
        },
        "handler": execute_set_display_brightness,
    },
    "clipboard_read": {
        "name": "clipboard_read",
        "display_name": "Read Clipboard (Governed OS)",
        "description": "Read text from the host clipboard (bounded to 4096 chars) with automated secret scrubbing (API keys, JWTs). Never persisted.",
        "category": "os_control",
        "risk_level": "low",
        "timeout_seconds": 5,
        "rate_limit_per_minute": 30,
        "requires_approval": False,
        "is_allowed_in_background": True,
        "input_schema": {
            "type": "object",
            "properties": {},
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "text": {"type": "string"},
                "character_count": {"type": "integer"},
                "original_length": {"type": "integer"},
                "truncated": {"type": "boolean"},
                "redacted": {"type": "boolean"},
            },
        },
        "handler": execute_clipboard_read,
    },
    "clipboard_write": {
        "name": "clipboard_write",
        "display_name": "Write Clipboard (Governed OS)",
        "description": "Write bounded text (max 4096 chars) to the host clipboard with cryptographic HITL approval. Plaintext is never logged in audit.",
        "category": "os_control",
        "risk_level": "medium",
        "timeout_seconds": 5,
        "rate_limit_per_minute": 10,
        "requires_approval": False,
        "is_allowed_in_background": False,
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text payload to write to the clipboard (max 4096 chars, no NUL bytes)",
                },
            },
            "required": ["text"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "action": {"type": "string"},
                "character_count": {"type": "integer"},
                "byte_count": {"type": "integer"},
                "sha256_hash": {"type": "string"},
            },
        },
        "handler": execute_clipboard_write,
    },
    "browser_navigate": {
        "name": "browser_navigate",
        "display_name": "Browser Navigate",
        "description": "Navigate the sandboxed workspace browser to a verified URL with SSRF protection.",
        "category": "browser",
        "risk_level": "low",
        "timeout_seconds": 30,
        "rate_limit_per_minute": 30,
        "requires_approval": False,
        "is_allowed_in_background": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "HTTP or HTTPS URL to navigate to"},
                "tab_id": {"type": "string", "description": "Optional tab ID (defaults to active tab)"},
                "wait_until": {"type": "string", "description": "Wait condition (domcontentloaded, load, networkidle)", "default": "domcontentloaded"},
                "timeout_ms": {"type": "integer", "description": "Navigation timeout in milliseconds", "default": 25000},
            },
            "required": ["url"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "tab_id": {"type": "string"},
                "url": {"type": "string"},
                "final_url": {"type": "string"},
                "title": {"type": "string"},
                "status_code": {"type": "integer"},
                "redirect_count": {"type": "integer"},
                "duration_ms": {"type": "number"},
                "is_untrusted_content": {"type": "boolean"},
            },
        },
        "handler": execute_browser_navigate,
    },
    "browser_get_page_state": {
        "name": "browser_get_page_state",
        "display_name": "Browser Get Page State",
        "description": "Inspect active browser page, extract accessibility tree snapshot with numeric element IDs, and capture prompt-sanitized content.",
        "category": "browser",
        "risk_level": "low",
        "timeout_seconds": 15,
        "rate_limit_per_minute": 60,
        "requires_approval": False,
        "is_allowed_in_background": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "tab_id": {"type": "string", "description": "Optional tab ID (defaults to active tab)"},
                "max_elements": {"type": "integer", "description": "Max accessibility tree nodes (10-200)", "default": 100},
                "max_chars": {"type": "integer", "description": "Max characters of formatted observation (500-20000)", "default": 8000},
            },
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "final_url": {"type": "string"},
                "title": {"type": "string"},
                "tab_id": {"type": "string"},
                "tabs_count": {"type": "integer"},
                "viewport": {"type": "object"},
                "axtree_formatted": {"type": "string"},
                "text_content": {"type": "string"},
                "is_untrusted_content": {"type": "boolean"},
                "captured_at": {"type": "string"},
            },
        },
        "handler": execute_browser_get_page_state,
    },
    "browser_screenshot": {
        "name": "browser_screenshot",
        "display_name": "Browser Screenshot",
        "description": "Capture a viewport or full-page PNG screenshot of the active browser tab without persisting to disk.",
        "category": "browser",
        "risk_level": "low",
        "timeout_seconds": 15,
        "rate_limit_per_minute": 30,
        "requires_approval": False,
        "is_allowed_in_background": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "tab_id": {"type": "string", "description": "Optional tab ID (defaults to active tab)"},
                "full_page": {"type": "boolean", "description": "Whether to capture full scrollable page", "default": False},
            },
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "tab_id": {"type": "string"},
                "format": {"type": "string"},
                "size_bytes": {"type": "integer"},
                "data_base64_preview": {"type": "string"},
                "is_untrusted_content": {"type": "boolean"},
            },
        },
        "handler": execute_browser_screenshot,
    },
    "browser_click": {
        "name": "browser_click",
        "display_name": "Browser Click Element",
        "description": "Click an interactive element identified by its numeric ID from a fresh page observation.",
        "category": "browser",
        "risk_level": "low",
        "timeout_seconds": 15,
        "rate_limit_per_minute": 60,
        "requires_approval": False,
        "is_allowed_in_background": False,
        "input_schema": {
            "type": "object",
            "properties": {
                "element_id": {"type": "integer", "description": "Numeric element ID from the active page observation AXTree"},
                "tab_id": {"type": "string", "description": "Optional tab ID (defaults to active tab)"},
                "click_count": {"type": "integer", "description": "Number of clicks (1, 2, or 3)", "default": 1},
                "button": {"type": "string", "description": "Mouse button (left, right, middle)", "default": "left"},
            },
            "required": ["element_id"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "action": {"type": "string"},
                "element_id": {"type": "integer"},
                "role": {"type": "string"},
                "name": {"type": "string"},
                "tab_id": {"type": "string"},
                "url": {"type": "string"},
                "is_untrusted_content": {"type": "boolean"},
            },
        },
        "handler": execute_browser_click,
    },
    "browser_type": {
        "name": "browser_type",
        "display_name": "Browser Type Text",
        "description": "Type text into an input field identified by its numeric ID from a fresh page observation.",
        "category": "browser",
        "risk_level": "medium",
        "timeout_seconds": 15,
        "rate_limit_per_minute": 60,
        "requires_approval": False,
        "is_allowed_in_background": False,
        "input_schema": {
            "type": "object",
            "properties": {
                "element_id": {"type": "integer", "description": "Numeric element ID from the active page observation AXTree"},
                "text": {"type": "string", "description": "Text payload to type (max 2000 chars, no NUL bytes)"},
                "clear_first": {"type": "boolean", "description": "Whether to clear existing field content before typing", "default": True},
                "press_enter": {"type": "boolean", "description": "Whether to press Enter key after typing", "default": False},
                "tab_id": {"type": "string", "description": "Optional tab ID (defaults to active tab)"},
            },
            "required": ["element_id", "text"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "action": {"type": "string"},
                "element_id": {"type": "integer"},
                "role": {"type": "string"},
                "character_count": {"type": "integer"},
                "is_sensitive": {"type": "boolean"},
                "text_summary": {"type": "string"},
                "tab_id": {"type": "string"},
                "is_untrusted_content": {"type": "boolean"},
            },
        },
        "handler": execute_browser_type,
    },
    "browser_select": {
        "name": "browser_select",
        "display_name": "Browser Select Option",
        "description": "Select an option from a dropdown or combobox element by numeric element ID.",
        "category": "browser",
        "risk_level": "medium",
        "timeout_seconds": 15,
        "rate_limit_per_minute": 60,
        "requires_approval": False,
        "is_allowed_in_background": False,
        "input_schema": {
            "type": "object",
            "properties": {
                "element_id": {"type": "integer", "description": "Numeric element ID of the select/combobox element"},
                "value": {"type": "string", "description": "Option value or text label to select"},
                "tab_id": {"type": "string", "description": "Optional tab ID (defaults to active tab)"},
            },
            "required": ["element_id", "value"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "action": {"type": "string"},
                "element_id": {"type": "integer"},
                "value": {"type": "string"},
                "tab_id": {"type": "string"},
                "is_untrusted_content": {"type": "boolean"},
            },
        },
        "handler": execute_browser_select,
    },
    "browser_scroll": {
        "name": "browser_scroll",
        "display_name": "Browser Scroll",
        "description": "Scroll the viewport of the active browser page in a specified direction.",
        "category": "browser",
        "risk_level": "low",
        "timeout_seconds": 10,
        "rate_limit_per_minute": 60,
        "requires_approval": False,
        "is_allowed_in_background": False,
        "input_schema": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "description": "Scroll direction (down, up, top, bottom)", "default": "down"},
                "amount": {"type": "integer", "description": "Scroll amount in pixels (10-2000)", "default": 300},
                "tab_id": {"type": "string", "description": "Optional tab ID (defaults to active tab)"},
            },
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "action": {"type": "string"},
                "direction": {"type": "string"},
                "amount": {"type": "integer"},
                "tab_id": {"type": "string"},
                "is_untrusted_content": {"type": "boolean"},
            },
        },
        "handler": execute_browser_scroll,
    },
    "browser_press_key": {
        "name": "browser_press_key",
        "display_name": "Browser Press Key",
        "description": "Send a governed keyboard key to the active browser page (e.g. Enter, Tab, Escape, Arrow keys).",
        "category": "browser",
        "risk_level": "low",
        "timeout_seconds": 10,
        "rate_limit_per_minute": 60,
        "requires_approval": False,
        "is_allowed_in_background": False,
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Allowed key: Enter, Tab, Escape, ArrowDown, ArrowUp, ArrowLeft, ArrowRight, PageDown, PageUp, Home, End, Backspace, Delete, Space"},
                "tab_id": {"type": "string", "description": "Optional tab ID (defaults to active tab)"},
            },
            "required": ["key"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "action": {"type": "string"},
                "key": {"type": "string"},
                "tab_id": {"type": "string"},
                "is_untrusted_content": {"type": "boolean"},
            },
        },
        "handler": execute_browser_press_key,
    },
    "browser_tab_manage": {
        "name": "browser_tab_manage",
        "display_name": "Browser Tab Manage",
        "description": "Manage browser tabs within the workspace context (create, switch, close, list) up to 4 tabs.",
        "category": "browser",
        "risk_level": "low",
        "timeout_seconds": 15,
        "rate_limit_per_minute": 30,
        "requires_approval": False,
        "is_allowed_in_background": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "Action (create, switch, close, list)", "default": "list"},
                "tab_id": {"type": "string", "description": "Target tab ID for switch or close"},
                "url": {"type": "string", "description": "Optional URL to navigate to upon creating a tab"},
            },
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "action": {"type": "string"},
                "tab": {"type": "object"},
                "tabs": {"type": "array"},
                "closed_tab_id": {"type": "string"},
                "total_tabs": {"type": "integer"},
            },
        },
        "handler": execute_browser_tab_manage,
    },
    "browser_list_credentials": {
        "name": "browser_list_credentials",
        "display_name": "Browser List Credentials",
        "description": "List non-sensitive credential metadata for the workspace. Plaintext secrets are never returned.",
        "category": "browser",
        "risk_level": "low",
        "timeout_seconds": 10,
        "rate_limit_per_minute": 60,
        "requires_approval": False,
        "is_allowed_in_background": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "target_origin": {"type": "string", "description": "Optional origin filter (e.g. https://login.example.com)"},
            },
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "action": {"type": "string"},
                "credentials": {"type": "array"},
                "total": {"type": "integer"},
            },
        },
        "handler": execute_browser_list_credentials,
    },
    "browser_inject_credential": {
        "name": "browser_inject_credential",
        "display_name": "Browser Inject Credential",
        "description": "Securely inject stored credentials directly into active webpage form fields via Playwright-native boundary. Plaintext credentials are never exposed.",
        "category": "browser",
        "risk_level": "high",
        "timeout_seconds": 20,
        "rate_limit_per_minute": 20,
        "requires_approval": True,
        "is_allowed_in_background": False,
        "input_schema": {
            "type": "object",
            "properties": {
                "credential_id": {"type": "string", "description": "UUID of the stored credential to inject"},
                "tab_id": {"type": "string", "description": "Optional tab ID (defaults to active tab)"},
                "username_element_id": {"type": "integer", "description": "Optional AXTree element ID of the username field"},
                "password_element_id": {"type": "integer", "description": "Optional AXTree element ID of the password field"},
                "submit_form": {"type": "boolean", "description": "Whether to automatically submit the form after injection", "default": False},
            },
            "required": ["credential_id"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "action": {"type": "string"},
                "credential_id": {"type": "string"},
                "name": {"type": "string"},
                "target_origin": {"type": "string"},
                "username_hint": {"type": "string"},
                "tab_id": {"type": "string"},
                "is_untrusted_content": {"type": "boolean"},
            },
        },
        "handler": execute_browser_inject_credential,
    },
    "browser_save_session": {
        "name": "browser_save_session",
        "display_name": "Browser Save Session",
        "description": "Capture and encrypt active browser storage state (cookies, storage) into the encrypted session vault.",
        "category": "browser",
        "risk_level": "medium",
        "timeout_seconds": 15,
        "rate_limit_per_minute": 30,
        "requires_approval": False,
        "is_allowed_in_background": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "session_name": {"type": "string", "description": "Name for the saved session snapshot", "default": "default"},
                "tab_id": {"type": "string", "description": "Optional tab ID (defaults to active tab)"},
            },
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "action": {"type": "string"},
                "session_id": {"type": "string"},
                "session_name": {"type": "string"},
                "target_origin": {"type": "string"},
                "is_untrusted_content": {"type": "boolean"},
            },
        },
        "handler": execute_browser_save_session,
    },
    "browser_restore_session": {
        "name": "browser_restore_session",
        "display_name": "Browser Restore Session",
        "description": "Restore and decrypt a previously stored browser session into the active Playwright context.",
        "category": "browser",
        "risk_level": "medium",
        "timeout_seconds": 15,
        "rate_limit_per_minute": 30,
        "requires_approval": False,
        "is_allowed_in_background": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "session_name": {"type": "string", "description": "Name of the stored session snapshot", "default": "default"},
                "tab_id": {"type": "string", "description": "Optional tab ID (defaults to active tab)"},
                "target_origin": {"type": "string", "description": "Optional origin to match stored session against"},
            },
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "action": {"type": "string"},
                "session_name": {"type": "string"},
                "target_origin": {"type": "string"},
                "cookies_restored_count": {"type": "integer"},
                "is_untrusted_content": {"type": "boolean"},
            },
        },
        "handler": execute_browser_restore_session,
    },
}


def validate_json_schema(schema: Dict[str, Any], data: Dict[str, Any]) -> None:
    """Validate argument dictionary against basic JSON schema requirements."""
    if not isinstance(data, dict):
        raise ValidationError("Tool arguments must be a dictionary/object")

    required = schema.get("required", [])
    for field in required:
        if field not in data:
            raise ValidationError(f"Missing required parameter '{field}' for tool input schema")

    properties = schema.get("properties", {})
    for k, val in data.items():
        if k in properties:
            expected_type = properties[k].get("type")
            if expected_type == "string" and not isinstance(val, str):
                raise ValidationError(f"Parameter '{k}' must be a string")
            elif expected_type == "integer" and not (isinstance(val, int) and not isinstance(val, bool)):
                raise ValidationError(f"Parameter '{k}' must be an integer")
            elif expected_type == "number" and not (isinstance(val, (int, float)) and not isinstance(val, bool)):
                raise ValidationError(f"Parameter '{k}' must be a number")
            elif expected_type == "boolean" and not isinstance(val, bool):
                raise ValidationError(f"Parameter '{k}' must be a boolean")
            elif expected_type == "array" and not isinstance(val, list):
                raise ValidationError(f"Parameter '{k}' must be an array")
            elif expected_type == "object" and not isinstance(val, dict):
                raise ValidationError(f"Parameter '{k}' must be an object")


class ToolRegistryService:
    """Manages tool registration, discovery, authorization, execution, and audit logging."""

    def __init__(self):
        self._handlers: Dict[str, Callable] = {
            name: spec["handler"] for name, spec in BUILTIN_TOOLS.items() if "handler" in spec
        }

    def register_handler(self, tool_name: str, handler: Callable) -> None:
        """Register a Python callable handler for a tool name."""
        self._handlers[tool_name] = handler

    async def ensure_builtin_tools(self, db: AsyncSession) -> None:
        """Ensure built-in system tools exist in the database."""
        for name, spec in BUILTIN_TOOLS.items():
            res = await db.execute(select(Tool).where(Tool.name == name))
            tool = res.scalar_one_or_none()
            if not tool:
                new_tool = Tool(
                    name=spec["name"],
                    display_name=spec["display_name"],
                    description=spec["description"],
                    category=spec["category"],
                    risk_level=spec["risk_level"],
                    input_schema=spec["input_schema"],
                    output_schema=spec.get("output_schema", {}),
                    timeout_seconds=spec.get("timeout_seconds", 30),
                    rate_limit_per_minute=spec.get("rate_limit_per_minute", 60),
                    requires_approval=spec.get("requires_approval", False),
                    is_allowed_in_background=spec.get("is_allowed_in_background", True),
                    is_active=True,
                )
                db.add(new_tool)
        await db.commit()

    async def list_tools(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        category: Optional[str] = None,
    ) -> List[ToolResponse]:
        """List all tools available to the given workspace (system tools + workspace tools)."""
        await self.ensure_builtin_tools(db)

        stmt = select(Tool).where(
            (Tool.workspace_id == workspace_id) | (Tool.workspace_id.is_(None)),
            Tool.is_active.is_(True),
        )
        if category:
            stmt = stmt.where(Tool.category == category)

        res = await db.execute(stmt)
        tools = res.scalars().all()

        return [
            ToolResponse(
                id=t.id,
                workspace_id=t.workspace_id,
                integration_id=t.integration_id,
                name=t.name,
                display_name=t.display_name,
                description=t.description,
                category=t.category,
                risk_level=t.risk_level,
                input_schema=t.input_schema,
                output_schema=t.output_schema,
                timeout_seconds=t.timeout_seconds,
                rate_limit_per_minute=t.rate_limit_per_minute,
                requires_approval=t.requires_approval,
                is_allowed_in_background=t.is_allowed_in_background,
                is_active=t.is_active,
                created_at=t.created_at,
            )
            for t in tools
        ]

    async def get_tool(self, db: AsyncSession, tool_id: uuid.UUID, workspace_id: uuid.UUID) -> Tool:
        """Fetch tool and verify workspace access."""
        res = await db.execute(
            select(Tool).where(
                Tool.id == tool_id,
                (Tool.workspace_id == workspace_id) | (Tool.workspace_id.is_(None)),
                Tool.is_active.is_(True),
            )
        )
        tool = res.scalar_one_or_none()
        if not tool:
            raise EntityNotFoundError("Tool", str(tool_id))
        return tool

    async def register_tool(
        self,
        db: AsyncSession,
        payload: ToolRegisterRequest,
        workspace_id: uuid.UUID,
        actor_id: str,
    ) -> ToolResponse:
        """Register a new tool for a specific workspace with audit logging."""
        # Check duplicate tool name
        res = await db.execute(
            select(Tool).where(
                Tool.name == payload.name,
                (Tool.workspace_id == workspace_id) | (Tool.workspace_id.is_(None)),
            )
        )
        if res.scalar_one_or_none():
            raise ValidationError(f"Tool with name '{payload.name}' already exists in workspace")

        tool = Tool(
            workspace_id=workspace_id,
            name=payload.name,
            display_name=payload.display_name,
            description=payload.description,
            category=payload.category,
            risk_level=payload.risk_level,
            input_schema=payload.input_schema,
            output_schema=payload.output_schema or {},
            timeout_seconds=payload.timeout_seconds,
            rate_limit_per_minute=payload.rate_limit_per_minute,
            requires_approval=payload.requires_approval,
            is_allowed_in_background=payload.is_allowed_in_background,
            is_active=True,
        )
        db.add(tool)
        await db.flush()

        # Audit log creation
        await self._log_audit(
            db=db,
            workspace_id=workspace_id,
            actor_type="user",
            actor_id=actor_id,
            action="tool.registered",
            resource_type="tool",
            resource_id=str(tool.id),
            details={"name": tool.name, "risk_level": tool.risk_level},
        )
        await db.commit()
        await db.refresh(tool)

        return ToolResponse(
            id=tool.id,
            workspace_id=tool.workspace_id,
            integration_id=tool.integration_id,
            name=tool.name,
            display_name=tool.display_name,
            description=tool.description,
            category=tool.category,
            risk_level=tool.risk_level,
            input_schema=tool.input_schema,
            output_schema=tool.output_schema,
            timeout_seconds=tool.timeout_seconds,
            rate_limit_per_minute=tool.rate_limit_per_minute,
            requires_approval=tool.requires_approval,
            is_allowed_in_background=tool.is_allowed_in_background,
            is_active=tool.is_active,
            created_at=tool.created_at,
        )

    async def execute_tool(
        self,
        db: AsyncSession,
        request: ToolExecutionRequest,
        actor_id: str,
        actor_type: str = "user",
    ) -> ToolExecutionResponse:
        """Execute a tool through validation, authorization, risk-level check, and audit boundaries."""
        await self.ensure_builtin_tools(db)

        # 1. Resolve Tool Entity
        if request.tool_id:
            tool = await self.get_tool(db, request.tool_id, request.workspace_id)
        elif request.tool_name:
            res = await db.execute(
                select(Tool).where(
                    Tool.name == request.tool_name,
                    (Tool.workspace_id == request.workspace_id) | (Tool.workspace_id.is_(None)),
                    Tool.is_active.is_(True),
                )
            )
            tool = res.scalar_one_or_none()
            if not tool:
                raise EntityNotFoundError("Tool", request.tool_name)
        else:
            raise ValidationError("Either tool_id or tool_name must be provided")

        if not tool.is_active:
            raise AuthorizationError(f"Tool '{tool.name}' is currently disabled")

        # 2. Emergency Kill Switch Check
        from app.services.kill_switch import kill_switch
        if kill_switch.is_active(request.workspace_id):
            logger.warning(f"ToolRegistry: Tool '{tool.name}' blocked - Emergency Kill Switch is active")
            raise AuthorizationError(f"Emergency Kill Switch is active in workspace '{request.workspace_id}'. Tool execution is prohibited.")

        # 3. Check Tool Permission Overrides
        perm_res = await db.execute(
            select(ToolPermission).where(
                ToolPermission.workspace_id == request.workspace_id,
                ToolPermission.tool_id == tool.id,
            )
        )
        perm = perm_res.scalar_one_or_none()
        if perm and not perm.is_enabled:
            raise AuthorizationError(f"Tool '{tool.name}' has been disabled by workspace policy")

        # 3. Validate Input Arguments against JSON Schema
        validate_json_schema(tool.input_schema, request.arguments)

        # 4. Semantic Risk Evaluation & Human-In-The-Loop Approval Check
        effective_risk_level = tool.risk_level
        if tool.name.startswith("browser_"):
            from app.services.browser.governance import browser_risk_classifier
            effective_risk_level = browser_risk_classifier.evaluate_risk(
                tool_name=tool.name,
                arguments=request.arguments,
                workspace_id=request.workspace_id,
            )

        requires_approval = tool.requires_approval or (perm and perm.override_requires_approval)
        if effective_risk_level in ["high", "critical"] or requires_approval:
            # Generate cryptographic approval token for HITL gate
            approval_payload = {
                "workspace_id": str(request.workspace_id),
                "tool_id": str(tool.id),
                "tool_name": tool.name,
                "actor_id": actor_id,
                "arguments": request.arguments,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            token = sign_approval_payload(approval_payload)
            return ToolExecutionResponse(
                success=False,
                tool_name=tool.name,
                risk_level=effective_risk_level,
                execution_time_ms=0.0,
                requires_hitl_approval=True,
                approval_token=token,
                error=f"Tool execution suspended: Human-in-the-Loop approval required for {effective_risk_level}-risk action",
            )

        # 5. Resolve Handler and Execute with Timeout & Telemetry Span
        from app.core.telemetry import telemetry_manager

        handler = self._handlers.get(tool.name)
        if not handler:
            raise ValidationError(f"No executable handler registered for tool '{tool.name}'")

        start_time = time.perf_counter()
        async with telemetry_manager.start_async_span(
            name=f"tool.execute {tool.name}",
            span_type="tool",
            attributes={
                "aura.tool_name": tool.name,
                "aura.risk_level": tool.risk_level,
                "aura.workspace_id": str(request.workspace_id),
                "aura.actor_id": actor_id,
                "aura.actor_type": actor_type,
                "aura.arguments_keys": list(request.arguments.keys()),
            },
        ) as span:
            try:
                import inspect
                call_kwargs = dict(request.arguments)
                sig = inspect.signature(handler)
                if "workspace_id" in sig.parameters and "workspace_id" not in call_kwargs:
                    call_kwargs["workspace_id"] = request.workspace_id
                if "db" in sig.parameters and "db" not in call_kwargs:
                    call_kwargs["db"] = db

                if asyncio.iscoroutinefunction(handler):
                    result = await asyncio.wait_for(
                        handler(**call_kwargs),
                        timeout=float(tool.timeout_seconds),
                    )
                else:
                    result = await asyncio.wait_for(
                        asyncio.to_thread(handler, **call_kwargs),
                        timeout=float(tool.timeout_seconds),
                    )
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                span.set_attribute("aura.status", "success")
                span.set_attribute("aura.duration_ms", round(duration_ms, 2))

                # Log audit event with trace_id correlation
                active_trace_id = telemetry_manager.get_current_trace_id()
                audit_details = {
                    "tool_name": tool.name,
                    "arguments_keys": list(request.arguments.keys()),
                    "duration_ms": round(duration_ms, 2),
                    "status": "success",
                }
                if active_trace_id:
                    audit_details["trace_id"] = active_trace_id

                await self._log_audit(
                    db=db,
                    workspace_id=request.workspace_id,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    action="tool.executed",
                    resource_type="tool",
                    resource_id=str(tool.id),
                    details=audit_details,
                )
                await db.commit()

                return ToolExecutionResponse(
                    success=True,
                    tool_name=tool.name,
                    result=result,
                    risk_level=tool.risk_level,
                    execution_time_ms=round(duration_ms, 2),
                    requires_hitl_approval=False,
                )

            except asyncio.TimeoutError:
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                error_msg = f"Tool '{tool.name}' execution timed out after {tool.timeout_seconds}s"
                span.set_attribute("aura.status", "timeout")
                logger.error(error_msg)
                return ToolExecutionResponse(
                    success=False,
                    tool_name=tool.name,
                    error=error_msg,
                    risk_level=tool.risk_level,
                    execution_time_ms=round(duration_ms, 2),
                )
            except Exception as e:
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                span.set_attribute("aura.status", "error")
                logger.error(f"Tool '{tool.name}' execution error: {e}")
                return ToolExecutionResponse(
                    success=False,
                    tool_name=tool.name,
                    error=f"Execution error: {str(e)}",
                    risk_level=tool.risk_level,
                    execution_time_ms=round(duration_ms, 2),
                )

    async def _log_audit(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        actor_type: str,
        actor_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        details: Dict[str, Any],
    ) -> None:
        """Emit tamper-evident SHA-256 hashed audit log record."""
        from app.services.audit_service import audit_service
        await audit_service.record_event(
            db=db,
            workspace_id=workspace_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
        )


tool_registry = ToolRegistryService()
tool_registry_service = tool_registry

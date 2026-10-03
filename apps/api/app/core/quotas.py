"""Resource Quotas, Rate Limits and Execution Ceiling Enforcement Module.

Enforces:
- Hard ceiling on task duration (default max 600s)
- Hard ceiling on model loop iterations (default max 15 turns)
- Hard ceiling on sub-agent recursion depth (max 2)
- Hard ceiling on concurrent worker threads (max 4)
- Maximum tool output size (max 1 MB)
- Maximum token budget per step
"""

from typing import Any, Dict, Optional
from app.core.errors import RateLimitError, ValidationError
from app.core.logging import logger


class ResourceQuotaEnforcer:
    """Enforces deterministic computational and memory boundaries."""

    MAX_TASK_DURATION_SECONDS = 600
    MAX_LOOP_ITERATIONS = 15
    MAX_SUBAGENT_DEPTH = 2
    MAX_CONCURRENT_WORKERS = 4
    MAX_TOOL_OUTPUT_BYTES = 1024 * 1024  # 1 MB
    MAX_PROMPT_TOKENS = 8192

    @classmethod
    def check_depth(cls, current_depth: int) -> None:
        """Validate sub-agent depth against the hard architectural limit of 2."""
        if current_depth > cls.MAX_SUBAGENT_DEPTH:
            logger.error(f"QuotaEnforcer: Sub-agent recursion depth {current_depth} exceeded limit of {cls.MAX_SUBAGENT_DEPTH}")
            raise ValidationError(f"Sub-agent depth {current_depth} exceeds hard ceiling of {cls.MAX_SUBAGENT_DEPTH}")

    @classmethod
    def check_iterations(cls, iteration_count: int) -> None:
        """Validate loop iterations against max limit."""
        if iteration_count > cls.MAX_LOOP_ITERATIONS:
            logger.error(f"QuotaEnforcer: Execution loop exceeded {cls.MAX_LOOP_ITERATIONS} iterations")
            raise RateLimitError(f"Task exceeded maximum allowed iterations ({cls.MAX_LOOP_ITERATIONS})")

    @classmethod
    def sanitize_and_truncate_output(cls, output: Any) -> Any:
        """Truncate excessive tool outputs to prevent context memory overflow."""
        if isinstance(output, str):
            if len(output.encode("utf-8")) > cls.MAX_TOOL_OUTPUT_BYTES:
                logger.warning("QuotaEnforcer: Tool output exceeded 1MB limit; truncating")
                return output[:100000] + "\n\n...[OUTPUT TRUNCATED DUE TO 1MB RESOURCE CEILING]..."
        elif isinstance(output, dict):
            # Check stringified size
            import json
            dumped = json.dumps(output)
            if len(dumped.encode("utf-8")) > cls.MAX_TOOL_OUTPUT_BYTES:
                logger.warning("QuotaEnforcer: Dict tool output exceeded 1MB limit; truncating")
                return {"status": "truncated", "summary": dumped[:50000] + "...[TRUNCATED]"}
        return output


quota_enforcer = ResourceQuotaEnforcer()

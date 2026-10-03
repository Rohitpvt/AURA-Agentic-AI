"""Canonical Agent Runtime Event definitions."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
import uuid


class RuntimeEventType(str, Enum):
    TASK_CREATED = "task.created"
    PLAN_GENERATED = "plan.generated"
    STEP_STARTED = "step.started"
    TOOL_REQUESTED = "tool.requested"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    TOOL_REJECTED = "tool.rejected"
    STEP_COMPLETED = "step.completed"
    STEP_FAILED = "step.failed"
    VERIFICATION_STARTED = "verification.started"
    VERIFICATION_COMPLETED = "verification.completed"
    MEMORY_RECALLED = "memory.recalled"
    MEMORY_WRITTEN = "memory.written"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_CANCELLED = "task.cancelled"
    # Phase 2B Events
    MCP_SERVER_STARTED = "mcp.server_started"
    MCP_TOOL_DISCOVERED = "mcp.tool_discovered"
    MCP_TOOL_EXECUTED = "mcp.tool_executed"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_GRANTED = "approval.granted"
    APPROVAL_REJECTED = "approval.rejected"
    APPROVAL_EXPIRED = "approval.expired"
    SUBAGENT_STARTED = "subagent.started"
    SUBAGENT_COMPLETED = "subagent.completed"
    SUBAGENT_FAILED = "subagent.failed"
    SUBAGENT_CANCELLED = "subagent.cancelled"
    KILL_SWITCH_ACTIVATED = "kill_switch.activated"
    # Phase 6 File Events
    FILE_JOB_UPDATED = "file.job_updated"
    FILE_EXTRACTION_COMPLETED = "file.extraction_completed"
    FILE_INDEXING_COMPLETED = "file.indexing_completed"


@dataclass
class RuntimeEvent:
    """Normalized runtime event emitted during cognitive execution."""
    event_type: RuntimeEventType
    task_id: uuid.UUID
    agent_run_id: uuid.UUID
    step_number: Optional[int] = None
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type.value if hasattr(self.event_type, "value") else str(self.event_type),
            "task_id": str(self.task_id),
            "agent_run_id": str(self.agent_run_id),
            "step_number": self.step_number,
            "data": self.data,
            "timestamp": self.timestamp,
        }


class EventBroadcasterHub:
    """In-memory event hub for SSE and real-time frontend streaming subscriptions."""

    def __init__(self):
        import asyncio
        self._subscribers = set()

    def subscribe(self):
        import asyncio
        q = asyncio.Queue(maxsize=100)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q) -> None:
        self._subscribers.discard(q)

    def publish(self, event: Any) -> None:
        import asyncio
        if hasattr(event, "to_dict"):
            event_dict = event.to_dict()
        elif isinstance(event, dict):
            event_dict = event
        else:
            event_dict = {"event_type": "generic", "data": str(event)}
        for q in list(self._subscribers):
            try:
                q.put_nowait(event_dict)
            except asyncio.QueueFull:
                pass


event_hub = EventBroadcasterHub()


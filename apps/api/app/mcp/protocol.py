"""JSON-RPC 2.0 Protocol serialization and parsing for Model Context Protocol (MCP)."""

import json
from typing import Any, Dict, Optional
from app.core.errors import ValidationError


class JSONRPCMessage:
    """Helper for constructing and parsing MCP JSON-RPC 2.0 frames."""

    @staticmethod
    def build_request(method: str, params: Optional[Dict[str, Any]] = None, request_id: int = 1) -> str:
        """Create a JSON-RPC 2.0 request line."""
        msg: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            msg["params"] = params
        return json.dumps(msg) + "\n"

    @staticmethod
    def build_notification(method: str, params: Optional[Dict[str, Any]] = None) -> str:
        """Create a JSON-RPC 2.0 notification line (no id)."""
        msg: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            msg["params"] = params
        return json.dumps(msg) + "\n"

    @staticmethod
    def parse_response(line: str) -> Dict[str, Any]:
        """Parse and validate incoming JSON-RPC response."""
        try:
            data = json.loads(line.strip())
            if not isinstance(data, dict):
                raise ValidationError("MCP response is not a valid JSON object")
            if "error" in data and data["error"]:
                err_msg = data["error"].get("message", "Unknown MCP JSON-RPC error")
                err_code = data["error"].get("code", -1)
                raise ValidationError(f"MCP Server Error [{err_code}]: {err_msg}")
            return data
        except json.JSONDecodeError as e:
            raise ValidationError(f"Failed to parse MCP JSON-RPC payload: {e}")

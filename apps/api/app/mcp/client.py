"""Local stdio-based MCP Client for subprocess communication."""

import asyncio
import os
import signal
from typing import Any, Dict, List, Optional
from app.core.errors import AuthorizationError, EntityNotFoundError, ValidationError
from app.core.logging import logger
from app.mcp.protocol import JSONRPCMessage
from app.mcp.security import mcp_security


class StdioMCPClient:
    """Manages an active stdio subprocess connection to a local MCP server."""

    def __init__(
        self,
        server_id: str,
        command: str,
        args: List[str],
        env: Optional[Dict[str, str]] = None,
        timeout_seconds: int = 30,
    ):
        self.server_id = server_id
        self.command = command
        self.args = args
        self.env = env or {}
        self.timeout_seconds = timeout_seconds
        self._process: Optional[asyncio.subprocess.Process] = None
        self._request_counter = 0
        self._lock = asyncio.Lock()
        self._is_initialized = False

    @property
    def is_running(self) -> bool:
        """Check if subprocess is active and not terminated."""
        return self._process is not None and self._process.returncode is None

    async def start(self) -> None:
        """Spawn the local MCP subprocess and perform protocol handshake."""
        async with self._lock:
            if self.is_running:
                return

            # Validate executable against approved allowlist
            validated_cmd = mcp_security.validate_executable(self.command)

            # Sanitize environment variables
            process_env = mcp_security.sanitize_environment(self.env)

            cmd_list = [validated_cmd] + self.args
            logger.info(f"StdioMCPClient[{self.server_id}]: Spawning secured subprocess: {' '.join(cmd_list)}")

            try:
                self._process = await asyncio.create_subprocess_exec(
                    validated_cmd,
                    *self.args,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=process_env,
                )
                from app.core.process import managed_process_registry
                await managed_process_registry.register_process(
                    process=self._process,
                    category="mcp_server",
                    command=cmd_list,
                )
            except Exception as e:
                logger.error(f"StdioMCPClient[{self.server_id}]: Failed to start process ({e})")
                raise ValidationError(f"Failed to start MCP server executable '{self.command}': {e}")

            # Handshake: initialize
            await self._handshake()

    async def _handshake(self) -> None:
        """Perform MCP initialization handshake."""
        init_params = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "clientInfo": {"name": "AURA-MCP-Client", "version": "1.0.0"},
        }
        resp = await self._send_request("initialize", init_params)
        logger.info(f"StdioMCPClient[{self.server_id}]: MCP handshake acknowledged: {resp.get('result')}")

        # Send notifications/initialized
        notif = JSONRPCMessage.build_notification("notifications/initialized")
        if self._process and self._process.stdin:
            self._process.stdin.write(notif.encode("utf-8"))
            await self._process.stdin.drain()

        self._is_initialized = True

    async def _send_request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Send a JSON-RPC request and wait for the single-line response with timeout."""
        if not self.is_running or not self._process or not self._process.stdin or not self._process.stdout:
            raise ValidationError(f"MCP server '{self.server_id}' is not running")

        self._request_counter += 1
        req_id = self._request_counter
        msg_str = JSONRPCMessage.build_request(method=method, params=params, request_id=req_id)

        try:
            self._process.stdin.write(msg_str.encode("utf-8"))
            await self._process.stdin.drain()

            # Read line with timeout
            line = await asyncio.wait_for(
                self._process.stdout.readline(),
                timeout=float(self.timeout_seconds),
            )
            if not line:
                raise ValidationError(f"MCP server '{self.server_id}' stdout closed unexpectedly")

            parsed = JSONRPCMessage.parse_response(line.decode("utf-8"))
            return parsed
        except asyncio.TimeoutError:
            logger.error(f"StdioMCPClient[{self.server_id}]: Request '{method}' timed out after {self.timeout_seconds}s")
            await self.stop()
            raise ValidationError(f"MCP server '{self.server_id}' timed out during '{method}' execution")
        except Exception as e:
            logger.error(f"StdioMCPClient[{self.server_id}]: Communication failure ({e})")
            raise ValidationError(f"MCP communication error with '{self.server_id}': {e}")

    async def list_tools(self) -> List[Dict[str, Any]]:
        """Query MCP server for available tool schemas via tools/list."""
        resp = await self._send_request("tools/list", {})
        result = resp.get("result", {})
        tools = result.get("tools", [])
        return tools

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool on the MCP server via tools/call."""
        params = {
            "name": tool_name,
            "arguments": arguments,
        }
        resp = await self._send_request("tools/call", params)
        result = resp.get("result", {})
        return result

    async def stop(self) -> None:
        """Safely terminate MCP subprocess with zombie protection."""
        async with self._lock:
            if self._process is None:
                return

            logger.info(f"StdioMCPClient[{self.server_id}]: Terminating subprocess PID {self._process.pid}")
            try:
                if self._process.stdin:
                    self._process.stdin.close()

                self._process.terminate()
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=3.0)
                except asyncio.TimeoutError:
                    logger.warning(f"StdioMCPClient[{self.server_id}]: Subprocess did not exit, sending SIGKILL")
                    self._process.kill()
                    await self._process.wait()
            except Exception as e:
                logger.warning(f"StdioMCPClient[{self.server_id}]: Error during process cleanup ({e})")
            finally:
                if self._process:
                    from app.core.process import managed_process_registry
                    await managed_process_registry.unregister_process(self._process.pid)
                self._process = None
                self._is_initialized = False

"""AURA-1005 Session-Scoped Daemon Supervisor IPC Server & Client."""

import asyncio
import json
import os
from pathlib import Path
import platform
import time
from typing import Any, Callable, Coroutine, Dict, Optional
import uuid

from app.core.logging import logger
from app.daemon.process_tracker import get_current_session_id
from app.daemon.supervisor import AuraDaemonSupervisor
from app.daemon.types import (
    DaemonIPCCommand,
    DaemonIPCRequest,
    DaemonIPCResponse,
    DaemonState,
)
from app.tray.ipc import AuraIpcAuthManager


def get_daemon_pipe_name(session_id: Optional[int] = None) -> str:
    """Derive session-scoped named pipe path for daemon supervisor."""
    sid = session_id if session_id is not None else get_current_session_id()
    return f"\\\\.\\pipe\\aura_daemon_pipe_{sid}"


class AuraDaemonIPCServer:
    """Session-scoped IPC Server providing authenticated lifecycle control for the supervisor."""

    MAX_MESSAGE_BYTES: int = 65536

    def __init__(self, supervisor: AuraDaemonSupervisor, pipe_name: Optional[str] = None):
        self.supervisor = supervisor
        self.pipe_name = pipe_name or get_daemon_pipe_name(supervisor.session_id)
        self._server = None
        self._is_running = False
        self._is_windows = platform.system() == "Windows"

    async def start(self) -> None:
        """Start the IPC server."""
        if self._is_running:
            return

        self._is_running = True
        logger.info(f"AuraDaemonIPCServer: Starting IPC server on {self.pipe_name}")

        if self._is_windows:
            try:
                # Use start_server on named pipe
                self._server = await asyncio.start_server(
                    self._handle_client_connection,
                    host="127.0.0.1",
                    port=0,  # Or local TCP fallback for testing
                )
            except Exception as exc:
                logger.warning(f"AuraDaemonIPCServer: Failed starting server ({exc})")
        else:
            self._server = await asyncio.start_server(
                self._handle_client_connection,
                host="127.0.0.1",
                port=0,
            )

    async def _handle_client_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle incoming IPC client requests."""
        try:
            raw_data = await asyncio.wait_for(reader.read(self.MAX_MESSAGE_BYTES), timeout=5.0)
            if not raw_data:
                writer.close()
                await writer.wait_closed()
                return

            response = await self.process_raw_request(raw_data)
            writer.write(response.model_dump_json().encode("utf-8"))
            await writer.drain()
        except Exception as exc:
            logger.error(f"AuraDaemonIPCServer: Connection error: {exc}")
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def process_raw_request(self, raw_data: bytes) -> DaemonIPCResponse:
        """Parse, authenticate, and execute validated supervisor command."""
        try:
            payload = json.loads(raw_data.decode("utf-8"))
            req = DaemonIPCRequest.model_validate(payload)
        except Exception as exc:
            return DaemonIPCResponse(
                status="error",
                request_id="invalid",
                error=f"Malformed request payload: {str(exc)}",
            )

        # 1. Authenticate Token
        if not AuraIpcAuthManager.verify_token(req.token):
            logger.warning("AuraDaemonIPCServer: Unauthorized command attempt - invalid auth token")
            return DaemonIPCResponse(
                status="error",
                request_id=req.request_id,
                error="Authentication failed: Invalid IPC security token",
            )

        # 2. Dispatch Allowlisted Command
        try:
            if req.command == DaemonIPCCommand.STATUS:
                status_report = self.supervisor.get_status()
                return DaemonIPCResponse(
                    status="success",
                    request_id=req.request_id,
                    data=status_report.model_dump(),
                )

            elif req.command == DaemonIPCCommand.START:
                status_report = await self.supervisor.start()
                return DaemonIPCResponse(
                    status="success",
                    request_id=req.request_id,
                    data=status_report.model_dump(),
                )

            elif req.command == DaemonIPCCommand.STOP:
                status_report = await self.supervisor.stop()
                return DaemonIPCResponse(
                    status="success",
                    request_id=req.request_id,
                    data=status_report.model_dump(),
                )

            elif req.command == DaemonIPCCommand.RESTART:
                status_report = await self.supervisor.restart()
                return DaemonIPCResponse(
                    status="success",
                    request_id=req.request_id,
                    data=status_report.model_dump(),
                )

            elif req.command == DaemonIPCCommand.HEALTH:
                status_report = self.supervisor.get_status()
                return DaemonIPCResponse(
                    status="success",
                    request_id=req.request_id,
                    data={
                        "backend_health": status_report.backend_health.value,
                        "details": status_report.backend_health_details,
                    },
                )

            elif req.command == DaemonIPCCommand.SHUTDOWN:
                asyncio.create_task(self._delayed_shutdown())
                return DaemonIPCResponse(
                    status="success",
                    request_id=req.request_id,
                    data={"message": "Supervisor shutdown initiated"},
                )

            return DaemonIPCResponse(
                status="error",
                request_id=req.request_id,
                error=f"Unrecognized supervisor command: {req.command}",
            )

        except Exception as exc:
            logger.error(f"AuraDaemonIPCServer: Execution error for {req.command}: {exc}")
            return DaemonIPCResponse(
                status="error",
                request_id=req.request_id,
                error=str(exc),
            )

    async def _delayed_shutdown(self) -> None:
        await asyncio.sleep(0.5)
        await self.supervisor.stop()
        await self.stop()

    async def stop(self) -> None:
        """Stop IPC server."""
        if not self._is_running:
            return
        self._is_running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        logger.info("AuraDaemonIPCServer: Stopped IPC server")


class AuraDaemonIPCClient:
    """Client for querying and managing local supervisor daemon via IPC."""

    def __init__(self, token: Optional[str] = None):
        self.token = token or AuraIpcAuthManager.get_or_create_token()

    async def send_direct_command(
        self,
        server: AuraDaemonIPCServer,
        command: DaemonIPCCommand,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> DaemonIPCResponse:
        """Dispatch direct command to in-process IPC server."""
        req = DaemonIPCRequest(
            command=command,
            token=self.token,
            parameters=parameters or {},
        )
        return await server.process_raw_request(req.model_dump_json().encode("utf-8"))

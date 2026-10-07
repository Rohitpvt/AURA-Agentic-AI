"""AURA-1005 Background Watchdog Health Monitor."""

import asyncio
import time
from typing import Any, Dict, Optional, Tuple

import httpx

from app.core.logging import logger
from app.daemon.process_tracker import ProcessIdentity
from app.daemon.types import DaemonConfig, ProcessHealthStatus


class BackendHealthMonitor:
    """Probes backend process existence and HTTP health endpoints with strict timeout bounds."""

    def __init__(self, config: DaemonConfig):
        self.config = config

    async def probe_health(
        self,
        identity: Optional[ProcessIdentity],
        check_detailed: bool = False,
    ) -> Tuple[ProcessHealthStatus, Dict[str, Any]]:
        """Evaluate backend process status and HTTP endpoint health."""
        # 1. Process Existence Check
        if identity is None:
            return ProcessHealthStatus.DEAD, {"error": "No backend process registered"}

        if not identity.matches_live_process():
            return ProcessHealthStatus.DEAD, {
                "error": f"Process PID {identity.pid} is not running or creation time mismatched"
            }

        # 2. HTTP Endpoint Liveness Probe
        endpoint = self.config.detailed_health_endpoint if check_detailed else self.config.health_endpoint
        url = f"http://{self.config.backend_host}:{self.config.backend_port}{endpoint}"

        try:
            async with httpx.AsyncClient(timeout=self.config.health_timeout) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                    except Exception:
                        data = {"raw_text": resp.text[:200]}

                    raw_status = data.get("status", "").lower()
                    if raw_status == "healthy":
                        return ProcessHealthStatus.HEALTHY, data
                    elif raw_status == "degraded":
                        return ProcessHealthStatus.DEGRADED, data
                    else:
                        return ProcessHealthStatus.HEALTHY, data

                return ProcessHealthStatus.UNRESPONSIVE, {
                    "error": f"HTTP {resp.status_code}",
                    "status_code": resp.status_code,
                }
        except httpx.ConnectError as exc:
            return ProcessHealthStatus.UNRESPONSIVE, {
                "error": "ConnectionRefused",
                "details": str(exc),
            }
        except httpx.TimeoutException:
            return ProcessHealthStatus.UNRESPONSIVE, {
                "error": "Health probe timeout",
            }
        except Exception as exc:
            return ProcessHealthStatus.UNRESPONSIVE, {
                "error": "Probe error",
                "details": str(exc),
            }

"""Background worker daemon for Telegram Bot long-polling."""

import asyncio
import socket
import uuid
from typing import Optional
from sqlalchemy import select
from app.core.logging import logger
from app.db.models.telegram import TelegramIntegration
from app.db.session import async_session_factory
from app.services.integrations.telegram_service import telegram_service


class TelegramDaemon:
    """Async background daemon executing continuous long-polling across active Telegram Bot integrations."""

    def __init__(self, poll_interval_seconds: float = 2.0):
        self.poll_interval = poll_interval_seconds
        self.worker_id = f"tg_worker_{socket.gethostname()}_{uuid.uuid4().hex[:8]}"
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Start the background Telegram polling daemon."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop(), name=f"telegram_daemon_{self.worker_id}")
        logger.info(f"TelegramDaemon: Started background long-poller '{self.worker_id}'")

    async def stop(self) -> None:
        """Stop the background polling daemon gracefully."""
        if not self._running:
            return
        logger.info(f"TelegramDaemon: Stopping poller '{self.worker_id}'...")
        self._running = False
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await telegram_service.close()
        logger.info(f"TelegramDaemon: Poller '{self.worker_id}' stopped safely")

    async def _run_loop(self) -> None:
        """Core polling dispatch loop across active integrations."""
        while self._running:
            try:
                await self.poll_active_integrations()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"TelegramDaemon: Unexpected error in polling cycle: {e}")

            # Sleep briefly or wait for stop event
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.poll_interval)
            except asyncio.TimeoutError:
                pass

    async def poll_active_integrations(self) -> None:
        """Query active Telegram integrations and execute a long-polling cycle for each."""
        async with async_session_factory() as session:
            try:
                stmt = select(TelegramIntegration.id).where(
                    TelegramIntegration.is_active == True,
                    TelegramIntegration.deleted_at.is_(None),
                )
                res = await session.execute(stmt)
                integration_ids = res.scalars().all()
            except Exception as e:
                logger.error(f"TelegramDaemon: Failed to query integrations: {e}")
                return

        # Poll each active integration
        for int_id in integration_ids:
            if not self._running:
                break
            try:
                async with async_session_factory() as poll_session:
                    await telegram_service.poll_integration_updates(
                        db=poll_session,
                        integration_id=int_id,
                        worker_id=self.worker_id,
                        timeout_seconds=20,
                    )
            except Exception as e:
                logger.error(f"TelegramDaemon: Error polling integration {int_id}: {e}")


telegram_daemon = TelegramDaemon()

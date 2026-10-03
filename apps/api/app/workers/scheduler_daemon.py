"""Background worker daemon for AURA Cron Scheduler."""

import asyncio
import socket
import uuid
from typing import Optional
from app.core.logging import logger
from app.db.session import async_session_factory
from app.services.automations.scheduler_service import scheduler_service


class SchedulerDaemon:
    """Async background daemon periodically scanning and claiming due automations."""

    def __init__(self, poll_interval_seconds: float = 5.0):
        self.poll_interval = poll_interval_seconds
        self.worker_id = f"worker_{socket.gethostname()}_{uuid.uuid4().hex[:8]}"
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Start the background scheduler loop."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop(), name=f"scheduler_daemon_{self.worker_id}")
        logger.info(f"SchedulerDaemon: Started background scheduler worker '{self.worker_id}' (poll_interval={self.poll_interval}s)")

    async def stop(self) -> None:
        """Stop the background scheduler loop gracefully."""
        if not self._running:
            return
        logger.info(f"SchedulerDaemon: Stopping worker '{self.worker_id}'...")
        self._running = False
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(f"SchedulerDaemon: Worker '{self.worker_id}' stopped safely")

    async def _run_loop(self) -> None:
        """Core scheduling iteration loop."""
        while self._running:
            try:
                await self.poll_and_dispatch()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"SchedulerDaemon: Unexpected error during poll cycle: {e}")

            # Sleep until next poll or stop signal
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.poll_interval)
            except asyncio.TimeoutError:
                pass

    async def poll_and_dispatch(self) -> None:
        """Execute a single scan, claim, and dispatch cycle."""
        from app.services.kill_switch import kill_switch
        if kill_switch.is_active():
            logger.warning("SchedulerDaemon: Poll cycle suspended because Emergency Kill Switch is active")
            return

        async with async_session_factory() as session:
            try:
                # 1. Recover any expired leases from dead/stalled workers
                await scheduler_service.recover_expired_leases(
                    db=session, worker_id=self.worker_id, limit=10
                )

                # 2. Transactionally claim due automations
                claimed_runs = await scheduler_service.claim_due_automations(
                    db=session, worker_id=self.worker_id, limit=10
                )
                await session.commit()

                # 3. Execute each claimed run
                for run in claimed_runs:
                    try:
                        async with async_session_factory() as exec_session:
                            await scheduler_service.execute_claimed_run(
                                db=exec_session,
                                run_id=run.id,
                                worker_id=self.worker_id,
                            )
                            await exec_session.commit()
                    except Exception as exc:
                        logger.error(f"SchedulerDaemon: Failed executing run {run.id}: {exc}")
            except Exception as exc:
                await session.rollback()
                logger.error(f"SchedulerDaemon: Error in transaction cycle: {exc}")


scheduler_daemon = SchedulerDaemon()

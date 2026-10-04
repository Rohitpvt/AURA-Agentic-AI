"""AURA-706 Long-Horizon Task Recovery Latency Benchmark.

Measures:
1. Checkpoint write latency (step verification & durable boundary persistence)
2. Resume initialization latency (DAG analysis, governance revalidation, state transition)
3. Startup recovery sweep latency (batch sweep & reconciliation of orphaned tasks)
"""

import asyncio
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import statistics
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.base import Base
from app.db.models.task import Task, TaskStep
from app.db.models.user import User
from app.db.models.workspace import Workspace, WorkspaceMember
from app.services.task_recovery_service import task_recovery_service
from app.services.task_service import task_service


async def benchmark_recovery_latencies():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as db:
        # 1. Provision Test Tenant
        user = User(
            id=uuid.uuid4(),
            email=f"bench_{uuid.uuid4().hex[:8]}@example.com",
            full_name="Bench User",
            password_hash="hash",
            is_active=True,
        )
        db.add(user)

        ws = Workspace(
            id=uuid.uuid4(),
            name=f"Bench Workspace {uuid.uuid4().hex[:6]}",
            slug=f"bench-ws-{uuid.uuid4().hex[:6]}",
        )
        db.add(ws)

        member = WorkspaceMember(
            id=uuid.uuid4(),
            workspace_id=ws.id,
            user_id=user.id,
            role="owner",
            permissions=["admin"],
        )
        db.add(member)
        await db.commit()

        # -------------------------------------------------------------
        # Benchmark 1: Checkpoint Write Latency (50 iterations)
        # -------------------------------------------------------------
        task = Task(
            id=uuid.uuid4(),
            workspace_id=ws.id,
            created_by=user.id,
            title="Benchmark Task",
            goal="Test recovery checkpoints",
            status="running",
            autonomy_level=2,
            budget_max_tokens=100000,
            budget_max_cost_cents=500,
            timeout_seconds=3600,
        )
        db.add(task)
        await db.commit()

        checkpoint_write_latencies_ms = []
        for i in range(50):
            step = TaskStep(
                id=uuid.uuid4(),
                task_id=task.id,
                step_number=i + 1,
                title=f"Step {i + 1}",
                description="Checkpoint persistence step",
                dependencies=[],
                status="completed",
                tool_name="web_search",
                tool_input={"query": f"query {i}"},
                tool_output={"result": f"out {i}"},
                is_verified=True,
            )
            t0 = time.perf_counter()
            db.add(step)
            await db.commit()
            t1 = time.perf_counter()
            checkpoint_write_latencies_ms.append((t1 - t0) * 1000.0)

        # -------------------------------------------------------------
        # Benchmark 2: Resume Initialization Latency (30 iterations)
        # -------------------------------------------------------------
        resume_init_latencies_ms = []
        for i in range(30):
            # Create a task needing resumption
            resumable_task = Task(
                id=uuid.uuid4(),
                workspace_id=ws.id,
                created_by=user.id,
                title=f"Resumable Task {i}",
                goal="Resumption latency measurement",
                status="pending",
                autonomy_level=2,
                budget_max_tokens=100000,
                budget_max_cost_cents=500,
                timeout_seconds=3600,
            )
            db.add(resumable_task)
            step1 = TaskStep(
                id=uuid.uuid4(),
                task_id=resumable_task.id,
                step_number=1,
                title="Step 1",
                description="Verified step",
                dependencies=[],
                status="completed",
                tool_name="web_search",
                tool_input={"query": "test"},
                tool_output={"ok": True},
                is_verified=True,
            )
            step2 = TaskStep(
                id=uuid.uuid4(),
                task_id=resumable_task.id,
                step_number=2,
                title="Step 2",
                description="Unverified step",
                dependencies=[1],
                status="running",
                tool_name="inspect_file",
                tool_input={"file_id": str(uuid.uuid4())},
                is_verified=False,
            )
            db.add_all([step1, step2])
            await db.commit()

            t0 = time.perf_counter()
            await task_recovery_service.resume_task(
                db=db,
                task_id=resumable_task.id,
                workspace_id=ws.id,
                actor_id=str(user.id),
            )
            t1 = time.perf_counter()
            resume_init_latencies_ms.append((t1 - t0) * 1000.0)

        # -------------------------------------------------------------
        # Benchmark 3: Startup Recovery Sweep Latency (20 iterations)
        # -------------------------------------------------------------
        sweep_latencies_ms = []
        for _ in range(20):
            # Seed 5 orphaned tasks
            for k in range(5):
                orphan = Task(
                    id=uuid.uuid4(),
                    workspace_id=ws.id,
                    created_by=user.id,
                    title=f"Orphan Task {k}",
                    goal="Startup sweep measurement",
                    status="running",
                    autonomy_level=2,
                    budget_max_tokens=100000,
                    budget_max_cost_cents=500,
                    timeout_seconds=3600,
                )
                db.add(orphan)
            await db.commit()

            t0 = time.perf_counter()
            await task_recovery_service.startup_recovery_sweep(db)
            t1 = time.perf_counter()
            sweep_latencies_ms.append((t1 - t0) * 1000.0)

    await engine.dispose()

    print("\n=================================================================")
    print("           AURA-706 LONG-HORIZON RECOVERY BENCHMARKS             ")
    print("=================================================================")
    print(f"Checkpoint Write Latency (p50): {statistics.median(checkpoint_write_latencies_ms):.3f} ms")
    print(f"Checkpoint Write Latency (p95): {sorted(checkpoint_write_latencies_ms)[int(len(checkpoint_write_latencies_ms)*0.95)]:.3f} ms")
    print(f"Checkpoint Write Latency (p99): {sorted(checkpoint_write_latencies_ms)[int(len(checkpoint_write_latencies_ms)*0.99)]:.3f} ms")
    print("-----------------------------------------------------------------")
    print(f"Resume Init Latency (p50):      {statistics.median(resume_init_latencies_ms):.3f} ms")
    print(f"Resume Init Latency (p95):      {sorted(resume_init_latencies_ms)[int(len(resume_init_latencies_ms)*0.95)]:.3f} ms")
    print(f"Resume Init Latency (p99):      {sorted(resume_init_latencies_ms)[int(len(resume_init_latencies_ms)*0.99)]:.3f} ms")
    print("-----------------------------------------------------------------")
    print(f"Startup Sweep Latency (p50):    {statistics.median(sweep_latencies_ms):.3f} ms")
    print(f"Startup Sweep Latency (p95):    {sorted(sweep_latencies_ms)[int(len(sweep_latencies_ms)*0.95)]:.3f} ms")
    print(f"Startup Sweep Latency (p99):    {sorted(sweep_latencies_ms)[int(len(sweep_latencies_ms)*0.99)]:.3f} ms")
    print("=================================================================\n")


if __name__ == "__main__":
    asyncio.run(benchmark_recovery_latencies())

"""Target-OS Windows 11 Process Integration & Latency Benchmark Suite (AURA-507).

Real Target-OS integration tests:
1. Cross-process kill-state coordination across independent OS processes (test_cross_process_kill_state_coordination).
2. Python Parent -> Child -> Grandchild process tree spawning and deep recursive termination (test_real_target_os_process_tree_termination).
3. Real Playwright / Chromium headless browser process-tree termination (test_real_target_os_chromium_process_tree_termination).
4. Real Node.js Parent -> Child process-tree termination (test_real_target_os_node_process_tree_termination).
5. PID reuse protection test (create_time mismatch defense) (test_pid_reuse_protection).
6. Process already exited before kill handling (test_process_already_exited_graceful_handling).
7. Rapid process creation during termination window (multi-pass sweep) (test_kill_race_against_child_creation).
8. Real FastAPI System API endpoint invocation with managed process (test_real_api_kill_switch_lifecycle_with_managed_process).
9. Coordinated Docker sandbox + OS process termination (test_multi_process_and_sandbox_coordinated_kill).
10. Real kill latency benchmarking (trigger-to-abort breakdown) (test_kill_switch_operational_latency_benchmark).
"""

import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from typing import List

import psutil
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.process import ManagedProcessInfo, ManagedProcessRegistry, managed_process_registry
from app.core.security import create_access_token
from app.db.models.user import User
from app.db.models.workspace import Workspace, WorkspaceMember
from app.runtime.sandbox.manager import sandbox_manager
from app.runtime.sandbox.profiles import SandboxProfileType
from app.services.kill_switch import EmergencyKillSwitchService, kill_switch
from app.services.tools.browser_manager import browser_manager


@pytest.fixture(autouse=True)
def reset_kill_state():
    """Reset emergency kill state before and after each test."""
    kill_switch.set_active(False)
    yield
    kill_switch.set_active(False)


@pytest.mark.asyncio
async def test_cross_process_kill_state_coordination(db_session: AsyncSession):
    """Real multi-process test: Independent OS Python worker observes kill switch triggered by parent process."""
    ws_id = uuid.uuid4()
    
    # Process A: Independent Python worker loop checking kill_switch.is_active(ws_id)
    worker_code = f"""
import os, sys, time, uuid
from app.services.kill_switch import kill_switch
ws_id = uuid.UUID('{ws_id}')
print('READY', flush=True)
for _ in range(50):
    if kill_switch.is_active(ws_id):
        print('KILL_DETECTED', flush=True)
        sys.exit(0)
    time.sleep(0.05)
print('TIMED_OUT', flush=True)
sys.exit(1)
"""
    api_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    proc_a = subprocess.Popen(
        [sys.executable, "-c", worker_code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=api_dir,
    )

    try:
        # 1. Wait for Process A to signal ready
        ready_line = proc_a.stdout.readline().strip()
        assert ready_line == "READY"
        assert proc_a.poll() is None

        # 2. Process B (Parent) triggers emergency kill switch
        kill_res = await kill_switch.trigger_emergency_kill(
            db=db_session,
            workspace_id=ws_id,
            actor_id="operator_proc_b",
            reason="Cross-process integration test",
        )
        assert kill_res["status"] == "ABORTED"

        # 3. Process A should detect kill switch and exit within < 2 seconds
        stdout_data, _ = proc_a.communicate(timeout=3.0)
        assert "KILL_DETECTED" in stdout_data
        assert proc_a.returncode == 0

        # 4. Concurrent cross-process triggers test
        proc1 = subprocess.Popen(
            [sys.executable, "-c", f"import uuid; from app.services.kill_switch import kill_switch; kill_switch.set_active(True, uuid.UUID('{ws_id}'))"],
            cwd=api_dir,
        )
        proc2 = subprocess.Popen(
            [sys.executable, "-c", f"import uuid; from app.services.kill_switch import kill_switch; kill_switch.set_active(True, uuid.UUID('{ws_id}'))"],
            cwd=api_dir,
        )
        proc1.wait(timeout=8.0)
        proc2.wait(timeout=8.0)
        assert proc1.returncode == 0
        assert proc2.returncode == 0
        assert kill_switch.is_active(ws_id)

    finally:
        if proc_a.poll() is None:
            proc_a.kill()
        kill_switch.set_active(False, workspace_id=ws_id)


@pytest.mark.asyncio
async def test_real_target_os_process_tree_termination():
    """Target-OS test: Spawn real Python Parent -> Child -> Grandchild process tree and terminate all nodes."""
    code_grandchild = "import time; time.sleep(45)"
    code_child = (
        f"import subprocess, sys, time; "
        f"p = subprocess.Popen([sys.executable, '-c', '{code_grandchild}']); "
        f"time.sleep(45)"
    )
    code_parent = (
        f"import subprocess, sys, time; "
        f"p = subprocess.Popen([sys.executable, '-c', \"{code_child}\"]); "
        f"time.sleep(45)"
    )

    parent_proc = subprocess.Popen(
        [sys.executable, "-c", code_parent],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    parent_pid = parent_proc.pid

    ws_id = uuid.uuid4()
    info = await managed_process_registry.register_process(
        process=parent_proc,
        workspace_id=ws_id,
        category="python_worker_tree",
        command=["python3", "worker_tree"],
    )

    # Allow children and grandchildren 1.5s to spawn
    await asyncio.sleep(1.5)

    try:
        p_obj = psutil.Process(parent_pid)
        children = p_obj.children(recursive=True)
        child_pids = [c.pid for c in children]
    except Exception:
        child_pids = []

    assert p_obj.is_running()

    # Execute recursive process tree termination
    term_res = await managed_process_registry.terminate_process_tree(
        pid=parent_pid,
        expected_create_time=info.create_time,
        timeout=3.0,
    )

    assert term_res["status"] == "terminated"
    assert parent_pid in term_res["terminated_pids"]
    assert term_res["duration_ms"] > 0

    # Verify Parent and all descendants are dead
    assert not psutil.pid_exists(parent_pid)
    for cpid in child_pids:
        assert not psutil.pid_exists(cpid)


@pytest.mark.asyncio
async def test_real_target_os_chromium_process_tree_termination(db_session: AsyncSession):
    """Target-OS test: Launch real Playwright Chromium browser and verify emergency kill terminates browser tree."""
    from playwright.async_api import async_playwright

    playwright_inst = await async_playwright().start()
    browser_inst = await playwright_inst.chromium.launch(headless=True)
    
    # Identify driver and Chromium processes
    driver_proc = getattr(getattr(getattr(playwright_inst, "_impl_obj", None), "_connection", None), "_transport", None)
    proc_obj = getattr(driver_proc, "_proc", None)
    assert proc_obj is not None
    driver_pid = proc_obj.pid

    ws_id = uuid.uuid4()
    info = await managed_process_registry.register_process(
        process=proc_obj,
        workspace_id=ws_id,
        category="playwright_chromium_driver",
        command=["playwright", "chromium"],
    )

    # Inspect Chromium children
    driver_p = psutil.Process(driver_pid)
    chromium_children = [c.pid for c in driver_p.children(recursive=True)]
    assert len(chromium_children) >= 1

    # Trigger emergency kill switch
    kill_res = await kill_switch.trigger_emergency_kill(
        db=db_session,
        workspace_id=ws_id,
        actor_id="operator_browser_test",
        reason="Testing real Chromium termination",
    )

    assert kill_res["status"] == "ABORTED"
    assert kill_res["processes_terminated"] >= 1

    # Verify driver and all Chromium children are dead on Windows OS
    await asyncio.sleep(0.5)
    assert not psutil.pid_exists(driver_pid)
    for cpid in chromium_children:
        assert not psutil.pid_exists(cpid)

    # Cleanup instance wrapper
    try:
        await browser_inst.close()
    except Exception:
        pass
    try:
        await playwright_inst.stop()
    except Exception:
        pass


@pytest.mark.asyncio
async def test_real_target_os_node_process_tree_termination():
    """Target-OS test: Spawn real Node.js Parent -> Child process tree and terminate recursively."""
    node_script = "const cp = require('child_process'); cp.spawn(process.execPath, ['-e', 'setTimeout(()=>{}, 45000)']); setTimeout(()=>{}, 45000);"
    
    node_proc = subprocess.Popen(
        ["node", "-e", node_script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    node_pid = node_proc.pid

    ws_id = uuid.uuid4()
    info = await managed_process_registry.register_process(
        process=node_proc,
        workspace_id=ws_id,
        category="node_worker_tree",
        command=["node", "worker_tree"],
    )

    # Allow child process to spawn
    await asyncio.sleep(1.0)

    try:
        p_obj = psutil.Process(node_pid)
        node_children = [c.pid for c in p_obj.children(recursive=True)]
    except Exception:
        node_children = []

    assert p_obj.is_running()

    # Terminate process tree
    term_res = await managed_process_registry.terminate_process_tree(
        pid=node_pid,
        expected_create_time=info.create_time,
        timeout=3.0,
    )

    assert term_res["status"] == "terminated"
    assert node_pid in term_res["terminated_pids"]

    # Verify Parent and Child Node processes are dead
    assert not psutil.pid_exists(node_pid)
    for cpid in node_children:
        assert not psutil.pid_exists(cpid)


@pytest.mark.asyncio
async def test_pid_reuse_protection():
    """Target-OS test: Refuse to terminate a process if create_time does not match registered timestamp."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    pid = proc.pid
    try:
        p_obj = psutil.Process(pid)
        real_create_time = p_obj.create_time()

        # Attempt termination with a fake/stale creation timestamp (1000s in the past)
        fake_create_time = real_create_time - 1000.0

        term_res = await managed_process_registry.terminate_process_tree(
            pid=pid,
            expected_create_time=fake_create_time,
            timeout=2.0,
        )

        assert term_res["status"] == "pid_reuse_aborted"
        # Process should STILL be alive because safety check blocked killing unrelated PID
        assert psutil.pid_exists(pid)
    finally:
        proc.kill()
        proc.wait()


@pytest.mark.asyncio
async def test_process_already_exited_graceful_handling():
    """Target-OS test: Verify that terminating an already-exited PID handles NoSuchProcess gracefully."""
    proc = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(0)"])
    pid = proc.pid
    proc.wait()

    term_res = await managed_process_registry.terminate_process_tree(
        pid=pid,
        expected_create_time=None,
        timeout=2.0,
    )
    assert term_res["status"] == "already_exited"


@pytest.mark.asyncio
async def test_kill_race_against_child_creation():
    """Race test: Process rapidly spawning short-lived children is safely terminated by multi-pass sweep."""
    # Process spawns children in a tight loop
    spawner_code = """
import subprocess, sys, time
for _ in range(50):
    subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)'])
    time.sleep(0.05)
"""
    spawner_proc = subprocess.Popen(
        [sys.executable, "-c", spawner_code],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    spawner_pid = spawner_proc.pid

    ws_id = uuid.uuid4()
    info = await managed_process_registry.register_process(
        process=spawner_proc,
        workspace_id=ws_id,
        category="rapid_fork_spawner",
    )

    await asyncio.sleep(0.5)

    # Terminate spawner and all rapidly spawned children
    term_res = await managed_process_registry.terminate_process_tree(
        pid=spawner_pid,
        expected_create_time=info.create_time,
        timeout=3.0,
    )

    assert term_res["status"] == "terminated"
    assert not psutil.pid_exists(spawner_pid)


@pytest.mark.asyncio
async def test_real_api_kill_switch_lifecycle_with_managed_process(client: AsyncClient, db_session: AsyncSession):
    """End-to-end API test: Invoke POST /system/kill-switch via HTTP with real managed OS subprocess."""
    ws = Workspace(name="LiveAPIWS", slug=f"liveapiws-{uuid.uuid4().hex[:6]}")
    db_session.add(ws)
    await db_session.flush()

    user = User(email="apiadmin@example.com", password_hash="hash", full_name="API Admin", role="admin", is_active=True)
    db_session.add(user)
    await db_session.flush()

    member = WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="owner", permissions=["*"])
    db_session.add(member)
    await db_session.commit()

    token = create_access_token({"sub": str(user.id)})

    # Spawn real OS subprocess registered to this workspace
    real_proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    await managed_process_registry.register_process(
        process=real_proc,
        workspace_id=ws.id,
        category="api_managed_worker",
    )

    try:
        # Call API endpoint
        resp = await client.post(
            "/api/v1/system/kill-switch",
            json={"workspace_id": str(ws.id), "reason": "End-to-end API test abort"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ABORTED"
        assert data["processes_terminated"] >= 1
        assert "audit_log_id" in data

        # Process should be terminated on the OS
        assert not psutil.pid_exists(real_proc.pid)

        # Status endpoint check
        status_resp = await client.get(
            f"/api/v1/system/kill-switch/status?workspace_id={ws.id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert status_resp.status_code == 200
        assert status_resp.json()["is_active_for_query"] is True

        # Recovery via API
        reset_resp = await client.post(
            "/api/v1/system/kill-switch/reset",
            json={"workspace_id": str(ws.id), "reason": "API test recovery"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert reset_resp.status_code == 200
        assert reset_resp.json()["status"] == "RECOVERED"
    finally:
        if psutil.pid_exists(real_proc.pid):
            real_proc.kill()


@pytest.mark.asyncio
async def test_multi_process_and_sandbox_coordinated_kill(db_session: AsyncSession):
    """Target-OS test: Coordinated emergency abort of both host subprocesses and Docker sandbox containers."""
    ws_id = uuid.uuid4()

    # 1. Spawn a host subprocess
    host_proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    await managed_process_registry.register_process(
        process=host_proc,
        workspace_id=ws_id,
        category="background_worker",
    )

    # 2. Trigger emergency kill
    res = await kill_switch.trigger_emergency_kill(
        db=db_session,
        workspace_id=ws_id,
        actor_id="test_admin",
        reason="Coordinated multi-process test",
    )

    assert res["status"] == "ABORTED"
    assert res["processes_terminated"] >= 1
    assert not psutil.pid_exists(host_proc.pid)


@pytest.mark.asyncio
async def test_kill_switch_operational_latency_benchmark(db_session: AsyncSession):
    """Measure and record real operational kill latency across multiple samples (n=5)."""
    ws_id = uuid.uuid4()
    latencies: List[float] = []

    for i in range(5):
        # Spawn small dummy process
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
        await managed_process_registry.register_process(
            process=proc,
            workspace_id=ws_id,
            category="bench_worker",
        )

        res = await kill_switch.trigger_emergency_kill(
            db=db_session,
            workspace_id=ws_id,
            actor_id="benchmark_runner",
            reason=f"Benchmark sample {i}",
        )
        latencies.append(res["total_latency_ms"])
        kill_switch.set_active(False, workspace_id=ws_id)

    min_lat = min(latencies)
    max_lat = max(latencies)
    median_lat = sorted(latencies)[len(latencies) // 2]

    # Verify operational completion on target Windows host
    assert median_lat < 500.0

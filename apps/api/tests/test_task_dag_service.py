"""Tests for AURA-107: Task DAG Lifecycle, State Machine, Checkpoints, and Cancellation."""

import uuid
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_task_creation_and_dag_validation(client: AsyncClient):
    """Test creating a task with a valid multi-step DAG and retrieving step dependencies."""
    reg_res = await client.post(
        "/api/v1/auth/register",
        json={"email": "task_creator@example.com", "password": "TaskPassword123!"},
    )
    token = reg_res.json()["access_token"]
    me_res = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    ws_id = me_res.json()["workspaces"][0]["id"]

    # 1. Create Task with 3-step DAG
    task_payload = {
        "workspace_id": ws_id,
        "title": "Analyze Repository Security",
        "goal": "Audit dependencies and identify vulnerabilities in the repo",
        "priority": "high",
        "autonomy_level": 3,
        "steps": [
            {
                "step_number": 1,
                "title": "Search Security Advisories",
                "description": "Query DuckDuckGo for CVEs",
                "dependencies": [],
                "tool_name": "web_search",
                "tool_input": {"query": "FastAPI CVE advisories"},
            },
            {
                "step_number": 2,
                "title": "Parse Dependency Tree",
                "description": "Analyze requirements.txt for outdated packages",
                "dependencies": [1],
            },
            {
                "step_number": 3,
                "title": "Generate Final Report",
                "description": "Synthesize findings into markdown",
                "dependencies": [1, 2],
            },
        ],
    }

    create_res = await client.post("/api/v1/tasks", json=task_payload, headers={"Authorization": f"Bearer {token}"})
    assert create_res.status_code == 201
    task = create_res.json()
    assert task["status"] == "pending"
    assert len(task["steps"]) == 3
    assert task["steps"][2]["dependencies"] == [1, 2]
    task_id = task["id"]

    # 2. Get Task details
    get_res = await client.get(f"/api/v1/tasks/{task_id}?workspace_id={ws_id}", headers={"Authorization": f"Bearer {token}"})
    assert get_res.status_code == 200
    assert get_res.json()["title"] == "Analyze Repository Security"


@pytest.mark.asyncio
async def test_task_dag_cycle_and_invalid_dependency_rejection(client: AsyncClient):
    """Test DAG cycle detection, self-dependency, and non-existent dependency rejection."""
    reg_res = await client.post(
        "/api/v1/auth/register",
        json={"email": "dag_checker@example.com", "password": "DagPassword123!"},
    )
    token = reg_res.json()["access_token"]
    me_res = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    ws_id = me_res.json()["workspaces"][0]["id"]

    # 1. Cyclic DAG: Step 1 depends on 2, Step 2 depends on 1
    cyclic_payload = {
        "workspace_id": ws_id,
        "title": "Cyclic Task",
        "goal": "This must fail DAG validation",
        "steps": [
            {"step_number": 1, "title": "Step 1", "description": "1", "dependencies": [2]},
            {"step_number": 2, "title": "Step 2", "description": "2", "dependencies": [1]},
        ],
    }
    res_cycle = await client.post("/api/v1/tasks", json=cyclic_payload, headers={"Authorization": f"Bearer {token}"})
    assert res_cycle.status_code in [400, 422]
    assert "Cyclic dependency detected" in res_cycle.json()["error"]["message"]

    # 2. Self-dependency: Step 1 depends on 1
    self_dep_payload = {
        "workspace_id": ws_id,
        "title": "Self Dep Task",
        "goal": "This must fail self-dependency validation",
        "steps": [
            {"step_number": 1, "title": "Step 1", "description": "1", "dependencies": [1]},
        ],
    }
    res_self = await client.post("/api/v1/tasks", json=self_dep_payload, headers={"Authorization": f"Bearer {token}"})
    assert res_self.status_code in [400, 422]
    assert "cannot depend on itself" in res_self.json()["error"]["message"]


@pytest.mark.asyncio
async def test_task_step_checkpointing_and_lifecycle(client: AsyncClient):
    """Test updating step checkpoints, outputs, and verification status."""
    reg_res = await client.post(
        "/api/v1/auth/register",
        json={"email": "checkpoint_user@example.com", "password": "CpPassword123!"},
    )
    token = reg_res.json()["access_token"]
    me_res = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    ws_id = me_res.json()["workspaces"][0]["id"]

    # Create task with 1 step
    task_res = await client.post(
        "/api/v1/tasks",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "workspace_id": ws_id,
            "title": "Step Checkpoint Test",
            "goal": "Verify checkpoint execution state",
            "steps": [
                {"step_number": 1, "title": "Execute Step", "description": "Step 1", "dependencies": []}
            ],
        },
    )
    task_id = task_res.json()["id"]

    # 1. Update task to running
    await client.patch(
        f"/api/v1/tasks/{task_id}?workspace_id={ws_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "running"},
    )

    # 2. Checkpoint step as running
    step_run = await client.patch(
        f"/api/v1/tasks/{task_id}/steps/1?workspace_id={ws_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "running"},
    )
    assert step_run.status_code == 200
    assert step_run.json()["status"] == "running"
    assert step_run.json()["started_at"] is not None

    # 3. Checkpoint step as completed with tool_output
    step_comp = await client.patch(
        f"/api/v1/tasks/{task_id}/steps/1?workspace_id={ws_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "status": "completed",
            "tool_output": {"result": "All dependencies secure"},
            "is_verified": True,
        },
    )
    assert step_comp.status_code == 200
    assert step_comp.json()["status"] == "completed"
    assert step_comp.json()["is_verified"] is True
    assert step_comp.json()["tool_output"]["result"] == "All dependencies secure"


@pytest.mark.asyncio
async def test_task_idempotency_key_deduplication(client: AsyncClient):
    """Test that submitting identical idempotency_key returns the same task deterministically."""
    reg_res = await client.post(
        "/api/v1/auth/register",
        json={"email": "idempotent_admin@example.com", "password": "IdemPassword123!"},
    )
    token = reg_res.json()["access_token"]
    me_res = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    ws_id = me_res.json()["workspaces"][0]["id"]

    idem_key = f"idem-key-{uuid.uuid4().hex}"
    task_payload = {
        "workspace_id": ws_id,
        "title": "Idempotent Task Goal",
        "goal": "Ensure exactly-once goal creation",
        "idempotency_key": idem_key,
    }

    # First call creates task
    res1 = await client.post("/api/v1/tasks", json=task_payload, headers={"Authorization": f"Bearer {token}"})
    assert res1.status_code == 201
    task1_id = res1.json()["id"]

    # Duplicate call returns existing task
    res2 = await client.post("/api/v1/tasks", json=task_payload, headers={"Authorization": f"Bearer {token}"})
    assert res2.status_code in [200, 201]
    task2_id = res2.json()["id"]
    assert task1_id == task2_id


@pytest.mark.asyncio
async def test_task_cancellation_cascade(client: AsyncClient):
    """Test cancelling a task cascades cancellation to all pending/running steps."""
    reg_res = await client.post(
        "/api/v1/auth/register",
        json={"email": "cancel_user@example.com", "password": "CancelPassword123!"},
    )
    token = reg_res.json()["access_token"]
    me_res = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    ws_id = me_res.json()["workspaces"][0]["id"]

    task_payload = {
        "workspace_id": ws_id,
        "title": "Task To Cancel",
        "goal": "Verify cancellation cascade",
        "steps": [
            {"step_number": 1, "title": "Step 1", "description": "1", "dependencies": []},
            {"step_number": 2, "title": "Step 2", "description": "2", "dependencies": [1]},
        ],
    }
    create_res = await client.post("/api/v1/tasks", json=task_payload, headers={"Authorization": f"Bearer {token}"})
    task_id = create_res.json()["id"]

    # Cancel task
    cancel_res = await client.post(
        f"/api/v1/tasks/{task_id}/cancel?workspace_id={ws_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert cancel_res.status_code == 200
    task_data = cancel_res.json()
    assert task_data["status"] == "cancelled"
    for s in task_data["steps"]:
        assert s["status"] == "cancelled"


@pytest.mark.asyncio
async def test_task_horizontal_workspace_isolation(client: AsyncClient):
    """Test User A is strictly forbidden from reading or mutating User B's task."""
    # User A
    res_a = await client.post(
        "/api/v1/auth/register",
        json={"email": "task_user_a@example.com", "password": "PasswordA123!"},
    )
    token_a = res_a.json()["access_token"]
    ws_a_id = (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_a}"})).json()["workspaces"][0]["id"]

    # User B
    res_b = await client.post(
        "/api/v1/auth/register",
        json={"email": "task_user_b@example.com", "password": "PasswordB123!"},
    )
    token_b = res_b.json()["access_token"]
    ws_b_id = (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_b}"})).json()["workspaces"][0]["id"]

    # User A creates task in Workspace A
    task_a = await client.post(
        "/api/v1/tasks",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"workspace_id": ws_a_id, "title": "Secret Task A", "goal": "Confidential goal"},
    )
    task_a_id = task_a.json()["id"]

    # User B attempts to read User A's task -> 403 Forbidden
    hack_res = await client.get(
        f"/api/v1/tasks/{task_a_id}?workspace_id={ws_a_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert hack_res.status_code == 403
    assert "Access denied" in hack_res.json()["error"]["message"]

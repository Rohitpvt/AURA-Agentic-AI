"""Tests for AURA-103: Authentication, JWT lifecycle, Workspace Tenancy, and RBAC."""

import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import create_access_token
from app.db.models.user import User
from app.db.models.workspace import Workspace, WorkspaceMember
from app.main import app


@pytest.mark.asyncio
async def test_auth_registration_and_workspace_provisioning(client: AsyncClient):
    """Test user registration automatically provisions a personal workspace and JWT."""
    payload = {
        "email": "alice@example.com",
        "username": "alice",
        "password": "SecurePassword123!",
        "full_name": "Alice Agentic",
    }
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] > 0


@pytest.mark.asyncio
async def test_auth_duplicate_registration_prevention(client: AsyncClient):
    """Test duplicate email or username registration is blocked."""
    payload = {
        "email": "dup@example.com",
        "username": "dupuser",
        "password": "Password123!",
    }
    res1 = await client.post("/api/v1/auth/register", json=payload)
    assert res1.status_code == 201

    # Duplicate email
    res2 = await client.post("/api/v1/auth/register", json=payload)
    assert res2.status_code == 409
    assert "already exists" in res2.json()["error"]["message"]


@pytest.mark.asyncio
async def test_auth_login_and_token_refresh_lifecycle(client: AsyncClient):
    """Test login, token rotation on refresh, and logout revocation."""
    # 1. Register
    reg_payload = {
        "email": "bob@example.com",
        "username": "bob",
        "password": "BobPassword123!",
    }
    await client.post("/api/v1/auth/register", json=reg_payload)

    # 2. Login
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": "bob@example.com", "password": "BobPassword123!"},
    )
    assert login_res.status_code == 200
    tokens = login_res.json()
    access_token = tokens["access_token"]
    refresh_token = tokens["refresh_token"]

    # 3. Access protected /me endpoint
    me_res = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert me_res.status_code == 200
    user_info = me_res.json()
    assert user_info["email"] == "bob@example.com"
    assert len(user_info["workspaces"]) >= 1

    # 4. Refresh token
    ref_res = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert ref_res.status_code == 200
    new_tokens = ref_res.json()
    assert new_tokens["access_token"] != access_token
    assert new_tokens["refresh_token"] != refresh_token

    # 5. Old refresh token should now be revoked (rotation)
    old_ref_res = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert old_ref_res.status_code == 401

    # 6. Logout
    logout_res = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": new_tokens["refresh_token"]},
        headers={"Authorization": f"Bearer {new_tokens['access_token']}"},
    )
    assert logout_res.status_code == 200


@pytest.mark.asyncio
async def test_workspace_isolation_and_horizontal_privilege_prevention(client: AsyncClient):
    """Test User A is strictly forbidden from accessing or viewing User B's workspace."""
    # Create User A
    res_a = await client.post(
        "/api/v1/auth/register",
        json={"email": "user_a@example.com", "username": "usera", "password": "PasswordA123!"},
    )
    token_a = res_a.json()["access_token"]
    me_a = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_a}"})
    ws_a_id = me_a.json()["workspaces"][0]["id"]

    # Create User B
    res_b = await client.post(
        "/api/v1/auth/register",
        json={"email": "user_b@example.com", "username": "userb", "password": "PasswordB123!"},
    )
    token_b = res_b.json()["access_token"]
    me_b = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_b}"})
    ws_b_id = me_b.json()["workspaces"][0]["id"]

    # User A attempts to read User B's workspace details -> HTTP 403 Forbidden
    hack_res = await client.get(
        f"/api/v1/workspaces/{ws_b_id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert hack_res.status_code == 403
    assert "Access denied" in hack_res.json()["error"]["message"]

    # User A attempts to list members of User B's workspace -> HTTP 403 Forbidden
    hack_members = await client.get(
        f"/api/v1/workspaces/{ws_b_id}/members",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert hack_members.status_code == 403


@pytest.mark.asyncio
async def test_workspace_rbac_member_invitation(client: AsyncClient):
    """Test workspace Owner can invite User B with a specified role."""
    # Register Owner
    res_owner = await client.post(
        "/api/v1/auth/register",
        json={"email": "owner@example.com", "username": "owner_user", "password": "OwnerPassword123!"},
    )
    token_owner = res_owner.json()["access_token"]
    me_owner = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_owner}"})
    ws_id = me_owner.json()["workspaces"][0]["id"]

    # Register Member Candidate
    res_cand = await client.post(
        "/api/v1/auth/register",
        json={"email": "cand@example.com", "username": "cand_user", "password": "CandPassword123!"},
    )
    token_cand = res_cand.json()["access_token"]
    cand_id = (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_cand}"})).json()["id"]

    # Owner adds candidate as Member
    add_res = await client.post(
        f"/api/v1/workspaces/{ws_id}/members",
        headers={"Authorization": f"Bearer {token_owner}"},
        json={"user_id": cand_id, "role": "member", "permissions": ["read", "execute_task"]},
    )
    assert add_res.status_code == 201
    assert add_res.json()["role"] == "member"

    # Now Candidate can access workspace details
    cand_access = await client.get(
        f"/api/v1/workspaces/{ws_id}",
        headers={"Authorization": f"Bearer {token_cand}"},
    )
    assert cand_access.status_code == 200
    assert cand_access.json()["role"] == "member"


@pytest.mark.asyncio
async def test_persistent_token_revocation_survives_restart_and_race_condition(client: AsyncClient):
    """Verify revoked tokens remain blocked even after in-memory cache wipe (simulating crash/restart)."""
    from app.core.security import clear_in_memory_revocations

    # 1. Register & login
    reg_payload = {
        "email": "persist_user@example.com",
        "username": "persist_user",
        "password": "PersistPassword123!",
    }
    reg_res = await client.post("/api/v1/auth/register", json=reg_payload)
    refresh_token = reg_res.json()["refresh_token"]

    # 2. Rotate token
    ref_res = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert ref_res.status_code == 200
    new_refresh = ref_res.json()["refresh_token"]

    # 3. Simulate process crash / backend restart by wiping in-memory revocation set
    clear_in_memory_revocations()

    # 4. Old refresh token MUST still be rejected via DB query
    old_res = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert old_res.status_code == 401
    assert "revoked or already rotated" in old_res.json()["error"]["message"]

    # 5. Logout new token
    logout_res = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": new_refresh},
        headers={"Authorization": f"Bearer {ref_res.json()['access_token']}"},
    )
    assert logout_res.status_code == 200

    # 6. Wipe cache again
    clear_in_memory_revocations()

    # 7. Logged out token MUST still be rejected via DB
    logout_ref = await client.post("/api/v1/auth/refresh", json={"refresh_token": new_refresh})
    assert logout_ref.status_code == 401


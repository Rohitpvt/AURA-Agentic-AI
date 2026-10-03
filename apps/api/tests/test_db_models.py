"""Database model unit and integration tests."""

import uuid
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    compute_sha256_hash,
    get_password_hash,
    sign_approval_payload,
    verify_approval_signature,
    verify_password,
)
from app.db.models import (
    AgentRun,
    ApprovalRequest,
    AuditLog,
    Automation,
    Integration,
    MemoryRecord,
    Message,
    Session,
    Skill,
    SkillVersion,
    SubAgentRun,
    Task,
    TaskStep,
    Tool,
    ToolPermission,
    User,
    Workspace,
    WorkspaceMember,
)


@pytest.mark.asyncio
async def test_user_and_workspace_creation(db_session: AsyncSession):
    """Test creating user, workspace, and association."""
    # 1. Create Workspace
    workspace = Workspace(
        name="Primary Development Workspace",
        slug="dev-workspace",
        description="Local personal agentic workspace",
        settings={"theme": "dark", "autonomy_level": 2},
    )
    db_session.add(workspace)
    await db_session.flush()

    assert workspace.id is not None
    assert workspace.slug == "dev-workspace"
    assert workspace.is_deleted is False

    # 2. Create User
    hashed_pwd = get_password_hash("SuperSecret123!")
    user = User(
        email="architect@aura.local",
        password_hash=hashed_pwd,
        full_name="Lead Architect",
        role="owner",
    )
    db_session.add(user)
    await db_session.flush()

    assert user.id is not None
    assert verify_password("SuperSecret123!", user.password_hash) is True

    # 3. Create Workspace Member
    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
        permissions=["admin", "tools:execute", "approvals:resolve"],
    )
    db_session.add(member)
    await db_session.commit()

    # Query back
    result = await db_session.execute(select(Workspace).where(Workspace.slug == "dev-workspace"))
    loaded_ws = result.scalar_one()
    assert loaded_ws.name == "Primary Development Workspace"


@pytest.mark.asyncio
async def test_session_and_messages(db_session: AsyncSession):
    """Test conversational session and verbatim message creation."""
    ws = Workspace(name="WS1", slug="ws-1")
    user = User(email="user1@aura.local", password_hash="hash", full_name="User One")
    db_session.add_all([ws, user])
    await db_session.flush()

    session = Session(
        workspace_id=ws.id,
        user_id=user.id,
        title="Architecture Discussion",
        channel="web",
    )
    db_session.add(session)
    await db_session.flush()

    msg1 = Message(
        session_id=session.id,
        workspace_id=ws.id,
        sender_type="user",
        role="user",
        content="Plan an automated codebase audit",
        tokens_consumed=15,
    )
    msg2 = Message(
        session_id=session.id,
        workspace_id=ws.id,
        sender_type="agent",
        role="assistant",
        content="I will decompose this into 3 steps.",
        tokens_consumed=25,
        model_name="qwen2.5:7b-instruct-q4_K_M",
    )
    db_session.add_all([msg1, msg2])
    await db_session.commit()

    # Verify messages
    result = await db_session.execute(
        select(Message).where(Message.session_id == session.id).order_by(Message.created_at.asc())
    )
    messages = result.scalars().all()
    assert len(messages) == 2
    assert messages[0].content == "Plan an automated codebase audit"
    assert messages[1].model_name == "qwen2.5:7b-instruct-q4_K_M"


@pytest.mark.asyncio
async def test_task_dag_and_agent_run(db_session: AsyncSession):
    """Test multi-step task creation with steps and subagent delegation."""
    ws = Workspace(name="WS Task", slug="ws-task")
    db_session.add(ws)
    await db_session.flush()

    # Create Task
    task = Task(
        workspace_id=ws.id,
        title="Audit Repository",
        goal="Perform security scan and linting on workspace files",
        status="executing",
        autonomy_level=2,
        idempotency_key="idemp-" + str(uuid.uuid4()),
    )
    db_session.add(task)
    await db_session.flush()

    # Create DAG Steps
    step1 = TaskStep(
        task_id=task.id,
        step_number=1,
        title="List Files",
        description="Inspect directory structure",
        status="completed",
        tool_name="list_dir",
        tool_output={"files_found": 42},
        is_verified=True,
    )
    step2 = TaskStep(
        task_id=task.id,
        step_number=2,
        title="Scan Dependencies",
        description="Check package manifest for vulnerabilities",
        dependencies=[1],
        status="pending",
    )
    db_session.add_all([step1, step2])

    # Create AgentRun
    agent_run = AgentRun(
        task_id=task.id,
        workspace_id=ws.id,
        agent_type="master_supervisor",
        model_name="qwen2.5:7b-instruct-q4_K_M",
        model_tier="general",
        status="running",
    )
    db_session.add(agent_run)
    await db_session.flush()

    # Create SubAgentRun
    subagent = SubAgentRun(
        parent_run_id=agent_run.id,
        task_id=task.id,
        role="researcher",
        goal="Fetch CVEs for dependencies",
        assigned_budget_tokens=4000,
        depth_level=1,
    )
    db_session.add(subagent)
    await db_session.commit()

    # Query steps
    res = await db_session.execute(
        select(TaskStep).where(TaskStep.task_id == task.id).order_by(TaskStep.step_number.asc())
    )
    steps = res.scalars().all()
    assert len(steps) == 2
    assert steps[0].is_verified is True
    assert steps[1].dependencies == [1]


@pytest.mark.asyncio
async def test_approval_request_and_cryptographic_token(db_session: AsyncSession):
    """Test Human-in-the-Loop approval request and HMAC-SHA256 signature."""
    ws = Workspace(name="WS Approval", slug="ws-approval")
    db_session.add(ws)
    await db_session.flush()

    task = Task(workspace_id=ws.id, title="Deploy Hotfix", goal="Push code to git main")
    db_session.add(task)
    await db_session.flush()

    agent_run = AgentRun(
        task_id=task.id,
        workspace_id=ws.id,
        model_name="qwen2.5:7b",
    )
    db_session.add(agent_run)
    await db_session.flush()

    payload = {
        "task_id": str(task.id),
        "tool_name": "git_push",
        "params": {"branch": "main", "remote": "origin"},
    }
    signature = sign_approval_payload(payload)
    assert verify_approval_signature(payload, signature) is True

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    approval = ApprovalRequest(
        workspace_id=ws.id,
        task_id=task.id,
        agent_run_id=agent_run.id,
        tool_name="git_push",
        tool_params=payload["params"],
        risk_level="high",
        status="pending",
        approval_token_hash=signature,
        expires_at=expires_at,
    )
    db_session.add(approval)
    await db_session.commit()

    res = await db_session.execute(select(ApprovalRequest).where(ApprovalRequest.id == approval.id))
    loaded = res.scalar_one()
    assert loaded.status == "pending"
    assert loaded.risk_level == "high"


@pytest.mark.asyncio
async def test_audit_log_hash_chaining(db_session: AsyncSession):
    """Test cryptographic SHA-256 hash chaining in audit log."""
    ws = Workspace(name="WS Audit", slug="ws-audit")
    db_session.add(ws)
    await db_session.flush()

    genesis_prev_hash = "0" * 64
    entry1_data = f"{genesis_prev_hash}:tool_executed:user_123"
    entry1_hash = compute_sha256_hash(entry1_data)

    log1 = AuditLog(
        workspace_id=ws.id,
        actor_type="user",
        actor_id="user_123",
        action="tool_executed",
        resource_type="tool",
        resource_id="web_search",
        details={"query": "PostgreSQL 16"},
        previous_log_hash=genesis_prev_hash,
        log_hash=entry1_hash,
    )
    db_session.add(log1)
    await db_session.flush()

    entry2_data = f"{entry1_hash}:approval_granted:user_123"
    entry2_hash = compute_sha256_hash(entry2_data)

    log2 = AuditLog(
        workspace_id=ws.id,
        actor_type="user",
        actor_id="user_123",
        action="approval_granted",
        resource_type="approval",
        resource_id=str(uuid.uuid4()),
        previous_log_hash=entry1_hash,
        log_hash=entry2_hash,
    )
    db_session.add(log2)
    await db_session.commit()

    assert log2.previous_log_hash == log1.log_hash
    assert len(log2.log_hash) == 64


@pytest.mark.asyncio
async def test_memory_record_crud(db_session: AsyncSession):
    """Test cognitive memory record creation and tombstoning."""
    ws = Workspace(name="WS Mem", slug="ws-mem")
    db_session.add(ws)
    await db_session.flush()

    mem = MemoryRecord(
        workspace_id=ws.id,
        category="preference",
        fact_statement="User prefers local-first execution using Ollama Qwen 2.5",
        confidence_score=0.950,
        is_tombstoned=False,
    )
    db_session.add(mem)
    await db_session.commit()

    # Tombstone test
    mem.is_tombstoned = True
    mem.tombstoned_reason = "User updated preference"
    await db_session.commit()

    res = await db_session.execute(select(MemoryRecord).where(MemoryRecord.id == mem.id))
    loaded = res.scalar_one()
    assert loaded.is_tombstoned is True
    assert loaded.confidence_score == 0.950

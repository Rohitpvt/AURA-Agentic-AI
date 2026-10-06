"""
Cross-Phase Recovery Master Audit: Anti-Replay Semantics, State Restoration, and Clean Boot.
"""
import pytest
import uuid

from app.services.kill_switch import kill_switch
from app.services.task_recovery_service import TaskRecoveryService
from app.db.models.task import Task, TaskStep
from app.db.models.workspace import Workspace
from app.db.models.user import User


@pytest.mark.asyncio
async def test_recovery_anti_replay_after_emergency_reset(db_session):
    """
    Recovery Audit: Verify cancelled operations do NOT resurrect or auto-replay when kill switch is reset.
    """
    user_id = uuid.uuid4()
    ws_id = uuid.uuid4()
    task_id = uuid.uuid4()

    u = User(id=user_id, email=f"rec_{str(user_id)[:8]}@test.com", password_hash="pwd", full_name="Anti-Replay User", is_active=True)
    w = Workspace(id=ws_id, name="Anti-Replay WS", slug=f"ar-{ws_id.hex[:8]}")
    t = Task(id=task_id, workspace_id=ws_id, title="Aborted Task", goal="Aborted Goal", status="cancelled")
    db_session.add_all([u, w, t])
    await db_session.flush()

    # Reset kill switch
    kill_switch.set_active(False, ws_id)

    # Attempt to resume task -> Terminal state check preserves cancelled status
    rec_svc = TaskRecoveryService()
    resp = await rec_svc.resume_task(db=db_session, task_id=task_id, workspace_id=ws_id, actor_id="user")
    assert resp.status == "cancelled"

"""API v1 router aggregator."""

from fastapi import APIRouter
from app.api.v1.endpoints.agent import router as agent_router
from app.api.v1.endpoints.approvals import router as approvals_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.credentials import router as credentials_router
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.mcp import router as mcp_router
from app.api.v1.endpoints.memory import router as memory_router
from app.api.v1.endpoints.models import router as models_router
from app.api.v1.endpoints.providers import router as providers_router
from app.api.v1.endpoints.tasks import router as tasks_router
from app.api.v1.endpoints.tools import router as tools_router
from app.api.v1.endpoints.workspaces import router as workspaces_router

from app.api.v1.endpoints.audit import router as audit_router
from app.api.v1.endpoints.automations import router as automations_router
from app.api.v1.endpoints.system import router as system_router
from app.api.v1.endpoints.webhooks import router as webhooks_router
from app.api.v1.endpoints.telegram import router as telegram_router
from app.api.v1.endpoints.telemetry import router as telemetry_router
from app.api.v1.endpoints.files import router as files_router

api_v1_router = APIRouter(prefix="/api/v1")

# Mount endpoints
api_v1_router.include_router(health_router)
api_v1_router.include_router(models_router)
api_v1_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_v1_router.include_router(workspaces_router, prefix="/workspaces", tags=["workspaces"])
api_v1_router.include_router(files_router, prefix="/files", tags=["files"])
api_v1_router.include_router(memory_router, prefix="/memory", tags=["memory"])
api_v1_router.include_router(providers_router, prefix="/providers", tags=["providers"])
api_v1_router.include_router(credentials_router, prefix="/credentials", tags=["credentials"])
api_v1_router.include_router(tools_router, prefix="/tools", tags=["tools"])
api_v1_router.include_router(tasks_router, prefix="/tasks", tags=["tasks"])
api_v1_router.include_router(agent_router, prefix="/agent", tags=["agent"])
api_v1_router.include_router(approvals_router, prefix="/approvals", tags=["approvals"])
api_v1_router.include_router(mcp_router, prefix="/mcp", tags=["mcp"])
api_v1_router.include_router(automations_router, prefix="/automations", tags=["automations"])
api_v1_router.include_router(webhooks_router, prefix="/webhooks", tags=["webhooks"])
api_v1_router.include_router(telegram_router, prefix="/telegram", tags=["telegram"])
api_v1_router.include_router(telemetry_router)
api_v1_router.include_router(audit_router)
api_v1_router.include_router(system_router)



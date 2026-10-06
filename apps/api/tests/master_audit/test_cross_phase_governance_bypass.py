"""
Cross-Phase Governance Bypass Master Audit: Search for Ungoverned Execution Escapes.
"""
import pytest
from app.services.tool_registry import tool_registry
from app.services.os_guard.app_registry import ApplicationRegistry


@pytest.mark.asyncio
async def test_governance_bypass_tool_registry_risk_classifications(db_session):
    """
    Governance Audit: Verify every registered tool has an explicit non-null risk classification and category.
    """
    await tool_registry.ensure_builtin_tools(db_session)
    tools = await tool_registry.list_tools(workspace_id=None, db=db_session)

    assert len(tools) > 0
    for tool in tools:
        assert tool.risk_level in [
            "READ_ONLY", "LOW_RISK_WRITE", "MEDIUM_RISK_INTERACTION",
            "HIGH_RISK_SYSTEM_ACTION", "CRITICAL_ACTION",
            "low", "medium", "high", "critical", "read_only"
        ]


@pytest.mark.asyncio
async def test_governance_bypass_application_registry_lolbins_prohibited():
    """
    Governance Audit: Verify Windows LOLBins cannot be launched through ApplicationRegistry.
    """
    app_reg = ApplicationRegistry()
    prohibited_lolbins = [
        "powershell", "powershell.exe",
        "cmd", "cmd.exe",
        "wscript", "wscript.exe",
        "cscript", "cscript.exe",
        "mshta", "mshta.exe",
        "certutil", "certutil.exe",
        "bitsadmin", "bitsadmin.exe",
        "regsvr32", "regsvr32.exe",
        "rundll32", "rundll32.exe",
    ]

    for bin_name in prohibited_lolbins:
        assert app_reg.get_application(bin_name) is None

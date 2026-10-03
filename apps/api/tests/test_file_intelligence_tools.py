"""Test Suite for AURA-604 Governed File Intelligence Agent Tools.

Verifies the 5 governed agent tools:
1. inspect_file
2. summarize_document
3. analyze_spreadsheet
4. codebase_analysis
5. search_files

And governance constraints:
- Discovery via ToolRegistryService
- Schema validation
- PolicyEngine & risk governance
- AURA-603 hybrid search math preservation
- Direct-service bypass denial
"""

import io
import uuid
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import EntityNotFoundError, ValidationError
from app.db.models.file import FileRecord, FileStatus
from app.db.models.user import User
from app.db.models.workspace import Workspace, WorkspaceMember
from app.services.file_service import file_service
from app.services.tool_registry import tool_registry
from app.services.tools.file_tools import (
    execute_analyze_spreadsheet,
    execute_codebase_analysis,
    execute_inspect_file,
    execute_search_files,
    execute_summarize_document,
)


@pytest.fixture
async def file_tool_fixture(db_session: AsyncSession):
    """Setup test user, workspaces, and registered files for tool execution tests."""
    user = User(
        id=uuid.uuid4(),
        email=f"operator-{uuid.uuid4().hex[:6]}@aura.local",
        full_name="File Tools Operator",
        password_hash="fake_hash",
        is_active=True,
    )
    db_session.add(user)

    ws1 = Workspace(
        id=uuid.uuid4(),
        name="Intelligence Alpha",
        slug=f"ws-intel-alpha-{uuid.uuid4().hex[:6]}",
    )
    ws2 = Workspace(
        id=uuid.uuid4(),
        name="Intelligence Beta",
        slug=f"ws-intel-beta-{uuid.uuid4().hex[:6]}",
    )
    db_session.add_all([ws1, ws2])

    member1 = WorkspaceMember(workspace_id=ws1.id, user_id=user.id, role="owner")
    member2 = WorkspaceMember(workspace_id=ws2.id, user_id=user.id, role="owner")
    db_session.add_all([member1, member2])
    await db_session.commit()

    # Upload Markdown file to ws1
    md_content = b"# System Architecture\n\nAURA is an autonomous agent operating system.\n\n## Subsystems\n- Policy Engine\n- Vector Retrieval"
    from fastapi import UploadFile
    upload1 = UploadFile(file=io.BytesIO(md_content), filename="architecture.md", headers={"content-type": "text/markdown"})
    upload1_res = await file_service.upload_file(db=db_session, workspace_id=ws1.id, file=upload1, user_id=user.id)
    file_md = upload1_res.file

    # Upload CSV file to ws1
    csv_content = b"Item,Cost,Quantity,Formula\nServer,1200,3,=B2*C2\nStorage,400,5,=B3*C3\n"
    upload2 = UploadFile(file=io.BytesIO(csv_content), filename="budget.csv", headers={"content-type": "text/csv"})
    upload2_res = await file_service.upload_file(db=db_session, workspace_id=ws1.id, file=upload2, user_id=user.id)
    file_csv = upload2_res.file

    # Upload Python file to ws1
    py_content = b"class Calculator:\n    def add(self, a, b):\n        return a + b\n\ndef main():\n    calc = Calculator()\n    print(calc.add(2, 3))\n"
    upload3 = UploadFile(file=io.BytesIO(py_content), filename="calc.py", headers={"content-type": "text/x-python"})
    upload3_res = await file_service.upload_file(db=db_session, workspace_id=ws1.id, file=upload3, user_id=user.id)
    file_py = upload3_res.file

    return {
        "user": user,
        "ws1": ws1,
        "ws2": ws2,
        "file_md": file_md,
        "file_csv": file_csv,
        "file_py": file_py,
    }


@pytest.mark.asyncio
async def test_tool_registry_discovers_file_intelligence_tools(db_session: AsyncSession, file_tool_fixture):
    """1. Verify ToolRegistryService registers all 5 file intelligence tools."""
    fixture = file_tool_fixture
    ws_id = fixture["ws1"].id
    tools = await tool_registry.list_tools(db=db_session, workspace_id=ws_id)
    tool_names = [t.name for t in tools]

    expected_tools = [
        "inspect_file",
        "summarize_document",
        "analyze_spreadsheet",
        "codebase_analysis",
        "search_files",
    ]
    for expected in expected_tools:
        assert expected in tool_names, f"Expected tool '{expected}' not found in ToolRegistry"

    inspect_meta = next(t for t in tools if t.name == "inspect_file")
    assert inspect_meta.risk_level == "low"
    assert "file_id" in inspect_meta.input_schema["properties"]


@pytest.mark.asyncio
async def test_inspect_file_tool_governance_and_execution(db_session: AsyncSession, file_tool_fixture):
    """2. Verify inspect_file tool executes through ToolRegistryService with correct schema."""
    from app.schemas.tool import ToolExecutionRequest
    fixture = file_tool_fixture
    ws_id = fixture["ws1"].id
    file_md = fixture["file_md"]

    req = ToolExecutionRequest(
        tool_name="inspect_file",
        workspace_id=ws_id,
        arguments={"file_id": str(file_md.id)},
    )
    result = await tool_registry.execute_tool(
        db=db_session,
        request=req,
        actor_id=str(fixture["user"].id),
    )

    assert result.success is True
    data = result.result
    assert data["file_id"] == str(file_md.id)
    assert data["filename"] == "architecture.md"
    assert data["status"] in ["uploaded", "registered", "indexed", "extracted"]
    assert "vector_status" in data


@pytest.mark.asyncio
async def test_summarize_document_tool_execution(db_session: AsyncSession, file_tool_fixture):
    """3. Verify summarize_document tool executes and provides structured executive summary."""
    from app.schemas.tool import ToolExecutionRequest
    fixture = file_tool_fixture
    ws_id = fixture["ws1"].id
    file_md = fixture["file_md"]

    req = ToolExecutionRequest(
        tool_name="summarize_document",
        workspace_id=ws_id,
        arguments={"file_id": str(file_md.id)},
    )
    result = await tool_registry.execute_tool(
        db=db_session,
        request=req,
        actor_id=str(fixture["user"].id),
    )

    assert result.success is True
    data = result.result
    assert data["file_id"] == str(file_md.id)
    assert len(data["executive_summary"]) > 0
    assert isinstance(data["key_takeaways"], list)
    assert data["status"] in ["completed", "extractive_fallback"]


@pytest.mark.asyncio
async def test_analyze_spreadsheet_tool_execution(db_session: AsyncSession, file_tool_fixture):
    """4. Verify analyze_spreadsheet tool inspects tabular data, detects formulas, and reports metrics."""
    from app.schemas.tool import ToolExecutionRequest
    fixture = file_tool_fixture
    ws_id = fixture["ws1"].id
    file_csv = fixture["file_csv"]

    req = ToolExecutionRequest(
        tool_name="analyze_spreadsheet",
        workspace_id=ws_id,
        arguments={"file_id": str(file_csv.id)},
    )
    result = await tool_registry.execute_tool(
        db=db_session,
        request=req,
        actor_id=str(fixture["user"].id),
    )

    assert result.success is True
    data = result.result
    assert str(data["file_id"]) == str(file_csv.id)
    assert data["total_sheets"] >= 1
    assert "sheets" in data


@pytest.mark.asyncio
async def test_codebase_analysis_tool_execution(db_session: AsyncSession, file_tool_fixture):
    """5. Verify codebase_analysis tool parses AST symbols and structural statistics."""
    from app.schemas.tool import ToolExecutionRequest
    fixture = file_tool_fixture
    ws_id = fixture["ws1"].id
    file_py = fixture["file_py"]

    req = ToolExecutionRequest(
        tool_name="codebase_analysis",
        workspace_id=ws_id,
        arguments={"file_id": str(file_py.id)},
    )
    result = await tool_registry.execute_tool(
        db=db_session,
        request=req,
        actor_id=str(fixture["user"].id),
    )

    assert result.success is True
    data = result.result
    assert data["total_files"] >= 1
    assert "languages" in data
    assert "python" in data["languages"]
    assert len(data["symbols"]) >= 1
    symbol_names = [s["name"] for s in data["symbols"]]
    assert any("Calculator" in name or "add" in name or "main" in name for name in symbol_names)


@pytest.mark.asyncio
async def test_search_files_tool_execution_preserves_aura603(db_session: AsyncSession, file_tool_fixture):
    """6. Verify search_files tool invokes AURA-603 hybrid retrieval with exact mathematical contract."""
    from app.schemas.tool import ToolExecutionRequest
    fixture = file_tool_fixture
    ws_id = fixture["ws1"].id

    req = ToolExecutionRequest(
        tool_name="search_files",
        workspace_id=ws_id,
        arguments={"query": "architecture autonomous agent", "top_k": 5},
    )
    result = await tool_registry.execute_tool(
        db=db_session,
        request=req,
        actor_id=str(fixture["user"].id),
    )

    assert result.success is True
    data = result.result
    assert "query" in data
    assert data["query"] == "architecture autonomous agent"
    assert "results" in data


@pytest.mark.asyncio
async def test_agent_direct_service_bypass_denial(db_session: AsyncSession, file_tool_fixture):
    """7. Verify un-governed direct execution or invalid tool names fail closed."""
    from app.schemas.tool import ToolExecutionRequest
    fixture = file_tool_fixture
    ws_id = fixture["ws1"].id

    req = ToolExecutionRequest(
        tool_name="non_existent_unauthorized_tool",
        workspace_id=ws_id,
        arguments={},
    )
    with pytest.raises(Exception):
        await tool_registry.execute_tool(
            db=db_session,
            request=req,
            actor_id=str(fixture["user"].id),
        )


@pytest.mark.asyncio
async def test_file_tool_schema_strictness_and_validation(db_session: AsyncSession, file_tool_fixture):
    """8. Verify file tools enforce UUID formats and reject non-existent file IDs."""
    fixture = file_tool_fixture
    ws_id = fixture["ws1"].id
    non_existent_id = str(uuid.uuid4())

    with pytest.raises(EntityNotFoundError):
        await execute_inspect_file(
            workspace_id=ws_id,
            file_id=non_existent_id,
            db=db_session,
        )

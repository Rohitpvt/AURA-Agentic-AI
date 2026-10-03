"""Codebase Repository Analysis Service with AST Symbol Extraction."""

import ast
import json
import os
from typing import Any, Dict, List, Optional
import uuid
import zipfile
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.errors import EntityNotFoundError, ValidationError
from app.core.filesystem import filesystem_guard
from app.core.logging import logger
from app.db.models.file import FileRecord
from app.schemas.file import (
    CodebaseAnalysisRequest,
    CodebaseAnalysisResponse,
    CodebaseSymbolInfo,
)
from app.services.file_service import file_service


class CodebaseAnalysisService:
    """Safe, AST-guided structural codebase analysis engine."""

    async def analyze_codebase(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        file_id: uuid.UUID,
        request: Optional[CodebaseAnalysisRequest] = None,
    ) -> CodebaseAnalysisResponse:
        """Analyze repository archive structure, symbols, language distribution, and dependencies."""
        file_record = await file_service.get_file(db=db, workspace_id=workspace_id, file_id=file_id)

        physical_path = filesystem_guard.validate_and_resolve_path(workspace_id, file_record.storage_path)
        if not physical_path.exists():
            raise EntityNotFoundError("StorageFile", str(file_id))

        storage_path = str(physical_path)

        ext = file_record.file_extension.lower().lstrip(".")
        focus_paths = request.focus_paths if request and request.focus_paths else None
        symbol_query = request.symbol_query.lower() if request and request.symbol_query else None

        symbols: List[CodebaseSymbolInfo] = []
        languages: Dict[str, int] = {}
        file_tree: List[Dict[str, Any]] = []
        dependencies: List[str] = []
        total_files = 0

        if ext == "zip":
            with zipfile.ZipFile(storage_path, "r") as zf:
                namelist = zf.namelist()
                total_files = len(namelist)
                for entry in namelist:
                    if entry.endswith("/"):
                        continue

                    # Filter by focus paths if specified
                    if focus_paths and not any(entry.startswith(fp) for fp in focus_paths):
                        continue

                    lang = self._detect_language(entry)
                    if lang:
                        languages[lang] = languages.get(lang, 0) + 1

                    file_tree.append({"path": entry, "size_bytes": zf.getinfo(entry).file_size, "language": lang})

                    # Extract manifest dependencies
                    base_name = os.path.basename(entry).lower()
                    if base_name in ["requirements.txt", "package.json", "pyproject.toml", "cargo.toml", "go.mod"]:
                        try:
                            content = zf.read(entry).decode("utf-8", errors="replace")
                            deps = self._parse_dependencies(base_name, content)
                            dependencies.extend(deps)
                        except Exception as e:
                            logger.warning(f"Failed to parse dependency manifest {entry}: {e}")

                    # Extract Python AST symbols
                    if entry.endswith(".py"):
                        try:
                            py_code = zf.read(entry).decode("utf-8", errors="replace")
                            extracted_syms = self._extract_python_symbols(entry, py_code)
                            for sym in extracted_syms:
                                if not symbol_query or symbol_query in sym.name.lower():
                                    symbols.append(sym)
                        except Exception as e:
                            logger.warning(f"AST parsing failed for {entry}: {e}")
        else:
            # Single source file
            total_files = 1
            lang = self._detect_language(file_record.original_filename)
            if lang:
                languages[lang] = 1
            file_tree.append({"path": file_record.original_filename, "size_bytes": file_record.size_bytes, "language": lang})

            if ext == "py":
                with open(storage_path, "r", encoding="utf-8", errors="replace") as f:
                    py_code = f.read()
                symbols = self._extract_python_symbols(file_record.original_filename, py_code)
                if symbol_query:
                    symbols = [s for s in symbols if symbol_query in s.name.lower()]

        return CodebaseAnalysisResponse(
            file_id=file_id,
            total_files=total_files,
            languages=languages,
            file_tree=file_tree[:200],  # Bounded file tree preview
            symbols=symbols[:100],      # Bounded symbol list
            dependencies=list(set(dependencies))[:50],
        )

    def _detect_language(self, filename: str) -> Optional[str]:
        """Classify programming language by extension."""
        _, ext = os.path.splitext(filename.lower())
        mapping = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "javascript",
            ".tsx": "typescript",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
            ".c": "c",
            ".cpp": "cpp",
            ".h": "c_header",
            ".html": "html",
            ".css": "css",
            ".sql": "sql",
            ".json": "json",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".md": "markdown",
        }
        return mapping.get(ext)

    def _extract_python_symbols(self, filepath: str, code_content: str) -> List[CodebaseSymbolInfo]:
        """Parse Python source code AST to discover classes, functions, and docstrings."""
        symbols = []
        try:
            tree = ast.parse(code_content)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    doc = ast.get_docstring(node)
                    symbols.append(
                        CodebaseSymbolInfo(
                            name=node.name,
                            type="class",
                            file=filepath,
                            line=getattr(node, "lineno", None),
                            docstring=doc,
                        )
                    )
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    doc = ast.get_docstring(node)
                    symbols.append(
                        CodebaseSymbolInfo(
                            name=node.name,
                            type="function",
                            file=filepath,
                            line=getattr(node, "lineno", None),
                            docstring=doc,
                        )
                    )
        except Exception as e:
            logger.debug(f"AST parse error in {filepath}: {e}")
        return symbols

    def _parse_dependencies(self, manifest_name: str, content: str) -> List[str]:
        """Extract dependency packages from manifest text."""
        deps = []
        if manifest_name == "requirements.txt":
            for line in content.splitlines():
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith("-"):
                    pkg = line.split("==")[0].split(">=")[0].split("<=")[0].split("~=")[0].strip()
                    if pkg:
                        deps.append(pkg)
        elif manifest_name == "package.json":
            try:
                data = json.loads(content)
                for k in ["dependencies", "devDependencies"]:
                    if k in data and isinstance(data[k], dict):
                        deps.extend(list(data[k].keys()))
            except Exception:
                pass
        return deps


codebase_analysis_service = CodebaseAnalysisService()

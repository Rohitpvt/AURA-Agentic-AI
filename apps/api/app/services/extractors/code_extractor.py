"""Safe Source Code Structural Extractor (AURA-602).

Supports:
- Python (.py) via standard library AST parsing (inert analysis without code execution)
- TypeScript/JavaScript (.ts, .js) structural block & function extraction
- Go (.go), Rust (.rs), Java (.java), C/C++ (.c, .cpp) structural signature parsing
- Web/Database languages (.html, .css, .sql) syntax structure extraction
- Zero compiler, runtime, interpreter, or subprocess invocation
- Bounded memory buffers (max 5 MB extracted text)
"""

import ast
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set

from app.core.logging import logger
from app.schemas.file import ExtractedContentItem, NormalizedExtractionResult
from app.services.extractors.base import BaseExtractor


class CodeExtractor(BaseExtractor):
    """Isolated, deterministic source code extractor producing structural AST and symbol maps as inert data."""

    PARSER_NAME = "code_extractor"
    PARSER_VERSION = "1.0.0"

    SUPPORTED_EXTENSIONS: Set[str] = {
        ".py", ".ts", ".js", ".go", ".rs", ".java", ".c", ".cpp", ".h", ".hpp", ".html", ".css", ".sql"
    }
    SUPPORTED_MIMES: Set[str] = {
        "text/x-python", "application/x-python", "text/javascript", "application/javascript",
        "application/typescript", "text/x-go", "text/x-rust", "text/x-java", "text/x-c",
        "text/x-c++", "text/html", "text/css", "application/sql", "text/sql"
    }

    async def extract(
        self,
        file_path: Path,
        filename: str,
        mime_type: str,
        ext: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> NormalizedExtractionResult:
        """Extract structural code elements (classes, functions, signatures) as inert text/metadata."""
        options = options or {}
        max_bytes = options.get("max_text_bytes", self.MAX_EXTRACTED_BYTES)
        warnings: List[str] = []
        security_flags: List[str] = []

        try:
            raw_bytes = file_path.read_bytes()
            try:
                code_text = raw_bytes.decode("utf-8")
            except UnicodeDecodeError:
                code_text = raw_bytes.decode("utf-8", errors="replace")
                warnings.append("Decoded with replacement characters due to UTF-8 decoding error.")

            normalized_ext = ext.lower()

            if normalized_ext == ".py":
                return self._extract_python_ast(
                    code_text=code_text, filename=filename, mime_type=mime_type, ext=ext, max_bytes=max_bytes, warnings=warnings, security_flags=security_flags
                )
            else:
                return self._extract_generic_code(
                    code_text=code_text, filename=filename, mime_type=mime_type, ext=ext, max_bytes=max_bytes, warnings=warnings, security_flags=security_flags
                )

        except Exception as e:
            logger.error(f"CodeExtractor: Failed to extract code from {filename}: {e}", exc_info=True)
            return self.build_result(
                filename=filename,
                mime_type=mime_type,
                ext=ext,
                status="failed",
                extracted_text="",
                content_items=[],
                error_message=f"Code parsing failure: {str(e)}",
                max_bytes=max_bytes,
            )

    def _extract_python_ast(
        self,
        code_text: str,
        filename: str,
        mime_type: str,
        ext: str,
        max_bytes: int,
        warnings: List[str],
        security_flags: List[str],
    ) -> NormalizedExtractionResult:
        """Perform inert AST extraction on Python source code without executing any instructions."""
        content_items: List[ExtractedContentItem] = []
        metadata: Dict[str, Any] = {"language": "python"}
        item_idx = 0
        lines = code_text.splitlines()

        try:
            tree = ast.parse(code_text, filename=filename)

            # 1. Module Docstring
            docstring = ast.get_docstring(tree)
            if docstring:
                metadata["module_docstring"] = docstring
                content_items.append(
                    ExtractedContentItem(
                        index=item_idx,
                        text=f"Module Docstring: {docstring}",
                        item_type="module_docstring",
                        source_location={"symbol_type": "module_docstring"},
                    )
                )
                item_idx += 1

            classes_found = []
            functions_found = []
            imports_found = []

            # 2. Walk Top-Level and Nested Nodes
            for node in tree.body:
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    import_repr = ast.unparse(node) if hasattr(ast, "unparse") else "import statement"
                    imports_found.append(import_repr)

                elif isinstance(node, ast.ClassDef):
                    class_doc = ast.get_docstring(node) or ""
                    classes_found.append(node.name)
                    methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                    class_snippet = "\n".join(lines[node.lineno - 1 : getattr(node, "end_lineno", node.lineno)])
                    content_items.append(
                        ExtractedContentItem(
                            index=item_idx,
                            text=f"Class {node.name}:\n{class_snippet}",
                            item_type="ast_class",
                            source_location={
                                "symbol_name": node.name,
                                "symbol_type": "class",
                                "line_start": node.lineno,
                                "line_end": getattr(node, "end_lineno", node.lineno),
                                "methods": methods,
                                "docstring": class_doc,
                            },
                        )
                    )
                    item_idx += 1

                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    fn_doc = ast.get_docstring(node) or ""
                    functions_found.append(node.name)
                    fn_snippet = "\n".join(lines[node.lineno - 1 : getattr(node, "end_lineno", node.lineno)])
                    content_items.append(
                        ExtractedContentItem(
                            index=item_idx,
                            text=f"Function {node.name}:\n{fn_snippet}",
                            item_type="ast_function",
                            source_location={
                                "symbol_name": node.name,
                                "symbol_type": "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function",
                                "line_start": node.lineno,
                                "line_end": getattr(node, "end_lineno", node.lineno),
                                "docstring": fn_doc,
                            },
                        )
                    )
                    item_idx += 1

            metadata["classes_count"] = len(classes_found)
            metadata["functions_count"] = len(functions_found)
            metadata["imports_count"] = len(imports_found)
            metadata["classes"] = classes_found
            metadata["functions"] = functions_found
            metadata["line_count"] = len(lines)

            status = "extracted" if code_text.strip() else "no_text_extracted"

            return self.build_result(
                filename=filename,
                mime_type=mime_type,
                ext=ext,
                status=status,
                extracted_text=code_text,
                content_items=content_items,
                metadata=metadata,
                warnings=warnings,
                security_flags=security_flags,
                max_bytes=max_bytes,
            )

        except SyntaxError as syn_err:
            warnings.append(f"Python AST syntax notice ({syn_err}); falling back to generic line extraction.")
            return self._extract_generic_code(
                code_text=code_text, filename=filename, mime_type=mime_type, ext=ext, max_bytes=max_bytes, warnings=warnings, security_flags=security_flags
            )

    def _extract_generic_code(
        self,
        code_text: str,
        filename: str,
        mime_type: str,
        ext: str,
        max_bytes: int,
        warnings: List[str],
        security_flags: List[str],
    ) -> NormalizedExtractionResult:
        """Perform regex and line-based structural extraction for non-Python programming languages."""
        content_items: List[ExtractedContentItem] = []
        lines = code_text.splitlines()
        item_idx = 0

        # Heuristic symbol detection patterns
        func_patterns = [
            re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_$]+)", re.MULTILINE),
            re.compile(r"^\s*(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>", re.MULTILINE),
            re.compile(r"^\s*(?:pub\s+)?fn\s+([a-zA-Z0-9_]+)", re.MULTILINE),
            re.compile(r"^\s*func\s+(?:\([^)]+\)\s*)?([a-zA-Z0-9_]+)", re.MULTILINE),
            re.compile(r"^\s*(?:public|private|protected)?\s*(?:static\s+)?[a-zA-Z0-9_<>\[\]]+\s+([a-zA-Z0-9_]+)\s*\([^)]*\)\s*\{", re.MULTILINE),
            re.compile(r"^\s*(?:CREATE|ALTER)\s+(?:OR\s+REPLACE\s+)?(?:TABLE|VIEW|FUNCTION|PROCEDURE|INDEX)\s+([a-zA-Z0-9_\"\.]+)", re.IGNORECASE | re.MULTILINE),
        ]

        class_patterns = [
            re.compile(r"^\s*(?:export\s+)?(?:abstract\s+)?class\s+([a-zA-Z0-9_$]+)", re.MULTILINE),
            re.compile(r"^\s*(?:export\s+)?interface\s+([a-zA-Z0-9_$]+)", re.MULTILINE),
            re.compile(r"^\s*(?:pub\s+)?struct\s+([a-zA-Z0-9_]+)", re.MULTILINE),
            re.compile(r"^\s*(?:pub\s+)?enum\s+([a-zA-Z0-9_]+)", re.MULTILINE),
            re.compile(r"^\s*type\s+([a-zA-Z0-9_]+)\s+struct", re.MULTILINE),
        ]

        symbols_found = []

        for line_idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("#"):
                continue

            for pat in class_patterns:
                m = pat.search(line)
                if m:
                    sym_name = m.group(1)
                    symbols_found.append({"name": sym_name, "type": "class_or_type", "line": line_idx})
                    content_items.append(
                        ExtractedContentItem(
                            index=item_idx,
                            text=line,
                            item_type="code_symbol",
                            source_location={"symbol_name": sym_name, "symbol_type": "type_definition", "line": line_idx},
                        )
                    )
                    item_idx += 1
                    break

            for pat in func_patterns:
                m = pat.search(line)
                if m:
                    sym_name = m.group(1)
                    symbols_found.append({"name": sym_name, "type": "function", "line": line_idx})
                    content_items.append(
                        ExtractedContentItem(
                            index=item_idx,
                            text=line,
                            item_type="code_symbol",
                            source_location={"symbol_name": sym_name, "symbol_type": "function", "line": line_idx},
                        )
                    )
                    item_idx += 1
                    break

        metadata = {
            "line_count": len(lines),
            "symbols_count": len(symbols_found),
            "language": ext.lstrip("."),
        }

        status = "extracted" if code_text.strip() else "no_text_extracted"

        return self.build_result(
            filename=filename,
            mime_type=mime_type,
            ext=ext,
            status=status,
            extracted_text=code_text,
            content_items=content_items,
            metadata=metadata,
            warnings=warnings,
            security_flags=security_flags,
            max_bytes=max_bytes,
        )

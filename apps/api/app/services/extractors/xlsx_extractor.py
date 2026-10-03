"""Deterministic Microsoft Excel (.xlsx) Spreadsheet Parser (AURA-602).

Enforces Non-Negotiable Invariants:
1. Formula Preservation: Uses openpyxl with data_only=False to preserve formula expressions as inert data text.
2. Safe Formula Handling: Formulas (=SUM, =HYPERLINK, =WEBSERVICE, etc.) are treated strictly as data, never evaluated or executed.
3. Optional Cached-Value Access: Separate data_only=True pass strictly labeled as 'cached_formula_result' (creator-calculated, not AURA-evaluated).
4. Active Content Neutralization: VBA macros, DDE links, external workbook queries, and active scripts are ignored/neutralized.
5. Resource Bounding: Max 50 sheets, max 100,000 cells, max 5 MB extracted text.
6. Local-First: Zero external spreadsheet applications (Excel, LibreOffice) are ever invoked ($0.00 cloud cost).
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import openpyxl

from app.core.logging import logger
from app.schemas.file import ExtractedContentItem, NormalizedExtractionResult
from app.services.extractors.base import BaseExtractor


class XLSXExtractor(BaseExtractor):
    """Isolated, bounded XLSX spreadsheet extractor with strict formula preservation and active-content neutralization."""

    PARSER_NAME = "xlsx_extractor"
    PARSER_VERSION = "1.0.0"

    SUPPORTED_EXTENSIONS: Set[str] = {".xlsx"}
    SUPPORTED_MIMES: Set[str] = {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
    }

    MAX_SHEETS: int = 50
    MAX_CELLS: int = 100_000

    async def extract(
        self,
        file_path: Path,
        filename: str,
        mime_type: str,
        ext: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> NormalizedExtractionResult:
        """Extract workbook structure, sheets, tabular data, and inert formulas from .xlsx."""
        options = options or {}
        max_bytes = options.get("max_text_bytes", self.MAX_EXTRACTED_BYTES)
        include_cached = options.get("include_cached_formula_results", False)

        warnings: List[str] = []
        security_flags: List[str] = []
        content_items: List[ExtractedContentItem] = []
        sheet_summaries: List[str] = []
        metadata: Dict[str, Any] = {}

        try:
            # 1. Authoritative Pass: data_only=False (Formula Preservation)
            wb = openpyxl.load_workbook(
                filename=str(file_path),
                data_only=False,
                read_only=False,
                keep_vba=False,
            )

            sheet_names = wb.sheetnames
            metadata["sheet_names"] = sheet_names
            metadata["total_sheets"] = len(sheet_names)

            if len(sheet_names) > self.MAX_SHEETS:
                warnings.append(f"Spreadsheet contains {len(sheet_names)} sheets; only first {self.MAX_SHEETS} parsed.")

            total_cells_processed = 0
            formula_cells: Dict[str, str] = {}  # "SheetName!A1" -> formula_text
            item_idx = 0

            # 2. Iterate Sheets and Cells
            for sheet_idx, sheet_name in enumerate(sheet_names[: self.MAX_SHEETS]):
                ws = wb[sheet_name]
                sheet_lines: List[str] = [f"=== [Sheet: {sheet_name}] ==="]
                rows = list(ws.iter_rows(values_only=False))

                for row_idx, row in enumerate(rows, start=1):
                    row_cells_repr = []
                    for col_idx, cell in enumerate(row, start=1):
                        total_cells_processed += 1
                        if total_cells_processed > self.MAX_CELLS:
                            break

                        val = cell.value
                        if val is None:
                            continue

                        val_str = str(val).strip()
                        coord = cell.coordinate or f"R{row_idx}C{col_idx}"
                        cell_key = f"{sheet_name}!{coord}"

                        # Formula Expression Detection (Inert Data)
                        if isinstance(val, str) and val.startswith("="):
                            formula_cells[cell_key] = val
                            row_cells_repr.append(f"[{coord}: {val}]")
                            content_items.append(
                                ExtractedContentItem(
                                    index=item_idx,
                                    text=f"Formula at {cell_key}: {val}",
                                    item_type="formula",
                                    source_location={
                                        "sheet": sheet_name,
                                        "cell": coord,
                                        "row": row_idx,
                                        "col": col_idx,
                                    },
                                    is_formula=True,
                                    formula_expression=val,
                                )
                            )
                            item_idx += 1
                        else:
                            row_cells_repr.append(val_str)
                            content_items.append(
                                ExtractedContentItem(
                                    index=item_idx,
                                    text=f"{cell_key}: {val_str}",
                                    item_type="cell",
                                    source_location={
                                        "sheet": sheet_name,
                                        "cell": coord,
                                        "row": row_idx,
                                        "col": col_idx,
                                    },
                                    is_formula=False,
                                )
                            )
                            item_idx += 1

                    if row_cells_repr:
                        sheet_lines.append(" | ".join(row_cells_repr))

                    if total_cells_processed > self.MAX_CELLS:
                        warnings.append(f"Spreadsheet cell count exceeded {self.MAX_CELLS}; remaining cells truncated.")
                        break

                sheet_summaries.append("\n".join(sheet_lines))
                if total_cells_processed > self.MAX_CELLS:
                    break

            wb.close()

            # 3. Optional Cached Values Pass: data_only=True
            cached_results_count = 0
            if include_cached and formula_cells:
                try:
                    wb_cached = openpyxl.load_workbook(
                        filename=str(file_path),
                        data_only=True,
                        read_only=True,
                        keep_vba=False,
                    )
                    for sheet_name in sheet_names[: self.MAX_SHEETS]:
                        if sheet_name not in wb_cached.sheetnames:
                            continue
                        ws_c = wb_cached[sheet_name]
                        for row in ws_c.iter_rows(values_only=False):
                            for cell in row:
                                if cell.value is not None:
                                    coord = cell.coordinate
                                    cell_key = f"{sheet_name}!{coord}"
                                    if cell_key in formula_cells:
                                        cached_val_str = str(cell.value)
                                        content_items.append(
                                            ExtractedContentItem(
                                                index=item_idx,
                                                text=f"Cached result for {cell_key} ({formula_cells[cell_key]}): {cached_val_str}",
                                                item_type="cached_formula_result",
                                                source_location={
                                                    "sheet": sheet_name,
                                                    "cell": coord,
                                                    "formula": formula_cells[cell_key],
                                                    "is_cached_result": True,
                                                },
                                                is_formula=False,
                                            )
                                        )
                                        item_idx += 1
                                        cached_results_count += 1
                    wb_cached.close()
                except Exception as cached_err:
                    warnings.append(f"Optional cached-value pass note: {cached_err}")

            metadata["total_cells_processed"] = total_cells_processed
            metadata["formula_cells_count"] = len(formula_cells)
            metadata["cached_results_extracted"] = cached_results_count
            metadata["formula_preservation"] = "inert_data_strings"

            full_extracted_text = "\n\n".join(sheet_summaries).strip()
            status = "extracted" if full_extracted_text else "no_text_extracted"

            return self.build_result(
                filename=filename,
                mime_type=mime_type,
                ext=ext,
                status=status,
                extracted_text=full_extracted_text,
                content_items=content_items,
                metadata=metadata,
                warnings=warnings,
                security_flags=security_flags,
                max_bytes=max_bytes,
            )

        except Exception as e:
            logger.error(f"XLSXExtractor: Failed to parse XLSX {filename}: {e}", exc_info=True)
            return self.build_result(
                filename=filename,
                mime_type=mime_type,
                ext=ext,
                status="failed",
                extracted_text="",
                content_items=[],
                error_message=f"XLSX parsing failure: {str(e)}",
                max_bytes=max_bytes,
            )

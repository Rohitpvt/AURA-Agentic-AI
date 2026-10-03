"""Spreadsheet Analysis Service with Formula Safety and Tabular Schema Extraction."""

import csv
import io
import os
from typing import Any, Dict, List, Optional
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.errors import EntityNotFoundError, ValidationError
from app.core.filesystem import filesystem_guard
from app.core.logging import logger
from app.db.models.file import FileRecord
from app.schemas.file import (
    SpreadsheetAnalysisRequest,
    SpreadsheetAnalysisResponse,
    SpreadsheetSheetInfo,
)
from app.services.file_service import file_service


class SpreadsheetAnalysisService:
    """Safe, formula-inert spreadsheet schema and tabular data inspection engine."""

    async def analyze_spreadsheet(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        file_id: uuid.UUID,
        request: Optional[SpreadsheetAnalysisRequest] = None,
    ) -> SpreadsheetAnalysisResponse:
        """Inspect spreadsheet worksheets, headers, sample rows, and formula counts safely."""
        file_record = await file_service.get_file(db=db, workspace_id=workspace_id, file_id=file_id)

        ext = file_record.file_extension.lower().lstrip(".")
        if ext not in ["xlsx", "csv"]:
            raise ValidationError(
                f"Spreadsheet analysis only supports '.xlsx' and '.csv' files, but file has extension '.{ext}'"
            )

        physical_path = filesystem_guard.validate_and_resolve_path(workspace_id, file_record.storage_path)
        if not physical_path.exists():
            raise EntityNotFoundError("StorageFile", str(file_id))

        storage_path = str(physical_path)
        sample_limit = request.sample_row_limit if request and request.sample_row_limit else 25
        target_sheet = request.sheet_name if request else None

        sheets_info: List[SpreadsheetSheetInfo] = []
        has_macros = False
        total_formulas = 0

        if ext == "csv":
            sheet_info, formulas = self._analyze_csv(storage_path, sample_limit)
            sheets_info.append(sheet_info)
            total_formulas += formulas
        elif ext == "xlsx":
            sheets_info, formulas, has_macros = self._analyze_xlsx(storage_path, sample_limit, target_sheet)
            total_formulas += formulas

        summary = {
            "total_sheets": len(sheets_info),
            "total_formulas_detected": total_formulas,
            "has_macros": has_macros,
            "filename": file_record.original_filename,
            "size_bytes": file_record.size_bytes,
        }

        return SpreadsheetAnalysisResponse(
            file_id=file_id,
            total_sheets=len(sheets_info),
            sheets=sheets_info,
            has_macros=has_macros,
            summary=summary,
        )

    def _analyze_csv(self, file_path: str, sample_limit: int) -> tuple[SpreadsheetSheetInfo, int]:
        """Analyze a CSV file safely."""
        rows: List[List[str]] = []
        formula_count = 0
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                if i < sample_limit + 1:
                    rows.append(row)
                for cell in row:
                    if cell.startswith(("=", "+", "-", "@")):
                        formula_count += 1

        columns = rows[0] if rows else []
        sample_rows_data = []
        for r in rows[1 : sample_limit + 1]:
            row_dict = {}
            for idx, col_name in enumerate(columns):
                val = r[idx] if idx < len(r) else ""
                row_dict[col_name or f"col_{idx}"] = str(val)
            sample_rows_data.append(row_dict)

        sheet_info = SpreadsheetSheetInfo(
            name="Sheet1",
            row_count=len(rows),
            column_count=len(columns),
            columns=[str(c) for c in columns],
            sample_rows=sample_rows_data,
            formulas_detected=formula_count,
        )
        return sheet_info, formula_count

    def _analyze_xlsx(
        self, file_path: str, sample_limit: int, target_sheet: Optional[str]
    ) -> tuple[List[SpreadsheetSheetInfo], int, bool]:
        """Analyze XLSX workbook structure with openpyxl with formula inertness."""
        import openpyxl

        sheets_info: List[SpreadsheetSheetInfo] = []
        total_formulas = 0
        has_macros = False

        wb = openpyxl.load_workbook(file_path, data_only=False, read_only=True)
        try:
            if getattr(wb, "vba_archive", None) is not None:
                has_macros = True

            sheet_names = wb.sheetnames
            if target_sheet and target_sheet in sheet_names:
                sheet_names = [target_sheet]

            for sname in sheet_names:
                ws = wb[sname]
                rows_iter = ws.iter_rows(values_only=False)

                header_row = next(rows_iter, None)
                if not header_row:
                    sheets_info.append(
                        SpreadsheetSheetInfo(
                            name=sname,
                            row_count=0,
                            column_count=0,
                            columns=[],
                            sample_rows=[],
                            formulas_detected=0,
                        )
                    )
                    continue

                columns = [str(cell.value or f"Col_{i+1}") for i, cell in enumerate(header_row)]
                sample_rows_data = []
                sheet_formulas = 0
                row_idx = 0

                for row in rows_iter:
                    row_idx += 1
                    row_dict = {}
                    for i, cell in enumerate(row):
                        col_key = columns[i] if i < len(columns) else f"Col_{i+1}"
                        val = cell.value
                        if isinstance(val, str) and val.startswith("="):
                            sheet_formulas += 1
                        if row_idx <= sample_limit:
                            row_dict[col_key] = str(val) if val is not None else ""
                    if row_idx <= sample_limit:
                        sample_rows_data.append(row_dict)

                total_formulas += sheet_formulas
                sheets_info.append(
                    SpreadsheetSheetInfo(
                        name=sname,
                        row_count=row_idx + 1,
                        column_count=len(columns),
                        columns=columns,
                        sample_rows=sample_rows_data,
                        formulas_detected=sheet_formulas,
                    )
                )
        finally:
            wb.close()

        return sheets_info, total_formulas, has_macros


spreadsheet_analysis_service = SpreadsheetAnalysisService()

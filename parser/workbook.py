"""Read ELSTAT workbooks into plain grids. The Excel files are opened read-only and never written."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter


@dataclass
class Sheet:
    """Cell values of one worksheet.

    `cells`  : values as stored (a merged range holds its value in the top-left cell only).
               Use for data rows: ELSTAT merges region names over a name row + blank row.
    `filled` : same, but every cell of a merged range carries the range's value.
               Use for header rows, where a merged label applies to all columns under it.
    """
    name: str
    cells: dict[tuple[int, int], object]
    filled: dict[tuple[int, int], object]
    max_row: int
    max_col: int

    def get(self, row: int, col: int):
        return self.cells.get((row, col))

    def text(self, row: int, col: int) -> str:
        v = self.cells.get((row, col))
        return "" if v is None else str(v).strip()

    def header_text(self, row: int, col: int) -> str:
        v = self.filled.get((row, col))
        return "" if v is None else str(v).strip()

    def row_values(self, row: int) -> dict[int, object]:
        return {c: v for (r, c), v in self.cells.items() if r == row}

    def find(self, predicate) -> list[tuple[int, int]]:
        return sorted(rc for rc, v in self.cells.items() if predicate(v))


def cell_ref(row: int, col: int) -> str:
    return f"{get_column_letter(col)}{row}"


def _fill_merged(cells: dict, merges: list[tuple[int, int, int, int]]) -> dict:
    """Copy each merged range's top-left value into all its cells.
    merges: (min_row, min_col, max_row, max_col), 1-based inclusive."""
    filled = dict(cells)
    for r0, c0, r1, c1 in merges:
        top = cells.get((r0, c0))
        if top is None:
            continue
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                filled[(r, c)] = top
    return filled


def _clean(v):
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def load_visible_sheets(path: Path) -> list[Sheet]:
    """All visible worksheets of an .xlsx or .xls file. Hidden sheets are skipped."""
    suffix = Path(path).suffix.lower()
    if suffix == ".xlsx":
        return _load_xlsx(path)
    if suffix == ".xls":
        return _load_xls(path)
    raise ValueError(f"unsupported file type {suffix!r} (expected .xlsx or .xls)")


def _load_xls(path: Path) -> list[Sheet]:
    """Old binary Excel format, read with xlrd (formatting_info gives merged cells)."""
    try:
        import xlrd
    except ImportError as e:
        raise ValueError("reading .xls needs the xlrd package: "
                         ".venv\\Scripts\\pip install -r requirements.txt") from e
    wb = xlrd.open_workbook(str(path), formatting_info=True, on_demand=True)
    sheets = []
    try:
        for i in range(wb.nsheets):
            ws = wb.sheet_by_index(i)
            if ws.visibility != 0:                       # 1 hidden, 2 very hidden
                continue
            cells: dict[tuple[int, int], object] = {}
            for r in range(ws.nrows):
                for c in range(ws.ncols):
                    cell = ws.cell(r, c)
                    if cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK, xlrd.XL_CELL_ERROR):
                        continue
                    v = _clean(cell.value)
                    if v is not None:
                        cells[(r + 1, c + 1)] = v
            # xlrd merges: (row_lo, row_hi_excl, col_lo, col_hi_excl), 0-based
            merges = [(r0 + 1, c0 + 1, r1, c1) for r0, r1, c0, c1 in ws.merged_cells]
            sheets.append(Sheet(ws.name, cells, _fill_merged(cells, merges), ws.nrows, ws.ncols))
    finally:
        wb.release_resources()
    return sheets


def _load_xlsx(path: Path) -> list[Sheet]:
    wb = openpyxl.load_workbook(path, data_only=True, read_only=False)
    sheets = []
    for ws in wb.worksheets:
        if ws.sheet_state != "visible":
            continue
        cells: dict[tuple[int, int], object] = {}
        for row in ws.iter_rows():
            for c in row:
                v = _clean(c.value)
                if v is not None:
                    cells[(c.row, c.column)] = v
        merges = [(m.min_row, m.min_col, m.max_row, m.max_col) for m in ws.merged_cells.ranges]
        sheets.append(Sheet(ws.title, cells, _fill_merged(cells, merges), ws.max_row, ws.max_column))
    wb.close()
    return sheets

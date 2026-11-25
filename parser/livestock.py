"""Livestock tables: one animal per dataset folder (bovine_animals, sheep, goats, ...).

Two kinds of ELSTAT table, same layout (one visible sheet):

    Table 1: Holdings with Bovine animals by region broken down by size classes, year 2025
    Region                           | Total | 1-4 | 5-9 | ... | 50 and over

    Table 7: Sheep by region broken down by main categories, year 2025
    Region                           | Total Sheep | Ewes and ewe lambs put to the ram | ... | Rams | ...

    then a "Total" row (Greece) and the 13 regions in Greeklish (no regional units).

- The title gives the measure, the animal and the year. The year must match the
  year folder and the animal must match the dataset folder ("Sheep" -> sheep/).
- "Holdings with <animal>"  -> metric holdings, category "Holdings by herd size",
  items = size classes (number of animals in the holding).
  "<animal>"                -> metric animals (heads), category "Animals by type",
  items = categories of animal.
- The "Total ..." column becomes item "Total" and must equal the sum of the other
  columns; the regions must add up to Greece.
- Values are survey estimates, so they can have decimals.

A new kind of title is reported as a problem: add it to MEASURES (and its unit to
UNITS in parser/base.py).
"""
from __future__ import annotations

import re

from openpyxl.utils import get_column_letter

from . import regions as R
from .base import BaseTable, Column, Layout, SheetResult, parse_value
from .workbook import Sheet, cell_ref

# (metric, category written to the output, title subject regex -> group 1 = animal)
MEASURES = [
    ("holdings", "Holdings by herd size", re.compile(r"^holdings\s+with\s+(.+)$", re.I)),
    ("animals", "Animals by type", re.compile(r"^(?!holdings\b)([a-z][a-z ]*)$", re.I)),
]

# ELSTAT typos in column headers -> one spelling across years
LABEL_FIXES = {
    "Ewes and ewe lambs put t the ram": "Ewes and ewe lambs put to the ram",
    "Ewes not put the ram": "Ewes not put to the ram",
}

TITLE_RE = re.compile(r"^\s*Table\s+(\w+)\s*[:.]\s*(.+?)\s+by\s+region\b(.*)$", re.I)
YEAR_RE = re.compile(r"\byear\s+(\d{4})\b", re.I)


class LivestockTable(BaseTable):
    """Base parser for raw_data/livestock/<animal>/<year>/<file>."""

    # ------------------------------------------------------------ layout

    def find_anchor(self, sheet: Sheet) -> tuple[int, int] | None:
        """Header cell 'Region' (names column)."""
        hits = sheet.find(lambda v: isinstance(v, str) and R.normalise(v) == "region")
        return hits[0] if hits else None

    def detect_layout(self, sheet: Sheet, problems: list[str]) -> Layout | None:
        header_row, name_col = self.find_anchor(sheet)
        title_lines = []
        for r in range(1, header_row):
            for _, v in sorted(sheet.row_values(r).items()):
                if isinstance(v, str) and v.strip() and v not in title_lines:
                    title_lines.append(v.strip())
        return Layout(anchor_row=header_row, el_col=name_col, en_col=name_col,
                      units_row=header_row, units_text="", header_rows=[header_row],
                      code_row=None, title_lines=title_lines)

    def read_title(self, layout: Layout, problems: list[str]) -> tuple[str, str, str] | None:
        """(table, metric, category) from the title; checks year and animal against the folders."""
        for line in layout.title_lines:
            m = TITLE_RE.match(line)
            if not m:
                continue
            table, subject, rest = m.group(1).lower(), m.group(2).strip(), m.group(3)
            y = YEAR_RE.search(rest)
            if not y:
                problems.append(f"no 'year YYYY' in title {line!r}")
            elif y.group(1) != self.year:
                problems.append(f"title says year {y.group(1)} but folder says {self.year}")
            for metric, category, rx in MEASURES:
                mm = rx.match(subject)
                if mm:
                    animal = re.sub(r"\s+", "_", mm.group(1).strip().lower())
                    if animal != self.dataset:
                        problems.append(f"title is about {mm.group(1).strip()!r} but the file is in "
                                        f"the {self.dataset!r} folder")
                    return table, metric, category
            problems.append(f"unknown measure {subject!r} in title "
                            f"(add it to MEASURES in parser/livestock.py)")
            return None
        problems.append("title 'Table N: ... by region ..., year YYYY' not found above the 'Region' header")
        return None

    # ------------------------------------------------------------ sheet parsing

    def parse_sheet(self, sheet: Sheet) -> SheetResult:
        problems: list[str] = []
        layout = self.detect_layout(sheet, problems)
        res = SheetResult(sheet.name, "", layout, [], [], {}, problems)
        title = self.read_title(layout, problems)
        if title is None:
            return res
        res.table, metric, category = title

        header_row, name_col = layout.anchor_row, layout.el_col
        value_cols = [c for c in range(name_col + 1, sheet.max_col + 1) if sheet.text(header_row, c)]
        if not value_cols:
            problems.append(f"no column labels right of {cell_ref(header_row, name_col)}")
            return res
        for c in value_cols:
            label = re.sub(r"\s+", " ", sheet.text(header_row, c)).strip()
            item = "Total" if re.match(r"total\b", label, re.I) else LABEL_FIXES.get(label, label)
            res.columns.append(self.adjust_column(Column(c, [label], category, item, "", metric)))

        res.rows = self.data_rows(sheet, layout, value_cols, problems)
        for column in res.columns:
            for r, region in res.rows:
                raw = sheet.get(r, column.col)
                val, ok = parse_value(raw)
                if not ok:
                    problems.append(f"{cell_ref(r, column.col)}: unexpected value {raw!r}")
                res.values[(column.col, region.code)] = val

        if not problems:
            problems += self.check_regions(res)
            problems += self.item_checks(res)
        return res

    def data_rows(self, sheet: Sheet, layout: Layout, value_cols: list[int],
                  problems: list[str]) -> list[tuple[int, R.Region]]:
        rows: list[tuple[int, R.Region]] = []
        name_col = layout.el_col
        for r in range(layout.anchor_row + 1, sheet.max_row + 1):
            name = sheet.text(r, name_col)
            has_numbers = any(isinstance(sheet.get(r, c), (int, float)) for c in value_cols)
            if not name:
                if has_numbers:
                    problems.append(f"row {r}: values without a region name")
                continue
            region = R.REGIONS["GR"] if R.normalise(name) == "total" else R.resolve(None, name)
            if region and region.level != "unit":
                rows.append((r, region))
            elif region:
                problems.append(f"row {r}: regional unit {name!r} in a regions-only table")
            elif has_numbers:
                problems.append(f"row {r}: unknown region name {name!r} "
                                f"(add the spelling to ALIASES in parser/regions.py)")
            else:
                break                               # first footnote line: data ends here

        seen: dict[str, int] = {}
        for r, region in rows:
            if region.code in seen:
                problems.append(f"row {r}: {region.name_en} ({region.code}) appears twice "
                                f"(also row {seen[region.code]})")
            seen[region.code] = r
        if not rows or rows[0][1].level != "country":
            problems.append("first data row is not 'Total' (Greece)")
        missing = [x for x in R.REGIONS.values() if x.level != "unit" and x.code not in seen]
        if missing:
            problems.append("missing regions: " + ", ".join(f"{m.name_en} ({m.code})" for m in missing))
        return rows

    # ------------------------------------------------------------ hooks

    def adjust_column(self, column: Column) -> Column:
        """Hook: rename a column. Livestock has no cross-year name mapping yet."""
        return column

    def item_checks(self, res: SheetResult) -> list[str]:
        """Size classes / animal types add up to 'Total' in every region."""
        totals = [c for c in res.columns if c.item == "Total"]
        if len(totals) != 1:
            return [f"expected one 'Total' column, found {len(totals)} "
                    f"(columns: {', '.join(c.labels[0] for c in res.columns)})"]
        parts = [c for c in res.columns if c is not totals[0]]
        if totals[0].metric == "holdings":
            for c in parts:
                if not re.search(r"\d", c.item):
                    return [f"column {get_column_letter(c.col)} {c.item!r} is not a size class"]
        return self.check_sum(res, parts, totals[0])

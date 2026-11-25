"""Generic parser for ELSTAT regional agricultural tables.

Layout handled (found by anchors, never by fixed cell positions):

    title rows            "Table 2a. Cereals for grain ..."      -> table id
    units row             "Areas in stremmas ..., production in tons"
    header rows           merged, Greek and English mixed      -> English labels only
    metric code row       1 = area, 2 = production             (optional)
    "Greece Total" row    Greek name in first column, English name in the
    13 regions + 74 units column headed "Regions and Regional Unities"
    footnotes

How area vs production is decided for each column, in order:
    1. metric code row (1/2)
    2. metric words in the header ("Areas", "Production of grapes for: wine")
    3. units row mentions only one unit (stremmas only -> area, tons only -> production)
    4. header label contains "area" / "production"

Sector, dataset and year come from the folder: raw_data/<sector>/<dataset>/<year>/<file>.xlsx

Per-table differences go in a subclass in parser/tables/ that overrides only the
hook that differs (see the "Hooks" section below). Any problem is collected and
raised as ParseError naming the file and year, so the parser can be adapted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import regions as R
from .items import canonical
from openpyxl.utils import get_column_letter

from .workbook import Sheet, cell_ref, load_visible_sheets

CSV_FIELDS = [
    "sector", "year", "dataset", "table", "category", "item", "detail",
    "level", "region", "region_code", "metric", "value", "unit",
]

UNITS = {"area": "stremmas", "production": "tons", "holdings": "holdings", "animals": "heads"}
DASHES = set("-‐‑‒–—―−….")
CODE_RE = re.compile(r"^([12])(?:\.0)?\s*(?:\(\d+\))?$")
GREEK_RE = re.compile(r"[Ͱ-Ͽἀ-῿]")
LATIN_RE = re.compile(r"[A-Za-z]")
# Greek capitals that look like Latin ones (e.g. "Αromatic plants" in ELSTAT headers)
LOOKALIKES = str.maketrans("ΑΒΕΖΗΙΚΜΝΟΡΤΥΧ", "ABEZHIKMNOPTYX")


class ParseError(Exception):
    def __init__(self, file: Path, year: str, problems: list[str]):
        self.file, self.year, self.problems = file, year, problems
        lines = "\n".join(f"  - {p}" for p in problems)
        super().__init__(f"{file} (year {year}): {len(problems)} problem(s)\n{lines}")


@dataclass
class Layout:
    anchor_row: int          # "Greece Total" row
    el_col: int              # Greek names column
    en_col: int              # English names column
    units_row: int
    units_text: str
    header_rows: list[int]
    code_row: int | None
    title_lines: list[str]


@dataclass
class Column:
    col: int
    labels: list[str]        # English header labels top -> bottom (metric words included)
    category: str
    item: str
    detail: str
    metric: str

    @property
    def key(self) -> str:
        return " / ".join(p for p in (self.category, self.item, self.detail) if p)


@dataclass
class SheetResult:
    sheet: str
    table: str
    layout: Layout
    rows: list[tuple[int, R.Region]]
    columns: list[Column]
    values: dict[tuple[int, str], float | None]     # (col, region_code) -> value
    problems: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- text helpers

def english_part(text: str) -> str:
    """English part of a header cell that may hold Greek, English or both."""
    text = str(text).strip()
    greek, latin = len(GREEK_RE.findall(text)), len(LATIN_RE.findall(text))
    if latin == 0:
        return ""
    if latin >= 4 * greek:                       # English (maybe a stray Greek lookalike)
        return text.translate(LOOKALIKES)
    parts = re.split(r"\s{2,}|\s+-\s+|\n", text)  # "Εκτάσεις   Areas", "Ελαιόλαδο - Olive oil"
    keep = [p for p in parts if len(LATIN_RE.findall(p)) > len(GREEK_RE.findall(p))]
    return " ".join(p.translate(LOOKALIKES) for p in keep)


def clean_label(text: str) -> str:
    text = re.sub(r"\(\d+\)", "", text)          # footnote markers "Other(1)"
    text = re.sub(r"\s+", " ", text)
    return text.strip(" :;,")


def parse_value(v) -> tuple[float | None, bool]:
    """(value, ok). Dashes and blanks mean 'no data' -> None."""
    if v is None:
        return None, True
    if isinstance(v, bool):
        return None, False
    if isinstance(v, (int, float)):
        return float(v), True
    s = str(v).strip().replace(" ", "").replace(" ", "")
    if not s or all(ch in DASHES for ch in s):
        return None, True
    try:
        return float(s.replace(",", ".")), True
    except ValueError:
        return None, False


# ---------------------------------------------------------------- base parser

class BaseTable:
    """Generic ELSTAT table parser. Subclass and override hooks for table quirks."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.year = self.path.parent.name
        self.dataset = self.path.parent.parent.name
        self.sector = self.path.parent.parent.parent.name

    # ------------------------------------------------------------ entry points

    def parse(self) -> list[dict]:
        """Parse the file; raise ParseError on any problem."""
        results, problems = self.analyse()
        if problems:
            raise ParseError(self.path, self.year, problems)
        return self.to_records(results)

    def analyse(self) -> tuple[list[SheetResult], list[str]]:
        """Parse without raising: returns sheet results and all problems found."""
        problems: list[str] = []
        if not re.fullmatch(r"\d{4}", self.year):
            problems.append(f"year folder {self.year!r} is not a 4-digit year "
                            f"(expected raw_data/<sector>/<dataset>/<year>/<file>)")
        sheets = [s for s in load_visible_sheets(self.path) if self.find_anchor(s)]
        self.sheets = {s.name: s for s in sheets}
        if not sheets:
            return [], problems + ["no visible sheet contains a 'Greece Total' row"]
        results = []
        for sheet in sheets:
            res = self.parse_sheet(sheet)
            problems += [f"[sheet {sheet.name!r}] {p}" for p in res.problems]
            results.append(res)
        problems += self.check_duplicates(results)
        return results, problems

    # ------------------------------------------------------------ layout

    def find_anchor(self, sheet: Sheet) -> tuple[int, int] | None:
        hits = sheet.find(lambda v: isinstance(v, str) and R.normalise(v) == "greece total")
        return hits[0] if hits else None

    def detect_layout(self, sheet: Sheet, problems: list[str]) -> Layout | None:
        anchor_row, en_col = self.find_anchor(sheet)
        row_cols = sorted(sheet.row_values(anchor_row))
        el_col = row_cols[0]
        if el_col >= en_col:
            problems.append(f"Greek name column not found left of English column at {cell_ref(anchor_row, en_col)}")
            return None

        units_row, units_text = None, ""
        for r in range(anchor_row - 1, 0, -1):
            texts = [str(v) for v in sheet.row_values(r).values() if isinstance(v, str)]
            eng = " ".join(t for t in texts if LATIN_RE.search(t)).lower()
            if re.search(r"stremma|\btons?\b|\btonnes?\b", eng):
                units_row, units_text = r, eng
                break
        if units_row is None:
            problems.append("units row ('Areas in stremmas ...' / 'In tons') not found above 'Greece Total'")
            return None

        header_rows = list(range(units_row + 1, anchor_row))
        code_row = None
        for r in header_rows:
            vals = [sheet.header_text(r, c) for c in range(el_col + 1, en_col)]
            vals = [v for v in vals if v]
            codes = [v for v in vals if CODE_RE.match(v)]
            if len(codes) >= 2 and len(codes) * 2 >= len(vals):
                code_row = r
        title_lines = []
        for r in range(1, units_row):
            for c, v in sorted(sheet.row_values(r).items()):
                if isinstance(v, str) and v not in title_lines:
                    title_lines.append(v)
        return Layout(anchor_row, el_col, en_col, units_row, units_text,
                      header_rows, code_row, title_lines)

    # ------------------------------------------------------------ hooks

    def table_id(self, layout: Layout) -> str | None:
        """Table number from the title, e.g. 'Table 2a. Cereals ...' -> '2a'."""
        for line in layout.title_lines:
            m = re.search(r"\bTable\s+(\d+[a-z]?)\b", line, re.I)
            if m:
                return m.group(1).lower()
        for line in layout.title_lines:                 # "7. Production of olive oil ..."
            if english_part(line):
                m = re.match(r"\s*(\d+[a-z]?)\.\s", english_part(line))
                if m:
                    return m.group(1).lower()
        return None

    def header_labels(self, sheet: Sheet, layout: Layout, col: int) -> list[str]:
        labels: list[str] = []
        for r in layout.header_rows:
            if r == layout.code_row:
                continue
            label = clean_label(english_part(sheet.header_text(r, col)))
            if label and (not labels or labels[-1].lower() != label.lower()):
                labels.append(label)
        return labels

    def build_column(self, sheet: Sheet, layout: Layout, col: int,
                     problems: list[str]) -> Column | None:
        where = get_column_letter(col)
        labels = self.header_labels(sheet, layout, col)

        metric = None
        if layout.code_row:
            m = CODE_RE.match(sheet.header_text(layout.code_row, col))
            if m:
                metric = "area" if m.group(1) == "1" else "production"

        path, detail, label_metric = [], "", None
        for i, label in enumerate(labels):
            if re.fullmatch(r"areas?", label, re.I):
                label_metric = "area"
                continue
            if re.match(r"(total\s+)?production\b", label, re.I):
                label_metric = "production"
                detail = ", ".join(labels[i + 1:])
                break
            path.append(label)

        metric = metric or label_metric or self.single_unit_metric(layout)
        if metric is None:
            joined = " ".join(labels).lower()
            if "production" in joined:
                metric = "production"
            elif re.search(r"\bareas?\b", joined):
                metric = "area"
        if metric is None:
            problems.append(f"column {where}: cannot tell area or production (labels {labels})")
            return None
        if not path:
            problems.append(f"column {where}: no English header label found")
            return None
        unit_word = {"area": "stremma", "production": "ton"}[metric]
        if unit_word not in layout.units_text:
            problems.append(f"column {where}: metric {metric} but units row says {layout.units_text!r}")
        category = path[0]
        item = ", ".join(path[1:]) or path[0]
        return self.adjust_column(Column(col, labels, category, item, detail, metric))

    def single_unit_metric(self, layout: Layout) -> str | None:
        has_area = "stremma" in layout.units_text
        has_prod = bool(re.search(r"\btons?\b|\btonnes?\b", layout.units_text))
        if has_area and not has_prod:
            return "area"
        if has_prod and not has_area:
            return "production"
        return None

    def adjust_column(self, column: Column) -> Column:
        """Hook: rename / regroup a column (category, item, detail).
        The default applies the cross-year crop-name mapping in parser/items.py."""
        column.category, column.item = canonical(self.dataset, column.category, column.item)
        return column

    def skip_column(self, column: Column) -> bool:
        """Hook: return True to leave a column out of the output."""
        return False

    def item_checks(self, res: SheetResult) -> list[str]:
        """Hook: sub-item sum checks for this table. Use self.check_sum()."""
        return []

    # ------------------------------------------------------------ sheet parsing

    def parse_sheet(self, sheet: Sheet) -> SheetResult:
        problems: list[str] = []
        layout = self.detect_layout(sheet, problems)
        res = SheetResult(sheet.name, "", layout, [], [], {}, problems)
        if layout is None:
            return res

        res.table = self.table_id(layout) or ""
        if not res.table:
            problems.append("table number not found in title rows")

        value_cols = [c for c in range(layout.el_col + 1, layout.en_col)]
        res.rows = self.data_rows(sheet, layout, value_cols, problems)
        used_cols = [c for c in value_cols
                     if any(sheet.get(r, c) is not None for r, _ in res.rows)]
        for c in used_cols:
            column = self.build_column(sheet, layout, c, problems)
            if column and not self.skip_column(column):
                res.columns.append(column)

        for column in res.columns:
            for r, region in res.rows:
                raw = sheet.get(r, column.col)
                val, ok = parse_value(raw)
                if not ok:
                    problems.append(f"{cell_ref(r, column.col)}: unexpected value {raw!r}")
                res.values[(column.col, region.code)] = val

        if not problems:                          # sums only make sense on a clean read
            problems += self.check_regions(res)
            problems += self.item_checks(res)
        return res

    def data_rows(self, sheet: Sheet, layout: Layout, value_cols: list[int],
                  problems: list[str]) -> list[tuple[int, R.Region]]:
        rows: list[tuple[int, R.Region]] = []
        for r in range(layout.anchor_row, sheet.max_row + 1):
            el, en = sheet.text(r, layout.el_col), sheet.text(r, layout.en_col)
            has_numbers = any(isinstance(sheet.get(r, c), (int, float)) for c in value_cols)
            if not el and not en:
                if has_numbers:
                    problems.append(f"row {r}: values without a region name")
                continue
            region = R.resolve(el, en)
            if region:
                rows.append((r, region))
            elif has_numbers:
                problems.append(f"row {r}: unknown region name {el!r} / {en!r} "
                                f"(add the spelling to ALIASES in parser/regions.py)")
            else:
                break                               # first footnote line: data ends here

        # structure: Greece, then each region followed by its own units, all present once
        seen: dict[str, int] = {}
        current_region = None
        for r, region in rows:
            if region.code in seen:
                problems.append(f"row {r}: {region.name_en} ({region.code}) appears twice "
                                f"(also row {seen[region.code]})")
            seen[region.code] = r
            if region.level == "region":
                current_region = region.code
            elif region.level == "unit" and region.parent != current_region:
                problems.append(f"row {r}: unit {region.name_en} ({region.code}) is not under "
                                f"its region {region.parent}")
        if not rows or rows[0][1].level != "country":
            problems.append("first data row is not 'Greece Total'")
        missing = [x for x in R.REGIONS.values() if x.code not in seen]
        if missing:
            problems.append("missing regions/units: " +
                            ", ".join(f"{m.name_en} ({m.code})" for m in missing))
        return rows

    # ------------------------------------------------------------ checks

    @staticmethod
    def tolerance(n_parts: int, total: float) -> float:
        """Allow rounding: half a unit per part, or 0.1 % of the total."""
        return max(0.5 * n_parts, 0.001 * abs(total), 0.01)

    def check_regions(self, res: SheetResult) -> list[str]:
        """Regional units sum to their region; regions sum to Greece Total."""
        problems = []
        present = {region.code for _, region in res.rows}
        for column in res.columns:
            for parent in [x for x in R.REGIONS.values() if x.level != "unit"]:
                kids = [k.code for k in R.children(parent.code) if k.code in present]
                if not kids:
                    continue
                total = res.values.get((column.col, parent.code)) or 0.0
                parts = sum(res.values.get((column.col, k)) or 0.0 for k in kids)
                if abs(total - parts) > self.tolerance(len(kids), total):
                    level = "regions" if parent.level == "country" else "units"
                    problems.append(
                        f"sum check [{column.key} | {column.metric}]: {level} of "
                        f"{parent.name_en} add up to {parts:,.3f} but table says {total:,.3f} "
                        f"(diff {parts - total:+,.3f})")
        return problems

    def check_sum(self, res: SheetResult, parts: list[Column], total: Column) -> list[str]:
        """Helper for item_checks: sum of `parts` equals `total` in every region."""
        problems = []
        for _, region in res.rows:
            t = res.values.get((total.col, region.code)) or 0.0
            p = sum(res.values.get((c.col, region.code)) or 0.0 for c in parts)
            if abs(t - p) > self.tolerance(len(parts), t):
                problems.append(
                    f"item sum check [{total.key} | {total.metric}] in {region.name_en}: "
                    f"parts add up to {p:,.3f} but total is {t:,.3f}")
        return problems

    def check_duplicates(self, results: list[SheetResult]) -> list[str]:
        """The same value appearing on two sheets must agree."""
        problems, seen = [], {}
        for res in results:
            for column in res.columns:
                for _, region in res.rows:
                    key = (res.table, column.key, column.metric, region.code)
                    val = res.values.get((column.col, region.code))
                    if key in seen and seen[key][1] != val:
                        problems.append(f"{column.key} | {column.metric} | {region.name_en}: "
                                        f"{seen[key][1]} on sheet {seen[key][0]!r} vs {val} on {res.sheet!r}")
                    seen.setdefault(key, (res.sheet, val))
        return problems

    # ------------------------------------------------------------ output

    def to_records(self, results: list[SheetResult]) -> list[dict]:
        records, seen = [], set()
        for res in results:
            for column in res.columns:
                for _, region in res.rows:
                    val = res.values.get((column.col, region.code))
                    key = (res.table, column.key, column.metric, region.code)
                    if val is None or key in seen:
                        continue
                    seen.add(key)
                    val = round(val, 3)
                    records.append({
                        "sector": self.sector, "year": self.year, "dataset": self.dataset,
                        "table": res.table, "category": column.category, "item": column.item,
                        "detail": column.detail, "level": region.level,
                        "region": region.name_en, "region_code": region.code,
                        "metric": column.metric,
                        "value": int(val) if val == int(val) else val,
                        "unit": UNITS[column.metric],
                    })
        return records

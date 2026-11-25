"""Command line.

    python -m parser run                    parse raw_data/<sector>/<dataset>/<year>/ -> data/agri.csv (stops on any problem)
    python -m parser run --only vegetables  parse selected dataset (or sector) folders
    python -m parser run --skip-failed      write what parses, list the files that failed
    python -m parser inspect FILE.xlsx      show what the parser detects in one file
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from openpyxl.utils import get_column_letter

from .base import CSV_FIELDS, UNITS, ParseError
from .tables import table_class

ROOT = Path(__file__).resolve().parent.parent


def find_files(raw: Path, only: list[str] | None) -> list[Path]:
    files = []
    for p in sorted(raw.glob("*/*/*/*")):              # <sector>/<dataset>/<year>/<file>
        if p.name.startswith("~$") or not p.is_file():
            continue
        if only and p.parent.parent.name not in only and p.parent.parent.parent.name not in only:
            continue
        files.append(p)
    return files


def cmd_run(args) -> int:
    files = find_files(Path(args.raw), args.only)
    if not files:
        print(f"No files found under {args.raw}/<sector>/<dataset>/<year>/", file=sys.stderr)
        return 1
    records, failed = [], []
    for path in files:
        if path.suffix.lower() not in (".xlsx", ".xls"):
            failed.append(f"{path}: unsupported file type {path.suffix} (expected .xlsx or .xls)")
            continue
        try:
            rows = table_class(path)(path).parse()
        except ParseError as e:
            failed.append(str(e))
            continue
        except ValueError as e:
            failed.append(f"{path}: {e}")
            continue
        print(f"ok    {path}  ({len(rows)} values)")
        records += rows

    if failed:
        written = "Skipped them, writing the rest." if args.skip_failed else "Nothing was written."
        print(f"\nFAILED: {len(failed)} of {len(files)} file(s). {written}\n",
              file=sys.stderr)
        for f in failed:
            print(f, file=sys.stderr)
        if not args.skip_failed:
            return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(records)
    print(f"\nWrote {len(records)} rows from {len(files) - len(failed)} file(s) to {out}")

    # same records for the dashboard, as JSON
    out_json = out.with_suffix(".json")
    with out_json.open("w", encoding="utf-8") as fh:
        json.dump(records, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"Wrote {out_json}")
    return 0


def fmt_num(v: float | None, decimals: int = 3) -> str:
    if v is None:
        return "—"
    return f"{v:,.{decimals}f}".rstrip("0").rstrip(".")


def print_item_values(res, query: str) -> None:
    """Per region: area, production (one column per detail) and yield for matching items."""
    groups: dict[tuple[str, str], list] = {}
    for c in res.columns:
        groups.setdefault((c.category, c.item), []).append(c)
    q = query.lower()
    matches = {k: v for k, v in groups.items() if q in f"{k[0]} | {k[1]}".lower()}
    if not matches:
        print(f"\n   no item matches {query!r}. Items: " +
              "; ".join(f"{k[0]} | {k[1]}" for k in groups))
        return
    for (category, item), cols in matches.items():
        area = next((c for c in cols if c.metric == "area"), None)
        prods = [c for c in cols if c.metric == "production"]
        heads = []
        if area:
            heads.append(("area (stremmas)", area))
        for p in prods:
            heads.append((f"production{' ' + p.detail if p.detail else ''} (tons)", p))
        with_yield = area is not None and len(prods) == 1
        title = category if category == item else f"{category} | {item}"
        print(f"\n   == {title}")
        widths = [max(18, len(h) + 2) for h, _ in heads]
        line = f"   {'code':<9} {'region':<32}" + "".join(f"{h:>{w}}" for (h, _), w in zip(heads, widths))
        if with_yield:
            line += f"{'yield (kg/stremma)':>20}"
        print(line)
        for _, region in res.rows:
            indent = {"country": "", "region": "  ", "unit": "    "}[region.level]
            vals = [res.values.get((c.col, region.code)) for _, c in heads]
            line = f"   {region.code:<9} {indent + region.name_en:<32}" + \
                   "".join(f"{fmt_num(v):>{w}}" for v, w in zip(vals, widths))
            if with_yield:
                a = res.values.get((area.col, region.code))
                p = res.values.get((prods[0].col, region.code))
                y = p * 1000 / a if a and p is not None else None
                line += f"{fmt_num(y, 1):>20}"
            print(line)


def sheet_text(table, sheet_name: str, row: int, col: int) -> str:
    return table.sheets[sheet_name].text(row, col)


def cmd_inspect(args) -> int:
    path = Path(args.file)
    table = table_class(path)(path)
    results, problems = table.analyse()
    print(f"file     {path}\nsector   {table.sector}\ndataset  {table.dataset}\nyear     {table.year}\n"
          f"parser   {type(table).__name__}")
    for res in results:
        lay = res.layout
        print(f"\n== sheet {res.sheet!r}  table {res.table or '?'}")
        if lay is None:
            continue
        print(f"   Greece Total row {lay.anchor_row}, names in columns "
              f"{get_column_letter(lay.el_col)} (Greek) / {get_column_letter(lay.en_col)} (English)")
        print(f"   units row {lay.units_row}: {lay.units_text}")
        print(f"   header rows {lay.header_rows[0] if lay.header_rows else '-'}-"
              f"{lay.header_rows[-1] if lay.header_rows else '-'}, metric code row {lay.code_row or 'none'}")
        print(f"   {len(res.rows)} data rows")
        print(f"\n   {'col':<4} {'metric':<11} {'Greece total':>16}  category | item | detail")
        for c in res.columns:
            v = res.values.get((c.col, "GR"))
            total = "—" if v is None else f"{v:,.3f}".rstrip("0").rstrip(".")
            unit = UNITS[c.metric] if v is not None else ""
            print(f"   {get_column_letter(c.col):<4} {c.metric:<11} {total:>16} {unit:<8} "
                  f"{c.category} | {c.item}{' | ' + c.detail if c.detail else ''}")

        if args.item is not None:
            print_item_values(res, args.item)
        elif not args.no_regions:
            print(f"\n   {'row':<5} {'level':<8} {'code':<9} {'matched to':<30} name in file (Greek / English)")
            for r, region in res.rows:
                indent = {"country": "", "region": "  ", "unit": "    "}[region.level]
                name_el = sheet_text(table, res.sheet, r, lay.el_col)
                name_en = sheet_text(table, res.sheet, r, lay.en_col)
                print(f"   {r:<5} {region.level:<8} {region.code:<9} "
                      f"{indent + region.name_en:<30} {name_el} / {name_en or '(none)'}")
    print(f"\n{len(problems)} problem(s)")
    for p in problems:
        print(f"  - {p}")
    return 1 if problems else 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m parser")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="parse all files into one CSV")
    run.add_argument("--raw", default=str(ROOT / "raw_data"))
    run.add_argument("--out", default=str(ROOT / "data" / "agri.csv"))
    run.add_argument("--only", nargs="*", help="sector or dataset folder names to include")
    run.add_argument("--skip-failed", action="store_true",
                     help="write the files that parse and list the failed ones, instead of writing nothing")
    run.set_defaults(func=cmd_run)
    ins = sub.add_parser("inspect", help="show detected layout of one file")
    ins.add_argument("file")
    ins.add_argument("--no-regions", action="store_true", help="hide the region/NUTS list")
    ins.add_argument("--item", nargs="?", const="",
                     help="per-region area, production and yield for items matching this text "
                          "(e.g. --item durum); --item alone shows all items")
    ins.set_defaults(func=cmd_inspect)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

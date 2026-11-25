"""Offline anomaly scan.

    python -m analysis                 data/agri.json -> data/anomalies.csv + data/anomalies.md
    python -m analysis --top 40        rows per dataset in the Markdown report

Run `python -m parser run` first so data/agri.json is current.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

from .anomalies import FIELDS, load, scan

ROOT = Path(__file__).resolve().parent.parent

KIND_TITLE = {
    "name_gap": "Crop name missing in some years",
    "spike": "One-year spike or dip (likely data error)",
    "yield_out_of_range": "Yield far outside the usual range",
    "share_shift": "Share of Greece left its usual range",
    "hard_change": "Hard change in the national total",
    "appeared": "Appeared",
    "disappeared": "Disappeared",
    "yield_change": "Yield moved differently from Greece",
}


def md_table(rows: list[dict]) -> str:
    out = ["| sev | kind | crop | metric | where | years | change | Greece | note |",
           "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        crop = r["category"] if r["item"] == r["category"] else f"{r['category']} · {r['item']}"
        if r["detail"]:
            crop += f" · {r['detail']}"
        where = f"{r['region']} ({r['region_code']})" if r["kind"] != "name_gap" else "—"
        yrs = f"{r['year_from']}→{r['year']}" if r["year_from"] else str(r["year"])
        chg = f"{r['change_pct']:+}%" if r["change_pct"] != "" else (f"{r['value']}" if r["value"] != "" else "")
        gr = f"{r['greece_change_pct']:+}%" if r["greece_change_pct"] != "" else ""
        note = r["note"] + (f"<br><small>{r['history']}</small>" if r["history"] else "")
        out.append(f"| {r['severity']} | {r['kind']} | {crop} | {r['metric']} | {where} | {yrs} | {chg} | {gr} | {note} |")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m analysis")
    ap.add_argument("--data", default=str(ROOT / "data" / "agri.json"))
    ap.add_argument("--out", default=str(ROOT / "data" / "anomalies.csv"))
    ap.add_argument("--top", type=int, default=25, help="rows per dataset in the Markdown report")
    args = ap.parse_args()

    data = Path(args.data)
    if not data.exists():
        print(f"{data} not found. Run: python -m parser run", file=sys.stderr)
        return 1
    series, meta, ds_years, names = load(data)
    issues = scan(series, meta, ds_years, names)

    out = Path(args.out)
    with out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(issues)
    # same list for the dashboard
    out.with_suffix(".json").write_text(
        json.dumps([{k: i[k] for k in FIELDS} for i in issues], ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8")

    # Markdown report, grouped by dataset
    lines = ["# Anomaly report", "",
             f"Source: `{data.name}`. {len(issues)} issue(s). Full list: `{out.name}`.", "",
             "Each line is something to check, not a conclusion. *spike* and *yield_out_of_range* "
             "usually point to data errors; *hard_change* and *yield_change* can be real events.", ""]
    lines += ["| dataset | years | high | medium |", "|---|---|---|---|"]
    for ds, yrs in sorted(ds_years.items()):
        c = Counter(i["severity"] for i in issues if i["dataset"] == ds)
        lines.append(f"| {ds} | {yrs[0]}–{yrs[-1]} ({len(yrs)}) | {c['high']} | {c['medium']} |")
    for ds, yrs in sorted(ds_years.items()):
        rows = [i for i in issues if i["dataset"] == ds]
        lines += ["", f"## {ds} ({yrs[0]}–{yrs[-1]})", ""]
        if len(yrs) < 2:
            lines.append("Only one year loaded: no year-on-year checks possible.")
            continue
        if not rows:
            lines.append("No issues found.")
            continue
        kinds = Counter(r["kind"] for r in rows)
        lines.append(", ".join(f"{KIND_TITLE[k]}: {n}" for k, n in kinds.most_common()))
        lines += ["", md_table(rows[: args.top])]
        if len(rows) > args.top:
            lines.append(f"\n…and {len(rows) - args.top} more in `{out.name}`.")
    md = out.with_suffix(".md")
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    c = Counter((i["severity"], i["kind"]) for i in issues)
    print(f"{len(issues)} issue(s) -> {out}\n                -> {md}")
    for (sev, kind), n in sorted(c.items()):
        print(f"  {sev:<7} {kind:<20} {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

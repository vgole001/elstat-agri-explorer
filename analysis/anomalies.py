"""Offline anomaly scan over every dataset, crop, region and year in data/agri.json.

It flags changes that need a person to look at them, whatever the cause (weather,
policy, reporting, or a data error). It does not decide which one it is; the `kind`
says what pattern was seen and the note says what to check.

Kinds
-----
name_gap            a crop name exists only in some years -> probably renamed by ELSTAT
spike               value jumps (or dips) >= x3 for one year and returns -> likely data error
share_shift         a place's share of Greece's total leaves its usual range, and the place
                    moved differently from the rest of Greece -> local event or error
hard_change         national total (Greece) moves >= x1.5 in one year
appeared            from nothing to a relevant amount
disappeared         from a relevant amount to nothing
yield_out_of_range  production / area >= x3 or <= /3 the usual for that crop -> units / typo?
yield_change        yield moved >= 35 % differently from the rest of Greece, outside its usual
                    ratio to Greece's yield -> local event?

Places are compared with the *rest of Greece* (Greece minus the place), not Greece itself:
a big region pulls Greece's total with it and would hide its own change.

Only relevant amounts are considered: at least MIN_SHARE of Greece's total for that
crop and metric, and at least MIN_ABS stremmas / tons. Tiny values swing wildly and
are skipped.
"""
from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------- thresholds
MIN_SHARE = 0.01                     # >= 1 % of Greece's value (either year)
MIN_ABS = {"area": 1000, "production": 100, "holdings": 20, "animals": 1000}   # stremmas / tons / holdings / heads
HARD_FACTOR = 2.0                    # short history (< 3 years): only x2 or /2 moves count
HARD_FACTOR_GREECE = 1.5             # national level: x1.5 or /1.5
SHARE_MIN_PP = 1.0                   # share of Greece must move >= 1 percentage point
SHARE_LOCAL = 1.5                    # and the place must diverge from the rest of Greece by x1.5
SHARE_OUTSIDE = 1.2                  # and land >= 20 % outside its share range of the other years
SHARE_HIGH_PP = 5.0                  # >= 5 points (and a large absolute change) -> high
SPIKE_FACTOR = 3.0                   # one-year jump/dip vs both neighbours
SPIKE_NEIGHBOURS = 2.0               # neighbours within x2 of each other
YIELD_FACTOR = 3.0                   # yield vs crop's usual yield
YIELD_LOCAL = 1.35                   # region yield change vs Greece's yield change
YIELD_MIN_AREA = 1000                # stremmas, for yield checks
HIGH_IMPACT = 0.05                   # change >= 5 % of Greece's total -> high severity
MIN_ABS_HIGH = {"area": 10000, "production": 2000, "holdings": 200, "animals": 20000}   # and at least this much -> high
YIELD_OWN_NORMAL = 1.5               # yield within x1.5 of the place's own median -> normal there

FIELDS = ["severity", "kind", "dataset", "category", "item", "detail", "metric", "level",
          "region", "region_code", "year_from", "year", "value_from", "value", "change_pct",
          "greece_change_pct", "share_from_pct", "share_of_greece_pct", "history", "note"]


# ---------------------------------------------------------------- data

def load(path: Path):
    rows = json.loads(path.read_text(encoding="utf-8"))
    series = defaultdict(dict)              # (ds, cat, item, detail, metric, code) -> {year: value}
    meta = {}                                # code -> (name, level)
    years = defaultdict(set)                 # ds -> years
    names = defaultdict(set)                 # (ds, cat, item, detail) -> years
    for r in rows:
        y = int(r["year"])
        series[(r["dataset"], r["category"], r["item"], r["detail"], r["metric"], r["region_code"])][y] = float(r["value"])
        meta[r["region_code"]] = (r["region"], r["level"])
        years[r["dataset"]].add(y)
        names[(r["dataset"], r["category"], r["item"], r["detail"])].add(y)

    # production split by use (grapes): total over uses, for yield
    split = defaultdict(lambda: defaultdict(float))
    has_total = {k[:3] + (k[5],) for k in series if k[4] == "production" and k[3] == ""}
    for k, v in series.items():
        if k[4] == "production" and k[3] != "" and k[:3] + (k[5],) not in has_total:
            for y, val in v.items():
                split[k[:3] + ("", "production", k[5])][y] += val
    series.update({k: dict(v) for k, v in split.items()})

    # yield (kg per stremma) where area and production both exist
    for k, a in list(series.items()):
        if k[4] != "area" or k[3] != "":
            continue
        p = series.get(k[:4] + ("production", k[5]))
        if not p:
            continue
        yv = {y: p[y] * 1000 / a[y] for y in a if a[y] > 0 and p.get(y) is not None}
        if yv:
            series[k[:4] + ("yield", k[5])] = yv
    return series, meta, {d: sorted(v) for d, v in years.items()}, names


def fmt(v: float, metric: str) -> str:
    if metric == "yield":
        return f"{v:,.0f}"
    return f"{v:,.0f}" if abs(v) >= 100 or v == 0 else f"{v:,.1f}"


def pct(new: float, old: float) -> float | None:
    return None if not old else (new - old) / old * 100


# ---------------------------------------------------------------- scan

def scan(series, meta, ds_years, names) -> list[dict]:
    issues: list[dict] = []

    def add(kind, severity, key, y0, y1, v0, v1, g0, g1, note):
        ds, cat, item, detail, metric, code = key
        name, level = meta.get(code, (code, ""))
        hist = series.get(key, {})
        issues.append({
            "severity": severity, "kind": kind, "dataset": ds, "category": cat, "item": item,
            "detail": detail, "metric": metric, "level": level, "region": name, "region_code": code,
            "year_from": y0 or "", "year": y1, "value_from": "" if v0 is None else round(v0, 1),
            "value": "" if v1 is None else round(v1, 1),
            "change_pct": "" if v0 in (None, 0) or v1 is None else round(pct(v1, v0), 1),
            "greece_change_pct": "" if not g0 or g1 is None else round(pct(g1, g0), 1),
            "share_from_pct": "",
            "share_of_greece_pct": "" if not g1 or v1 is None or code == "GR" or metric == "yield"
                                   else round(v1 / g1 * 100, 2),
            "history": " | ".join(f"{y}: {fmt(hist[y], metric)}" for y in ds_years[ds] if y in hist),
            "note": note,
            "_score": 0.0,
        })
        return issues[-1]

    # 1. crop names that exist only in some years
    for (ds, cat, item, detail), yrs in sorted(names.items()):
        missing = [y for y in ds_years[ds] if y not in yrs]
        if missing and len(ds_years[ds]) > 1:
            key = (ds, cat, item, detail, "", "GR")
            i = add("name_gap", "high", key, None, min(yrs), None, None, None, None,
                    f"Name only in {sorted(yrs)}, missing in {missing}. Probably renamed by ELSTAT: "
                    f"map the old name to the new one in parser/items.py.")
            i["history"] = ""
            i["_score"] = 10

    # 2. area / production changes
    for key, vals in series.items():
        ds, cat, item, detail, metric, code = key
        if metric == "yield":
            continue
        gvals = series.get(key[:5] + ("GR",), {})
        yrs = ds_years[ds]
        covered = set()

        # spikes: y-1, y, y+1 consecutive dataset years
        for i in range(1, len(yrs) - 1):
            ya, yb, yc = yrs[i - 1], yrs[i], yrs[i + 1]
            a, b, c = vals.get(ya, 0), vals.get(yb, 0), vals.get(yc, 0)
            if min(a, b, c) <= 0 or not relevant(b, max(a, c), gvals.get(yb), metric, code):
                continue
            if max(a, c) / min(a, c) > SPIKE_NEIGHBOURS:
                continue
            up = b / a >= SPIKE_FACTOR and b / c >= SPIKE_FACTOR
            down = a / b >= SPIKE_FACTOR and c / b >= SPIKE_FACTOR
            if up or down:
                sev = "high" if abs(b - a) >= MIN_ABS_HIGH[metric] else "medium"
                it = add("spike", sev, key, ya, yb, a, b, gvals.get(ya), gvals.get(yb),
                         f"{'Jumps' if up else 'Drops'} x{(b / a if up else a / b):.1f} in {yb} and returns in {yc}. "
                         f"Likely a data or entry error: check the {yb} Excel.")
                it["_score"] = 5 + impact(a, b, gvals.get(ya), gvals.get(yb))
                covered |= {(ya, yb), (yb, yc)}

        # year-on-year changes
        for ya, yb in zip(yrs, yrs[1:]):
            if (ya, yb) in covered:
                continue
            a, b = vals.get(ya, 0), vals.get(yb, 0)
            ga, gb = gvals.get(ya), gvals.get(yb)
            if not relevant(a, b, max(ga or 0, gb or 0) or None, metric, code):
                continue
            imp = impact(a, b, ga, gb)
            sev = "high" if imp >= HIGH_IMPACT and abs(b - a) >= MIN_ABS_HIGH[metric] else "medium"
            if a == 0 and b > 0:
                it = add("appeared", sev, key, ya, yb, a, b, ga, gb, f"From nothing in {ya} to {fmt(b, metric)} in {yb}.")
                it["_score"] = imp
                continue
            if b == 0 and a > 0:
                it = add("disappeared", sev, key, ya, yb, a, b, ga, gb, f"From {fmt(a, metric)} in {ya} to nothing in {yb}.")
                it["_score"] = imp
                continue
            ratio = b / a
            if code == "GR":
                if abs(math.log(ratio)) >= math.log(HARD_FACTOR_GREECE):
                    sev = "high" if abs(b - a) >= MIN_ABS_HIGH[metric] else "medium"
                    it = add("hard_change", sev, key, ya, yb, a, b, ga, gb,
                             f"National total {pct(b, a):+.0f}% in one year.")
                    it["_score"] = abs(math.log(ratio))
                continue
            if not (ga and gb):
                continue
            # share of Greece: normally stable for a place and crop; national swings cancel out
            sa, sb = a / ga, b / gb
            ra, rb = ga - a, gb - b                      # rest of Greece (without this place)
            if ra <= 0 or rb <= 0:
                continue                                 # place is all of Greece: nothing to compare
            local = math.log(ratio) - math.log(rb / ra)  # this place vs the rest of Greece
            if abs(sb - sa) < SHARE_MIN_PP / 100 or abs(local) < math.log(SHARE_LOCAL):
                continue
            others = [vals.get(y, 0) / gvals[y] for y in yrs if y != yb and gvals.get(y)]
            usual = ""
            if len(others) >= 2:
                lo, hi = min(others), max(others)
                if lo / SHARE_OUTSIDE <= sb <= hi * SHARE_OUTSIDE:
                    continue                             # within this place's usual range
                usual = f" (other years {lo * 100:.1f}–{hi * 100:.1f}%)"
            elif abs(math.log(ratio)) < math.log(HARD_FACTOR):
                continue                                 # short history: only large moves
            sev = "high" if abs(sb - sa) * 100 >= SHARE_HIGH_PP and abs(b - a) >= MIN_ABS_HIGH[metric] else "medium"
            it = add("share_shift", sev, key, ya, yb, a, b, ga, gb,
                     f"Share of Greece {sa * 100:.1f}% → {sb * 100:.1f}%{usual}. "
                     f"This place {pct(b, a):+.0f}%, rest of Greece {pct(rb, ra):+.0f}%.")
            it["share_from_pct"] = round(sa * 100, 2)
            it["_score"] = abs(sb - sa)

    # 3. yield checks
    for key, yv in series.items():
        ds, cat, item, detail, metric, code = key
        if metric != "yield":
            continue
        area = series.get(key[:4] + ("area", code), {})
        g_area = series.get(key[:4] + ("area", "GR"), {})
        g_yield = series.get(key[:5] + ("GR",), {})
        usual = statistics.median(g_yield.values()) if g_yield else None
        yrs = ds_years[ds]
        for y in yrs:
            if y not in yv or area.get(y, 0) < YIELD_MIN_AREA or not usual:
                continue
            if code != "GR" and area[y] < MIN_SHARE * g_area.get(y, 0):
                continue
            f = yv[y] / usual
            if f >= YIELD_FACTOR or f <= 1 / YIELD_FACTOR:
                others = [v for yy, v in yv.items() if yy != y]
                if len(others) >= 2:
                    own = statistics.median(others)
                    if max(yv[y] / own, own / yv[y]) <= YIELD_OWN_NORMAL:
                        continue                 # always like this here: geography, not an error
                    sev, why = "high", f"and x{yv[y] / own:.1f} this place's own usual {own:,.0f}"
                else:
                    sev, why = "medium", "(only one year here, so it may be normal for this place)"
                it = add("yield_out_of_range", sev, key, None, y, None, yv[y], None, g_yield.get(y),
                         f"Yield {yv[y]:,.0f} kg/stremma is x{f:.1f} the crop's usual {usual:,.0f} in Greece {why}. "
                         f"Check units or a typo in area or production.")
                it["_score"] = (5 if sev == "high" else 0) + abs(math.log(f))
        if code == "GR":
            continue
        for ya, yb in zip(yrs, yrs[1:]):
            a, b = yv.get(ya), yv.get(yb)
            ga, gb = g_yield.get(ya), g_yield.get(yb)
            if not (a and b and ga and gb):
                continue
            if min(area.get(ya, 0), area.get(yb, 0)) < YIELD_MIN_AREA:
                continue
            if area.get(yb, 0) < MIN_SHARE * g_area.get(yb, 0):
                continue
            # yield of the rest of Greece (Greece without this place)
            prod = series.get(key[:4] + ("production", code), {})
            g_prod = series.get(key[:4] + ("production", "GR"), {})
            rest = {}
            for y in (ya, yb):
                ra_, rp_ = g_area.get(y, 0) - area.get(y, 0), g_prod.get(y, 0) - prod.get(y, 0)
                rest[y] = rp_ * 1000 / ra_ if ra_ > 0 and rp_ > 0 else None
            if not (rest[ya] and rest[yb]):
                continue
            local = math.log(b / a) - math.log(rest[yb] / rest[ya])
            if abs(local) < math.log(YIELD_LOCAL):
                continue
            # usual ratio of this place's yield to Greece's, from the other years
            ratios = [yv[y] / g_yield[y] for y in yrs if y != yb and y in yv and g_yield.get(y)]
            if len(ratios) >= 2:
                lo, hi = min(ratios), max(ratios)
                if lo / SHARE_OUTSIDE <= b / gb <= hi * SHARE_OUTSIDE:
                    continue
                usual = f" Usually x{lo:.2f}–x{hi:.2f} Greece's yield, now x{b / gb:.2f}."
            else:
                usual = ""
            share = area.get(yb, 0) / g_area.get(yb, 1)
            it = add("yield_change", "high" if share >= 0.1 else "medium", key, ya, yb, a, b, ga, gb,
                     f"Yield {pct(b, a):+.0f}% while the rest of Greece {pct(rest[yb], rest[ya]):+.0f}%.{usual} "
                     f"Local event, or an error in area/production?")
            it["_score"] = abs(local) * share

    issues = drop_explained_regions(issues, series)
    issues = merge_area_production(issues)
    return sorted(issues, key=lambda i: (i["severity"] != "high", -i["_score"]))


def _event(i: dict, metric: bool = True) -> tuple:
    return (i["kind"], i["dataset"], i["category"], i["item"], i["detail"],
            i["metric"] if metric else "", i["year_from"], i["year"])


def drop_explained_regions(issues: list[dict], series) -> list[dict]:
    """A region flag driven by one of its units (>= 80 % of the change) is dropped;
    the unit's note says it drives the region."""
    by_event = {}
    for i in issues:
        if i["level"] == "unit":
            by_event.setdefault(_event(i) + (i["region_code"].split("-")[0],), []).append(i)
    keep = []
    for i in issues:
        if i["level"] == "region" and i["value_from"] != "" and i["value"] != "":
            units = by_event.get(_event(i) + (i["region_code"],), [])
            d_region = abs(float(i["value"]) - float(i["value_from"]))
            d_units = sum(abs(float(u["value"]) - float(u["value_from"])) for u in units
                          if u["value_from"] != "" and u["value"] != "")
            if units and d_region and d_units >= 0.8 * d_region:
                for u in units:
                    u["note"] += f" Drives most of {i['region']}'s change."
                continue
        keep.append(i)
    return keep


def merge_area_production(issues: list[dict]) -> list[dict]:
    """Same kind, place and years flagged for both area and production -> one line."""
    groups: dict[tuple, list[dict]] = {}
    for i in issues:
        if i["metric"] in ("area", "production"):
            groups.setdefault(_event(i, metric=False) + (i["region_code"],), []).append(i)
    out, done = [], set()
    for i in issues:
        k = _event(i, metric=False) + (i["region_code"],)
        g = groups.get(k)
        if not g or len(g) < 2:
            out.append(i)
            continue
        if k in done:
            continue
        done.add(k)
        area = next(x for x in g if x["metric"] == "area")
        prod = next(x for x in g if x["metric"] == "production")
        m = dict(area)
        m["metric"] = "area+production"
        m["severity"] = "high" if "high" in (area["severity"], prod["severity"]) else "medium"
        pc = f"{prod['change_pct']:+}%" if prod["change_pct"] != "" else "n/a"
        m["note"] = area["note"] + f" Production too: {pc}."
        m["history"] = f"area: {area['history']}  //  production: {prod['history']}"
        m["_score"] = max(area["_score"], prod["_score"])
        out.append(m)
    return out


def relevant(a: float, b: float, greece: float | None, metric: str, code: str) -> bool:
    big = max(a, b)
    if big < MIN_ABS.get(metric, 0):
        return False
    if code == "GR" or not greece:
        return True
    return big >= MIN_SHARE * greece


def impact(a, b, ga, gb) -> float:
    g = max(ga or 0, gb or 0)
    return abs(b - a) / g if g else 0.0

"""Build dashboard/data/regions.geojson (13 Greek regions) from Eurostat GISCO NUTS2.

Source (download once; 03M = 1:3 million gives ~86 KB for Greece, detailed enough for islands):
    https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/NUTS_RG_03M_2021_4326_LEVL_2.geojson
Licence: (c) EuroGeographics for the administrative boundaries - attribution required.

Eurostat uses the current NUTS codes for Greece (EL51, EL52, ...). The project keeps
the older GR codes (GR11, GR12, ...) used in parser/regions.py, so they are mapped here.

Usage:
    python tools/build_geo.py path/to/NUTS_RG_10M_2021_4326_LEVL_2.geojson
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from parser.regions import REGIONS  # noqa: E402

EL_TO_GR = {
    "EL51": "GR11", "EL52": "GR12", "EL53": "GR13", "EL54": "GR21",
    "EL61": "GR14", "EL62": "GR22", "EL63": "GR23", "EL64": "GR24",
    "EL65": "GR25", "EL30": "GR30", "EL41": "GR41", "EL42": "GR42", "EL43": "GR43",
}


def round_coords(obj, nd=4):
    if isinstance(obj, (int, float)):
        return round(obj, nd)
    return [round_coords(x, nd) for x in obj]


def main(src: str) -> None:
    data = json.loads(Path(src).read_text(encoding="utf-8"))
    features = []
    for f in data["features"]:
        nuts = f["properties"].get("NUTS_ID")
        if nuts not in EL_TO_GR:
            continue
        code = EL_TO_GR[nuts]
        geom = f["geometry"]
        features.append({
            "type": "Feature",
            "properties": {"code": code, "name": REGIONS[code].name_en, "nuts2021": nuts},
            "geometry": {"type": geom["type"], "coordinates": round_coords(geom["coordinates"])},
        })
    missing = set(EL_TO_GR) - {f["properties"]["nuts2021"] for f in features}
    if missing:
        sys.exit(f"Regions missing from source file: {sorted(missing)}")
    out = ROOT / "dashboard" / "data" / "regions.geojson"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"type": "FeatureCollection", "features": features},
                              ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {len(features)} regions to {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])

"""Crop-name mapping across years.

ELSTAT sometimes renames a column between years (same crop, new wording). Without a
mapping the series breaks: the dashboard trend stops and the anomaly report flags a
crop that "disappeared" and a new one that "appeared".

Map every old (category, item) to the current name, per dataset folder. The latest
ELSTAT wording is used as the standard. `python -m analysis` lists crop names that are
missing in some years, which is how new renames are found.
"""
from __future__ import annotations

RENAMES: dict[str, dict[tuple[str, str], tuple[str, str]]] = {
    "cereals_for_grain": {
        # 2019-2022 wording -> 2023+ wording
        ("Total Area", "Total Area"): ("Total cultivated areas", "Total cultivated areas"),
        ("Maize", "grown alone"): ("Maize", "without intercropping"),
        ("Maize", "grown with beans and other crops"): ("Maize", "intercropped with beans and other crops"),
    },
}


def canonical(dataset: str, category: str, item: str) -> tuple[str, str]:
    return RENAMES.get(dataset, {}).get((category, item), (category, item))

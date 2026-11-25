"""Which parser class handles a file.

Files live in raw_data/<sector>/<dataset>/<year>/<file>. Each sector has a base
parser (SECTORS); a dataset that differs from its sector's base case gets a
subclass that overrides only the hook that differs, registered in OVERRIDES
under the dataset folder name.

Example (parser/tables/cereals_for_grain.py):

    from ..base import BaseTable

    class CerealsForGrain(BaseTable):
        def item_checks(self, res):
            total = next(c for c in res.columns if c.category == "Total cultivated areas")
            crops = [c for c in res.columns if c.metric == "area" and c is not total]
            return self.check_sum(res, crops, total)
"""
from __future__ import annotations

from pathlib import Path

from ..base import BaseTable
from ..livestock import LivestockTable

SECTORS: dict[str, type[BaseTable]] = {
    "crops": BaseTable,
    "livestock": LivestockTable,
}

OVERRIDES: dict[str, type[BaseTable]] = {
    # "cereals_for_grain": CerealsForGrain,
}


def table_class(path: Path) -> type[BaseTable]:
    """Parser class for raw_data/<sector>/<dataset>/<year>/<file>."""
    path = Path(path)
    dataset, sector = path.parent.parent.name, path.parent.parent.parent.name
    if dataset in OVERRIDES:
        return OVERRIDES[dataset]
    if sector not in SECTORS:
        raise ValueError(f"no parser for sector {sector!r} (known: {', '.join(SECTORS)}); "
                         f"expected raw_data/<sector>/<dataset>/<year>/<file>")
    return SECTORS[sector]

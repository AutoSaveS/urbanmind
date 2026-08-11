"""Assign a coarse Koeppen climate group to every Track B record.

The real Experiment 2 stratifies the 15 evaluation cases by climate context x
pathway (the public reference analogue of the manuscript's city x pathway
grid). City-level overrides take precedence over country defaults; records
from national or multi-region programmes are grouped as "multi_region".

Output: data/trackb/climate_groups.csv (record_id, climate_group)
"""

from __future__ import annotations

import csv

RECORDS = "data/trackb/trackb_records.csv"
OUT = "data/trackb/climate_groups.csv"

# Coarse groups: mediterranean (Cs + adjacent hot B), oceanic (Cfb),
# continental (D), subtropical (Cfa/Cwa), tropical_semiarid (A + hot BSh).
COUNTRY_DEFAULT = {
    "greece": "mediterranean", "italy": "mediterranean", "spain": "mediterranean",
    "portugal": "mediterranean", "israel": "mediterranean", "albania": "mediterranean",
    "turkey": "mediterranean", "lebanon": "mediterranean", "egypt": "mediterranean",
    "saudi arabia": "mediterranean", "north macedonia": "mediterranean",
    "uk": "oceanic", "ireland": "oceanic", "netherlands": "oceanic",
    "belgium": "oceanic", "germany": "oceanic", "france": "oceanic",
    "switzerland": "oceanic", "austria": "oceanic", "new zealand": "oceanic",
    "france/uk": "oceanic",
    "sweden": "continental", "finland": "continental", "canada": "continental",
    "usa": "continental",
    "china": "subtropical", "japan": "subtropical", "south korea": "subtropical",
    "taiwan": "subtropical", "australia": "subtropical",
    "singapore": "tropical_semiarid", "india": "tropical_semiarid",
    "pakistan": "tropical_semiarid", "jamaica": "tropical_semiarid",
    "brazil": "tropical_semiarid", "ethiopia": "tropical_semiarid",
    "mexico": "tropical_semiarid",
    "canada; usa": "oceanic",  # Vancouver; Sacramento -> predominantly west coast
}

# City keyword overrides (substring match, lowercase).
CITY_OVERRIDE = {
    # USA splits
    "phoenix": "mediterranean",         # hot arid; grouped with dry-summer belt
    "los angeles": "mediterranean",
    "covina": "mediterranean",
    "pacoima": "mediterranean",
    "sacramento": "mediterranean",
    "davis": "mediterranean",
    "san francisco": "mediterranean",
    "california": "mediterranean",
    "florida": "subtropical",
    "new york": "subtropical",
    "pacific northwest": "oceanic",
    # China splits
    "beijing": "continental",
    "xi'an": "continental",
    # highland
    "addis ababa": "tropical_semiarid",
    "mexico city": "tropical_semiarid",
    # arid Israel
    "sde boqer": "mediterranean",
}

MULTI_KEYWORDS = ("national", "multiple", "not specified", "cities", "state)",
                  "region)", "tbd", "5 cities", "44 lez", "17 cities", "25 cities")


def group_for(city: str, country: str) -> str:
    c = city.strip().lower()
    for kw, g in CITY_OVERRIDE.items():
        if kw in c:
            return g
    if any(kw in c for kw in MULTI_KEYWORDS) and country.strip().lower() not in (
            "greece", "italy", "spain", "israel", "japan", "china", "taiwan",
            "south korea", "singapore", "india", "australia"):
        # National or unspecified sites in climatically heterogeneous countries
        # (USA, Germany, UK, ...) cannot be assigned a single climate group.
        if country.strip().lower() in ("usa", "germany", "uk", "netherlands",
                                       "sweden", "finland", "switzerland",
                                       "ireland", "canada", "france", "austria",
                                       "belgium", "new zealand"):
            dflt = COUNTRY_DEFAULT.get(country.strip().lower(), "multi_region")
            # Small countries are climatically uniform enough to keep the default.
            if country.strip().lower() in ("usa", "germany", "canada"):
                return "multi_region" if any(k in c for k in ("national", "multiple",
                                                              "state)", "cities")) else dflt
            return dflt
    return COUNTRY_DEFAULT.get(country.strip().lower(), "multi_region")


def main() -> None:
    rows = list(csv.DictReader(open(RECORDS)))
    out = [(r["record_id"], group_for(r["city"], r["country"])) for r in rows]
    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["record_id", "climate_group"])
        w.writerows(out)
    from collections import Counter
    print(Counter(g for _, g in out))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

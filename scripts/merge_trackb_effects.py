"""Merge the per-category effect extraction files into the analysis table.

Joins effects_*.csv (per-record quantitative effect sizes extracted from the
source systematic reviews and primary abstracts) with trackb_records.csv,
climate_groups.csv and trackb_assignment.csv, keeping one row per record per
outcome domain. Rows without a usable numeric value are logged and dropped.

Unit policy (IQR normalization requires unit consistency within a cell):
  thermal_air / thermal_surface -> degC only
  energy                        -> percent only
  air quality (pm25/pm10/no2/nox/bc/ec/o3/pollutant_other) -> percent only

Output: data/trackb/trackb_effects.csv
"""

from __future__ import annotations

import csv
import glob
from collections import defaultdict

DIR = "data/trackb"

AQ_DOMAINS = {"pm25", "pm10", "no2", "nox", "bc", "ec", "o3", "pollutant_other"}
DOMAIN_CLASS = {"thermal_air": "thermal", "thermal_surface": "thermal_surface",
                "energy": "energy", **{d: "air_quality" for d in AQ_DOMAINS}}
UNIT_FOR_CLASS = {"thermal": "degC", "thermal_surface": "degC",
                  "energy": "percent", "air_quality": "percent"}
# Within air quality prefer particulates over NOx-family measurements.
AQ_PREF = {"pm25": 0, "pm10": 1, "bc": 2, "ec": 2, "o3": 3, "no2": 4, "nox": 5,
           "pollutant_other": 6}


def subtype_for(intervention: str, title: str, condition: str) -> str:
    """Study-level intervention subtype from the record title (a documented
    attribute; subtypes differ strongly in effect magnitude, e.g. green roof
    surface cooling vs park air cooling)."""
    t = f"{title} {condition}".lower()
    if intervention == "greening":
        if any(k in t for k in ("green roof", "rooftop", "roof garden", "green-roof")):
            return "green_roof"
        if any(k in t for k in ("facade", "fassade", "green wall", "greened wall",
                                "vertical green")):
            return "facade"
        if any(k in t for k in ("hedge", "barrier", "curbside", "roadside")):
            return "barrier"
        if any(k in t for k in ("street", "avenue", "tree cover", "street tree",
                                "trees in", "canyon")):
            return "street_trees"
        return "park"
    if intervention == "cool_roof":
        if any(k in t for k in ("pavement", "asphalt", "road", "street",
                                "watering", "permeable", "porous", "paving")):
            return "cool_pavement"
        return "cool_roof_coating"
    if intervention == "combined":
        if any(k in t for k in ("watering", "pavement", "sprink")):
            return "watered_pavement"
        return "mixed_measures"
    if intervention == "retrofit":
        return "retrofit_program"
    return "lez_zone"


def main() -> None:
    records = {r["doi"].lower(): r for r in csv.DictReader(open(f"{DIR}/trackb_records.csv"))}
    groups = {r["record_id"]: r["climate_group"]
              for r in csv.DictReader(open(f"{DIR}/climate_groups.csv"))}
    subset = {r["record_id"]: r["subset"]
              for r in csv.DictReader(open(f"{DIR}/trackb_assignment.csv"))}

    raw = []
    for path in sorted(glob.glob(f"{DIR}/effects_*.csv")):
        for r in csv.DictReader(open(path)):
            r["_src_file"] = path.split("/")[-1]
            raw.append(r)
    print(f"read {len(raw)} effect rows from {len(glob.glob(f'{DIR}/effects_*.csv'))} files")

    dropped = defaultdict(int)
    # bucket[(record_id, domain_class)] -> list of candidate rows
    bucket: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in raw:
        doi = r["doi"].strip().lower()
        rec = records.get(doi)
        if rec is None:
            dropped["doi_not_in_library"] += 1
            continue
        dom = r["target_domain"].strip().lower()
        if dom in ("none", ""):
            dropped["no_quantitative_value"] += 1
            continue
        if dom not in DOMAIN_CLASS:
            dropped[f"unknown_domain:{dom}"] += 1
            continue
        cls = DOMAIN_CLASS[dom]
        unit = r["effect_unit"].strip().lower().replace("°c", "degc")
        if unit in ("degc", "deg_c", "c", "k"):
            unit = "degC"
        if unit != UNIT_FOR_CLASS[cls]:
            dropped[f"unit_excluded:{cls}:{unit}"] += 1
            continue
        try:
            val = float(r["effect_value"])
        except (ValueError, TypeError):
            dropped["unparseable_value"] += 1
            continue
        bucket[(rec["record_id"], cls)].append(
            {**r, "_val": val, "_dom": dom, "_cls": cls, "_rec": rec})

    out = []
    for (rid, cls), rows in sorted(bucket.items()):
        # Prefer measured rows; within air quality prefer particulates; average
        # the remaining equally preferred rows (e.g. day and night campaigns).
        measured = [r for r in rows if r["measurement"].strip().lower() == "measured"]
        pool = measured or rows
        if cls == "air_quality":
            best = min(AQ_PREF.get(r["_dom"], 9) for r in pool)
            pool = [r for r in pool if AQ_PREF.get(r["_dom"], 9) == best]
        val = sum(r["_val"] for r in pool) / len(pool)
        rec = pool[0]["_rec"]
        out.append({
            "record_id": rid,
            "doi": rec["doi"],
            "author_year": rec["author_year"],
            "intervention": rec["intervention"],
            "climate_group": groups.get(rid, "multi_region"),
            "subset": subset.get(rid, ""),
            "domain": cls,
            "subtype": subtype_for(rec["intervention"], rec["title"],
                                   pool[0].get("condition", "")),
            "pollutant": pool[0]["_dom"] if cls == "air_quality" else "",
            "effect_value": f"{val:.4g}",
            "unit": UNIT_FOR_CLASS[cls],
            "measurement": pool[0]["measurement"],
            "n_source_rows": len(pool),
            "condition": pool[0].get("condition", ""),
            "source": pool[0].get("source", ""),
        })

    with open(f"{DIR}/trackb_effects.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)

    n_records = len({o["record_id"] for o in out})
    print(f"wrote {len(out)} (record, domain) observations covering "
          f"{n_records} records -> {DIR}/trackb_effects.csv")
    if dropped:
        print("dropped:")
        for k, v in sorted(dropped.items()):
            print(f"  {k}: {v}")
    from collections import Counter
    print("by (intervention, domain):")
    for k, v in sorted(Counter((o['intervention'], o['domain']) for o in out).items()):
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()

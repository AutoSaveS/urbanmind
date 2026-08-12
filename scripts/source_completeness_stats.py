#!/usr/bin/env python3
"""Source-level completeness statistics for the temporal harmonization audit
(R1.3). Every number is a property of the public data source and can be
verified independently of any processing pipeline:

  - NOAA ISD-Lite hourly meteorology: valid-hour share at one reference
    station per city (Central Park 725053-94728, Nanjing Lukou 582380-99999,
    Singapore Changi 486980-99999), 2023;
  - CNEMC hourly PM2.5 (quotsoft.net mirror): valid-hour share per Nanjing
    station, full 2023;
  - NEA Singapore regional PM2.5 (data.gov.sg): hourly completeness per
    region, full 2023;
  - EPA AQS NYC PM2.5: hourly-monitor share via the Observation Count column
    of the daily file (max over duplicate POCs per station-day, capped at 24);
  - satellite upper bounds are arithmetic: MODIS <= 4 overpasses/day = 16.7%
    of hourly slots (before cloud screening); Sentinel-2 5-day revisit = 0.8%.

Inputs are fetched by scripts/fetch_holdout_data.sh plus the ISD-Lite files
downloaded here if missing.
"""

import gzip
import json
import subprocess
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

RAW = Path(__file__).resolve().parents[1] / "data" / "holdout" / "raw"
HOURS = 365 * 24
NANJING = ["1151A", "1152A", "1153A", "1154A", "1155A", "1156A", "1157A",
           "1158A", "1159A", "3422A", "3423A", "3424A", "3425A"]
NYC_COUNTIES = {"005", "047", "061", "081", "085"}
ISD = {"NYC Central Park": "725053-94728", "Nanjing Lukou": "582380-99999",
       "Singapore Changi": "486980-99999"}


def daterange():
    d = date(2023, 1, 1)
    while d <= date(2023, 12, 31):
        yield d
        d += timedelta(days=1)


def nanjing():
    valid = {s: 0 for s in NANJING}
    for d in daterange():
        p = RAW / "cn" / f"china_sites_{d.strftime('%Y%m%d')}.csv"
        if not p.exists() or p.stat().st_size < 1000:
            continue
        day = pd.read_csv(p)
        day = day[day["type"] == "PM2.5"]
        for s in NANJING:
            if s in day.columns:
                valid[s] += pd.to_numeric(day[s], errors="coerce").notna().sum()
    shares = sorted(v / HOURS for v in valid.values())
    print(f"Nanjing CNEMC PM2.5: {len(shares)} stations, valid-hour share "
          f"{100*shares[0]:.1f}-{100*shares[-1]:.1f}% "
          f"(mean {100*sum(shares)/len(shares):.1f}%)")


def singapore():
    regs = {}
    for d in daterange():
        p = RAW / "sg" / f"pm25_{d.strftime('%Y%m%d')}.json"
        if not p.exists():
            continue
        try:
            j = json.loads(p.read_text())
        except json.JSONDecodeError:
            continue
        for item in j.get("items", []):
            for reg in item.get("readings", {}).get("pm25_one_hourly", {}):
                regs[reg] = regs.get(reg, 0) + 1
    shares = sorted(v / HOURS for v in regs.values())
    print(f"Singapore NEA PM2.5: {len(shares)} regions, hourly completeness "
          f"{100*shares[0]:.1f}-{100*shares[-1]:.1f}%")


def nyc():
    with zipfile.ZipFile(RAW / "daily_88101_2023.zip") as z:
        with z.open(z.namelist()[0]) as f:
            df = pd.read_csv(f, dtype={"State Code": str, "County Code": str})
    df = df[(df["State Code"] == "36") & (df["County Code"].isin(NYC_COUNTIES))]
    df["station"] = (df["State Code"] + df["County Code"]
                     + df["Site Num"].astype(str).str.zfill(4))
    n_all = df["station"].nunique()
    hourly = df[df["Sample Duration"].str.contains("1 HOUR", na=False)]
    day = (hourly.groupby(["station", "Date Local"])["Observation Count"]
                 .max().clip(upper=24))
    per = day.groupby("station").sum() / HOURS
    print(f"NYC EPA PM2.5: {len(per)} of {n_all} monitors report hourly, "
          f"valid-hour share {100*per.min():.1f}-{100*per.max():.1f}%; "
          f"remainder are 1-in-3/1-in-6 day filter samplers")


def isd():
    for name, st in ISD.items():
        p = RAW / f"isd_{st}.gz"
        if not p.exists():
            subprocess.run(["curl", "-s", "-o", str(p), "--max-time", "120",
                            f"https://www.ncei.noaa.gov/pub/data/noaa/isd-lite/2023/{st}-2023.gz"],
                           check=True)
        rows = gzip.open(p, "rt").read().splitlines()
        ok = sum(1 for r in rows if r.split()[4] != "-9999")
        print(f"ISD {name}: {100*ok/HOURS:.1f}% valid temperature hours")


def main():
    isd()
    nanjing()
    singapore()
    nyc()
    print(f"\nSatellite upper bounds (arithmetic): MODIS 4/day = "
          f"{100*4/24:.1f}% of hourly slots; Sentinel-2 5-day revisit = "
          f"{100/(5*24):.2f}%")
    print("Building energy: native support monthly (NYC) / sector totals "
          "(Singapore, Nanjing); hourly inputs 100% rule-based by construction")


if __name__ == "__main__":
    main()

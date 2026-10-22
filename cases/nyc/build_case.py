#!/usr/bin/env python3
"""Build the UrbanMind New York City case-input package (Case 1).

Every value in the outputs is either fetched from a documented public endpoint
or derived by a rule written to baseline_provenance.csv.  Fields that could not
be obtained are left empty and listed in SOURCE_STATUS.json as pending.

Usage:
    python3 cases/nyc/build_case.py            # full build (network)
    python3 cases/nyc/build_case.py --no-raster   # skip Sentinel-2 / WorldCover
"""

import argparse
import csv
import json
import math
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import requests
import numpy as np
from pyproj import Transformer
from shapely.geometry import shape, box, LineString
from shapely.ops import transform as shp_transform

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"

# --------------------------------------------------------------------------
# Window definition
# --------------------------------------------------------------------------
CENTRE_LAT, CENTRE_LON = 40.816, -73.902
CELL = 500.0            # parent-cell edge, m
NROW = NCOL = 3         # 3 x 3 parent cells = 1.5 km; the 1.2 km window sits inside
EPSG = 32618            # UTM 18N, the scene CRS of the Sentinel-2 tile

KOPPEN = "Dfa"
CASE_ID = 1
TZ = "America/New_York"   # local day boundary for the CAMS daily mean

FOOTPRINT_COLS = ["osm_id", "building", "levels", "start_date", "height_m",
                  "height_source", "floors", "footprint_m2", "perimeter_m",
                  "facade_m2", "cx_m", "cy_m", "cell_row", "cell_col"]
GRID_COLS = ["cell_row", "cell_col", "lon", "lat", "in_district", "n_buildings",
             "lambda_p", "h_mean_m", "h_area_weighted_m", "road_width_mean_m",
             "h_over_w", "svf", "lcz", "koppen", "footprint_area_m2",
             "facade_area_m2", "height_source_mix"]
ROAD_COLS = ["osm_id", "highway", "width_m", "width_source", "flow_ratio",
             "length_m", "drivable"]
BASELINE_COLS = GRID_COLS + ["delta_fvc_baseline", "albedo_baseline",
                             "wc_tree_frac", "wc_grass_frac", "wc_built_frac",
                             "cell_area_m2", "plantable_area_m2",
                             "tree_count_plantable", "pm25_ugm3", "no2_ugm3",
                             "pm25_source", "lst_day_c", "lst_night_c",
                             "energy_kwh_m2_day", "baseline_status",
                             "scenario_case_id", "main_week"]

MAIN_WEEK = "2023-07-10"
ALL_WEEKS = ["2023-07-10", "2023-01-16", "2023-04-17", "2023-10-09"]

# Road class defaults, same conventions as cases/nanjing (see provenance).
ROAD_WIDTH = {"motorway": 30.0, "motorway_link": 12.0, "trunk": 30.0,
              "trunk_link": 12.0, "primary": 35.0, "primary_link": 12.0,
              "secondary": 25.0, "secondary_link": 12.0, "tertiary": 18.0,
              "tertiary_link": 12.0, "residential": 8.0, "living_street": 8.0,
              "service": 5.0, "unclassified": 8.0, "pedestrian": 5.0,
              "footway": 3.0, "cycleway": 3.0, "path": 3.0, "steps": 3.0,
              "track": 3.0, "busway": 8.0}
FLOW_RATIO = {"motorway": 1.0, "motorway_link": 0.55, "trunk": 1.0,
              "trunk_link": 0.55, "primary": 1.0, "primary_link": 0.55,
              "secondary": 0.5, "secondary_link": 0.35, "tertiary": 0.25,
              "tertiary_link": 0.25, "residential": 0.25,
              "living_street": 0.1, "service": 0.1, "unclassified": 0.1}
DRIVABLE = {"motorway", "motorway_link", "trunk", "trunk_link", "primary",
            "primary_link", "secondary", "secondary_link", "tertiary",
            "tertiary_link", "residential", "living_street", "service",
            "unclassified", "busway"}

# EPA AQS counties inside NYC (state 36): Bronx 005, Kings 047, New York 061,
# Queens 081, Richmond 085.
AQS_COUNTIES = {"36-005", "36-047", "36-061", "36-081", "36-085"}
AQS_SITE_NAME = "IS 52"


def log(msg):
    print(msg, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------
# Grid
# --------------------------------------------------------------------------
def build_grid():
    """3 x 3 parent cells (1.5 km) centred on the AOI and snapped to the lattice.

    The window must be an integer number of cells: offsetting by half a window
    (600 m) from a lattice point pushes the far edge into a fourth column.
    """
    t = Transformer.from_crs(4326, EPSG, always_xy=True)
    cx, cy = t.transform(CENTRE_LON, CENTRE_LAT)
    half = NCOL * CELL / 2.0
    x0 = math.floor((cx - half) / CELL) * CELL
    y0 = math.floor((cy - half) / CELL) * CELL
    return {"x0": x0, "y0": y0, "nrow": NROW, "ncol": NCOL, "epsg": EPSG}, (cx, cy)


def cell_box(row, col, g):
    x = g["x0"] + col * CELL
    y = g["y0"] + (g["nrow"] - 1 - row) * CELL   # row 0 at the north edge
    return box(x, y, x + CELL, y + CELL)


def window_box(g):
    """1.2 km evaluation window, centred on the AOI inside the 1.5 km grid."""
    cx = g["x0"] + g["ncol"] * CELL / 2.0
    cy = g["y0"] + g["nrow"] * CELL / 2.0
    return box(cx - 600.0, cy - 600.0, cx + 600.0, cy + 600.0)


# --------------------------------------------------------------------------
# Footprints
# --------------------------------------------------------------------------
def fetch_footprints(g):
    t = Transformer.from_crs(EPSG, 4326, always_xy=True)
    x1, y1 = g["x0"] + g["ncol"] * CELL, g["y0"] + g["nrow"] * CELL
    lon_min, lat_min = t.transform(g["x0"], g["y0"])
    lon_max, lat_max = t.transform(x1, y1)
    where = (f"within_box(the_geom,{lat_max:.6f},{lon_min:.6f},"
             f"{lat_min:.6f},{lon_max:.6f})")
    base = "https://data.cityofnewyork.us/resource/5zhs-2jue.json"
    rows, off = [], 0
    while True:
        p = {"$select": "bin,construction_year,height_roof,ground_elevation,"
                        "feature_code,shape_area,the_geom",
             "$where": where, "$limit": 1000, "$offset": off}
        for attempt in range(4):
            r = requests.get(base, params=p, timeout=180)
            if r.status_code == 200:
                break
            time.sleep(3 * (attempt + 1))
        r.raise_for_status()
        d = r.json()
        rows += d
        if len(d) < 1000:
            break
        off += 1000
    log(f"  footprints fetched: {len(rows)}")
    (RAW / "footprints_raw.json").write_text(json.dumps(rows))
    return rows


def build_footprints(rows, g):
    """Per-building footprint, height, facade in the UTM lattice."""
    tr = Transformer.from_crs(4326, EPSG, always_xy=True).transform
    records = []
    for r in rows:
        hft = r.get("height_roof")
        if not hft:
            continue
        h = float(hft) * 0.3048
        if h <= 0:
            continue
        try:
            geom = shape(json.loads(r["the_geom"])) if isinstance(r["the_geom"], str) else shape(r["the_geom"])
        except Exception:
            continue
        if geom.is_empty:
            continue
        gu = shp_transform(tr, geom)
        fp = gu.area
        if fp <= 0:
            continue
        per = gu.length
        cy_ = r.get("construction_year")
        try:
            cyv = int(float(cy_)) if cy_ not in (None, "") else 0
        except ValueError:
            cyv = 0
        # PLUTO/NYC convention: every odd-digit BIN starting 1/2/3 belongs to
        # a borough; the footprint file carries a NULL BIN for some structures.
        records.append({
            "osm_id": r.get("bin") or "",
            "building": "",
            "levels": "",
            "start_date": str(cyv) if cyv > 0 else "",
            "height_m": round(h, 2),
            "height_source": "nyc_footprints",
            "footprint_m2": round(fp, 1),
            "perimeter_m": round(per, 1),
            "facade_m2": round(per * h * 0.75, 1),
            "centroid": gu.centroid,
        })
    # assign cells
    # The fetch window is a lon/lat rectangle built from the UTM grid box, so
    # projection curvature lets a few centroids fall just outside the lattice.
    # They are dropped rather than clipped: a footprint with no parent cell
    # would enter none of the per-cell aggregates and would only inflate the
    # building count.
    x1, y1 = g["x0"] + g["ncol"] * CELL, g["y0"] + g["nrow"] * CELL
    kept = []
    for rec in records:
        cx, cy = rec["centroid"].x, rec["centroid"].y
        if not (g["x0"] <= cx < x1 and g["y0"] <= cy < y1):
            continue
        rec["cell_row"] = g["nrow"] - 1 - int((cy - g["y0"]) // CELL)
        rec["cell_col"] = int((cx - g["x0"]) // CELL)
        rec.pop("centroid")
        kept.append(rec)
    dropped = len(records) - len(kept)
    if dropped:
        log(f"  dropped {dropped} footprints outside the {g['ncol']}x{g['nrow']} lattice")
    return kept


# --------------------------------------------------------------------------
# Roads
# --------------------------------------------------------------------------
def fetch_roads(g):
    t = Transformer.from_crs(EPSG, 4326, always_xy=True)
    x1, y1 = g["x0"] + g["ncol"] * CELL, g["y0"] + g["nrow"] * CELL
    lon_min, lat_min = t.transform(g["x0"], g["y0"])
    lon_max, lat_max = t.transform(x1, y1)
    q = (f'[out:json][timeout:120];'
         f'way["highway"]({lat_min:.6f},{lon_min:.6f},{lat_max:.6f},{lon_max:.6f});'
         f'out tags geom;')
    r = requests.post("https://overpass-api.de/api/interpreter",
                      data={"data": q},
                      headers={"User-Agent": "urbanmind-case-builder/1.0 (research)"},
                      timeout=180)
    r.raise_for_status()
    d = r.json()
    (RAW / "roads_overpass.json").write_text(json.dumps(d))
    log(f"  roads fetched: {len(d.get('elements', []))} ways")
    return d.get("elements", [])


def build_roads(elements, g):
    tr = Transformer.from_crs(4326, EPSG, always_xy=True).transform
    gb = box(g["x0"], g["y0"],
             g["x0"] + g["ncol"] * CELL, g["y0"] + g["nrow"] * CELL)
    wb = window_box(g)
    out = []
    for el in elements:
        tags = el.get("tags", {})
        hw = tags.get("highway")
        pts = el.get("geometry") or []
        if not pts or hw is None:
            continue
        line = LineString([(p["lon"], p["lat"]) for p in pts])
        gu = shp_transform(tr, line).intersection(gb)
        if gu.is_empty:
            continue
        if gu.geom_type == "MultiLineString":
            length = sum(part.length for part in gu.geoms)
        else:
            length = gu.length
        if length <= 0:
            continue
        wlen = shp_transform(tr, line).intersection(wb)
        wlen = (sum(p.length for p in wlen.geoms)
                if wlen.geom_type == "MultiLineString" else wlen.length)
        width = None
        wsrc = "class_default"
        wt = tags.get("width")
        if wt:
            try:
                width = float(str(wt).split(";")[0].split()[0])
                wsrc = "osm_width"
            except (ValueError, IndexError):
                width = None
        if width is None:
            width = ROAD_WIDTH.get(hw)
        if width is None:
            continue
        out.append({
            "osm_id": el["id"],
            "highway": hw,
            "width_m": f"{width:g}" if width != int(width) else int(width),
            "width_source": wsrc,
            "flow_ratio": FLOW_RATIO.get(hw, 0.1),
            "length_m": round(length, 1),
            "drivable": 1 if hw in DRIVABLE else 0,
            "_window_m": round(wlen, 1),
            "_mid": (pts[len(pts) // 2]["lon"], pts[len(pts) // 2]["lat"]),
        })
    return out


# --------------------------------------------------------------------------
# Sentinel-2 FVC and albedo
# --------------------------------------------------------------------------
STAC = "https://earth-search.aws.element84.com/v1/search"


def pick_scene(g):
    t = Transformer.from_crs(EPSG, 4326, always_xy=True)
    x1, y1 = g["x0"] + g["ncol"] * CELL, g["y0"] + g["nrow"] * CELL
    lon_min, lat_min = t.transform(g["x0"], g["y0"])
    lon_max, lat_max = t.transform(x1, y1)
    payload = {
        "collections": ["sentinel-2-l2a"],
        "bbox": [lon_min, lat_min, lon_max, lat_max],
        "datetime": "2023-06-01T00:00:00Z/2023-09-15T00:00:00Z",
        "limit": 100,
        "query": {"eo:cloud_cover": {"lt": 15}},
        "sortby": [{"field": "properties.eo:cloud_cover", "direction": "asc"}],
    }
    r = requests.post(STAC, json=payload, timeout=120)
    r.raise_for_status()
    feats = r.json().get("features", [])
    if not feats:
        return None
    item = feats[0]
    (RAW / "stac_search.json").write_text(json.dumps(feats))
    return item


def read_scene_arrays(item, g):
    """Windowed reads, scene CRS.

    Each band is read at its own resolution.  The SCL mask is 20 m while
    blue/red/nir are 10 m, so the mask is read separately at each band's
    resolution (a single 20 m mask would drop or misalign 10 m pixels).
    Returns per band (data, col_off, row_off, transform).
    """
    import rasterio
    from rasterio.windows import from_bounds
    from rasterio.vrt import WarpedVRT
    from rasterio.enums import Resampling

    tr = Transformer.from_crs(EPSG, 32618, always_xy=True)
    x1, y1 = g["x0"] + g["ncol"] * CELL, g["y0"] + g["nrow"] * CELL
    bx0, by0 = tr.transform(g["x0"], g["y0"])
    bx1, by1 = tr.transform(x1, y1)
    bands = ["blue", "red", "nir", "swir16", "swir22"]
    arrs = {}
    keep = np.array([4, 5, 6])
    with rasterio.Env(AWS_NO_SIGN_REQUEST="YES",
                      GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        with rasterio.open(item["assets"]["scl"]["href"]) as scl_src:
            for b in bands:
                a = item["assets"][b]
                with rasterio.open(a["href"]) as w:
                    win = from_bounds(bx0, by0, bx1, by1, w.transform)
                    data = w.read(1, window=win).astype("float32")
                    scale = a["raster:bands"][0].get("scale", 1.0)
                    offset = a["raster:bands"][0].get("offset", 0.0)
                    if scale != 1.0:
                        data = data * scale + offset
                    # SCL at this band's 10 m grid
                    with WarpedVRT(scl_src, crs=w.crs,
                                   transform=w.transform,
                                   width=w.width, height=w.height,
                                   resampling=Resampling.nearest) as vrt:
                        win_s = from_bounds(bx0, by0, bx1, by1, vrt.transform)
                        scl = vrt.read(1, window=win_s)
                mask = ~np.isin(scl, keep)
                data[mask] = np.nan
                arrs[b] = (data, win.col_off, win.row_off, w.transform)
    return arrs


def cell_mean(arr, transform, col_off, row_off, x, y):
    """Mean of valid pixels inside a 500 m cell.

    `transform` is the absolute scene transform, so `from_bounds` returns
    absolute column/row indices; the array was read with a window offset by
    (col_off, row_off), which must be subtracted again.
    """
    from rasterio.windows import from_bounds
    win = from_bounds(x, y, x + CELL, y + CELL, transform)
    c0 = win.col_off - col_off
    r0 = win.row_off - row_off
    c1 = c0 + win.width
    r1 = r0 + win.height
    r0, c0 = max(0, int(round(r0))), max(0, int(round(c0)))
    r1, c1 = min(arr.shape[0], int(round(r1))), min(arr.shape[1], int(round(c1)))
    if r1 <= r0 or c1 <= c0:
        return None
    sub = arr[r0:r1, c0:c1]
    sub = sub[np.isfinite(sub)]
    return float(sub.mean()) if sub.size else None


# --------------------------------------------------------------------------
# WorldCover
# --------------------------------------------------------------------------
WC_TILE = ("https://esa-worldcover.s3.eu-central-1.amazonaws.com/"
           "v200/2021/map/ESA_WorldCover_10m_2021_v200_N39W075_Map.tif")


def worldcover_fractions(g):
    """Tree / grass / built fractions per cell from ESA WorldCover 2021."""
    import rasterio
    from rasterio.windows import from_bounds
    from rasterio.vrt import WarpedVRT
    from rasterio.enums import Resampling

    out = {}
    with rasterio.Env(AWS_NO_SIGN_REQUEST="YES"):
        with rasterio.open(WC_TILE) as src:
            with WarpedVRT(src, crs=f"EPSG:{EPSG}", resampling=Resampling.nearest) as vrt:
                for row in range(g["nrow"]):
                    for col in range(g["ncol"]):
                        x = g["x0"] + col * CELL
                        y = g["y0"] + (g["nrow"] - 1 - row) * CELL
                        win = from_bounds(x, y, x + CELL, y + CELL, vrt.transform)
                        d = vrt.read(1, window=win)
                        n = d.size
                        out[(row, col)] = {
                            "tree": float(((d == 10)).sum() / n),
                            "grass": float(((d == 30) | (d == 20) | (d == 40) | (d == 60)).sum() / n),
                            "built": float(((d == 50)).sum() / n),
                            "crop": float((d == 40).sum() / n),
                        }
    return out


# --------------------------------------------------------------------------
# Air quality
# --------------------------------------------------------------------------
def aqs_station_series(g):
    """Daily mean PM2.5 at the nearest AQS station, for the evaluation weeks."""
    csv_path = HERE / "raw" / "aqs_pm25_nyc.csv"
    if not csv_path.exists():
        return None
    import datetime as dt
    series = defaultdict(list)
    sites = {}
    with open(csv_path, newline="") as fh:
        for r in csv.DictReader(fh):
            if r.get("Parameter Code") != "88101":
                continue
            if r.get("Sample Duration") not in ("1 HOUR", "1 HOURS"):
                continue
            v = r.get("Sample Measurement")
            try:
                val = float(v)
            except (TypeError, ValueError):
                continue
            day = r["Date Local"]
            series[day].append(val)
            if r.get("Site Num"):
                sites[r["Site Num"]] = (r.get("Site Name"), r.get("County Code"))
    if not series:
        return None
    days = {d: sum(v) / len(v) for d, v in series.items()}
    return days, sites, csv_path


def fetch_openmeteo(lat, lon, weeks):
    """CAMS ~11 km model field, hourly -> daily mean for each week's day.

    The day is resolved in the case's local time zone, matching cases/nanjing
    and cases/singapore. Left at the API default the day boundary is UTC, which
    for a site at 74 W shifts the sampling window by five hours and changes the
    daily mean.
    """
    frames = {}
    for w in weeks:
        url = ("https://air-quality-api.open-meteo.com/v1/air-quality"
               f"?latitude={lat:.4f}&longitude={lon:.4f}"
               f"&start_date={w}&end_date={w}&timezone={TZ}"
               "&hourly=pm2_5,nitrogen_dioxide&domains=cams_global")
        r = requests.get(url, timeout=90)
        if r.status_code != 200:
            continue
        d = r.json().get("hourly", {})
        pm = [x for x in d.get("pm2_5", []) if x is not None]
        no2 = [x for x in d.get("nitrogen_dioxide", []) if x is not None]
        frames[w] = {"pm25": float(np.mean(pm)) if pm else None,
                     "no2": float(np.mean(no2)) if no2 else None,
                     "n_hours": len(pm)}
    return frames


# --------------------------------------------------------------------------
# Grid / baseline assembly
# --------------------------------------------------------------------------
def assemble(g, footprints, roads, wc, fvc, alb, aq, aq_meta):
    grid, base = [], []
    h_by_cell = defaultdict(list)
    for f in footprints:
        h_by_cell[(f["cell_row"], f["cell_col"])].append(f)

    # drivable road width per cell, length-weighted (see provenance)
    road_w = defaultdict(list)
    for r in roads:
        if r["drivable"] and r.get("_cell") is not None:
            road_w[r["_cell"]].append((float(r["width_m"]), r["length_m"]))

    t = Transformer.from_crs(EPSG, 4326, always_xy=True)

    for row in range(g["nrow"]):
        for col in range(g["ncol"]):
            bx = cell_box(row, col, g)
            lon, lat = t.transform(bx.centroid.x, bx.centroid.y)
            fs = h_by_cell.get((row, col), [])
            n = len(fs)
            fp_area = sum(f["footprint_m2"] for f in fs)
            fac = sum(f["facade_m2"] for f in fs)
            h_mean = statistics.mean(f["height_m"] for f in fs) if n else None
            h_med = statistics.median(f["height_m"] for f in fs) if n else None
            h_aw = (sum(f["height_m"] * f["footprint_m2"] for f in fs) / fp_area
                    if fp_area else None)
            lam = fp_area / (CELL * CELL)
            widths = road_w.get((row, col), [])
            if widths:
                tw = sum(l for _, l in widths)
                rw = sum(w * l for w, l in widths) / tw
            else:
                rw = None
            hw = (h_aw / rw) if (h_aw and rw) else None
            svf = 1.0 / (1.0 + hw) if hw else None
            srcs = sorted({f["height_source"] for f in fs}) or []
            w = wc.get((row, col), {})
            rec = {
                "cell_row": row, "cell_col": col,
                "lon": round(lon, 6), "lat": round(lat, 6),
                "in_district": 1,
                "n_buildings": n,
                "lambda_p": round(lam, 4),
                "h_mean_m": round(h_mean, 2) if h_mean else "",
                "h_area_weighted_m": round(h_aw, 2) if h_aw else "",
                "road_width_mean_m": round(rw, 1) if rw else "",
                "h_over_w": round(hw, 3) if hw else "",
                "svf": round(svf, 3) if svf else "",
                "lcz": lcz_class(lam, h_aw, h_med),
                "koppen": KOPPEN,
                "footprint_area_m2": round(fp_area, 1),
                "facade_area_m2": round(fac, 1),
                "height_source_mix": ";".join(srcs),
            }
            grid.append(rec)
            b = dict(rec)
            b.update({
                "delta_fvc_baseline": round(fvc[(row, col)], 4) if fvc.get((row, col)) is not None else "",
                "albedo_baseline": round(alb[(row, col)], 4) if alb.get((row, col)) is not None else "",
                "wc_tree_frac": round(w.get("tree", ""), 4) if w else "",
                "wc_grass_frac": round(w.get("grass", ""), 4) if w else "",
                "wc_built_frac": round(w.get("built", ""), 4) if w else "",
                "cell_area_m2": int(CELL * CELL),
                # Same rule as cases/nanjing: half of non-built herbaceous cover
                # is taken as plantable, divided by a 115 m2 mature crown.
                "plantable_area_m2": (round(0.5 * (w.get("grass", 0.0) + w.get("crop", 0.0))
                                            * CELL * CELL) if w else ""),
                "tree_count_plantable": (round(0.5 * (w.get("grass", 0.0) + w.get("crop", 0.0))
                                               * CELL * CELL / 115.0) if w else ""),
                "pm25_ugm3": (round(aq_meta["pm25"], 2)
                              if aq_meta.get("pm25") is not None else ""),
                "no2_ugm3": (round(aq_meta["no2"], 2)
                             if aq_meta.get("no2") is not None else ""),
                "pm25_source": aq_meta.get("label", ""),
                "lst_day_c": "", "lst_night_c": "",
                "energy_kwh_m2_day": "",
                "baseline_status": "geometry_complete;observation_pending",
                "scenario_case_id": CASE_ID,
                "main_week": MAIN_WEEK,
            })
            base.append(b)
    return grid, base


def lcz_class(lam, h_aw, h_med=None):
    """LCZ by Stewart & Oke building-height and built-fraction thresholds.

    The case targets low-rise residential fabric, so only the low-rise ladder
    (LCZ 3 compact / 6 open / 9 sparsely built) is applied; anything that
    fails the height test is flagged rather than relabelled.
    """
    h = h_med if h_med is not None else h_aw
    if h is None:
        return ""
    if h >= 25:
        return 5          # mid-rise, unexpected for this window
    if h >= 10:
        return 3 if lam >= 0.2 else 6
    if lam >= 0.3:
        return 3
    return 6


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-raster", action="store_true",
                    help="skip Sentinel-2 and WorldCover (reuse raw/ outputs)")
    args = ap.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)

    g, (cx, cy) = build_grid()
    log(f"grid origin {g}  AOI UTM ({cx:.1f},{cy:.1f})")

    (HERE / "grid_origin.json").write_text(json.dumps(
        {"x0": g["x0"], "y0": g["y0"], "nrow": g["nrow"], "ncol": g["ncol"],
         "epsg": EPSG}) + "\n")

    # ---- footprints -------------------------------------------------------
    fp_json = RAW / "footprints_raw.json"
    if fp_json.exists():
        rows = json.loads(fp_json.read_text())
        log(f"  footprints from cache: {len(rows)}")
    else:
        rows = fetch_footprints(g)
    footprints = build_footprints(rows, g)

    # ---- roads ------------------------------------------------------------
    rd_json = RAW / "roads_overpass.json"
    if rd_json.exists():
        els = json.loads(rd_json.read_text()).get("elements", [])
    else:
        els = fetch_roads(g)
    roads = build_roads(els, g)
    # cell tag for the width aggregation: midpoint of the way, mapped through
    # the same UTM lattice as the footprints
    to_utm = Transformer.from_crs(4326, EPSG, always_xy=True).transform
    for r in roads:
        x, y = to_utm(*r["_mid"])
        c = int((x - g["x0"]) // CELL)
        rr = g["nrow"] - 1 - int((y - g["y0"]) // CELL)
        r["_cell"] = (rr, c) if (0 <= rr < g["nrow"] and 0 <= c < g["ncol"]) else None

    # ---- rasters ----------------------------------------------------------
    fvc, alb = {}, {}
    scene_id = ""
    if not args.no_raster:
        item = pick_scene(g)
        if item is not None:
            scene_id = item["id"]
            log(f"  scene {scene_id} cloud={item['properties']['eo:cloud_cover']}")
            arrs = read_scene_arrays(item, g)
            for row in range(g["nrow"]):
                for col in range(g["ncol"]):
                    x = g["x0"] + col * CELL
                    y = g["y0"] + (g["nrow"] - 1 - row) * CELL
                    vals = {}
                    for name in ["blue", "red", "nir", "swir16", "swir22"]:
                        a = arrs[name]
                        vals[name] = cell_mean(a[0], a[3], a[1], a[2], x, y)
                    if vals.get("red") is None or vals.get("nir") is None:
                        continue
                    ndvi = (vals["nir"] - vals["red"]) / (vals["nir"] + vals["red"])
                    f = min(max((ndvi - 0.15) / (0.85 - 0.15), 0.0), 1.0)
                    al = (0.356 * vals["blue"] + 0.130 * vals["red"]
                          + 0.373 * vals["nir"] + 0.085 * vals["swir16"]
                          + 0.072 * vals["swir22"] - 0.0018)
                    fvc[(row, col)] = f
                    alb[(row, col)] = al
            np.save(RAW / "fvc.npy", np.array([[fvc.get((r, c), np.nan)
                                                for c in range(g["ncol"])]
                                               for r in range(g["nrow"])]))
            np.save(RAW / "albedo.npy", np.array([[alb.get((r, c), np.nan)
                                                   for c in range(g["ncol"])]
                                                  for r in range(g["nrow"])]))
    else:
        f = RAW / "fvc.npy"
        if f.exists():
            a = np.load(f); b = np.load(RAW / "albedo.npy")
            for r in range(g["nrow"]):
                for c in range(g["ncol"]):
                    if np.isfinite(a[r, c]):
                        fvc[(r, c)] = float(a[r, c])
                        alb[(r, c)] = float(b[r, c])
            scene_id = "cached"

    wc = worldcover_fractions(g) if not args.no_raster else {}
    if args.no_raster and (RAW / "wc.json").exists():
        wc = {tuple(map(int, k.split(","))): v
              for k, v in json.loads((RAW / "wc.json").read_text()).items()}

    # ---- air quality ------------------------------------------------------
    aq = aqs_station_series(g)
    aq_meta = {}
    if aq:
        days, sites, path = aq
        site_id = None
        for sid, (name, cty) in sites.items():
            if name and AQS_SITE_NAME.lower() in name.lower():
                site_id = sid
                break
        if site_id is None and sites:
            site_id = sorted(sites)[0]
        if site_id:
            pm = days.get(MAIN_WEEK)
            if pm is not None:
                aq_meta = {"label": f"EPA AQS station {site_id} daily mean (local)",
                           "pm25": pm}
    if not aq_meta:
        om = fetch_openmeteo(CENTRE_LAT, CENTRE_LON, ALL_WEEKS)
        if MAIN_WEEK in om and om[MAIN_WEEK]["pm25"] is not None:
            aq_meta = {"label": "CAMS ~11 km model field via Open-Meteo (not a station observation)",
                       "pm25": om[MAIN_WEEK]["pm25"],
                       "no2": om[MAIN_WEEK]["no2"]}

    # ---- write ------------------------------------------------------------
    with open(HERE / "footprints.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, FOOTPRINT_COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(footprints)
    with open(HERE / "roads.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, ROAD_COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(roads)
    grid, base = assemble(g, footprints, roads, wc, fvc, alb, aq, aq_meta)
    with open(HERE / "grid_500m.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, GRID_COLS, extrasaction="ignore")
        w.writeheader(); w.writerows(grid)
    with open(HERE / "baseline.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, BASELINE_COLS, extrasaction="ignore")
        w.writeheader(); w.writerows(base)

    for r in roads:
        r.pop("_cell", None)
    stats = report_stats(footprints, roads, grid, fvc, alb)
    log(json.dumps(stats, indent=1))
    return stats


def report_stats(footprints, roads, grid, fvc, alb):
    h = [f["height_m"] for f in footprints]
    cy = [f["start_date"] for f in footprints if f["start_date"]]
    drivable = [r for r in roads if r["drivable"]]
    return {
        "footprints": len(footprints),
        "median_h": statistics.median(h),
        "mean_h": round(statistics.mean(h), 2),
        "cy_coverage": f"{len(cy)}/{len(footprints)}",
        "fp_ha": round(sum(f["footprint_m2"] for f in footprints) / 1e4, 2),
        "roads": len(roads),
        "road_km": round(sum(r["length_m"] for r in roads) / 1e3, 1),
        "drivable_km": round(sum(r["length_m"] for r in drivable) / 1e3, 1),
        "fvc_range": [round(min(fvc.values()), 3), round(max(fvc.values()), 3)] if fvc else None,
        "albedo_range": [round(min(alb.values()), 3), round(max(alb.values()), 3)] if alb else None,
    }


if __name__ == "__main__":
    main()

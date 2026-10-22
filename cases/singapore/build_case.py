#!/usr/bin/env python3
"""Build the UrbanMind Singapore (Toa Payoh) case-input package.

Everything this script needs is public and credential-free:
  HDB footprints      data.gov.sg d_16b157c52ed637edd6ba1232e026258d
  HDB attributes      data.gov.sg d_17f5382f26140b1fdae0ba2ef6239d2f
  other buildings, roads   OSM Overpass (overpass-api.de)
  FVC, albedo         Earth Search STAC, sentinel-2-l2a, unsigned AWS
  land cover          ESA WorldCover 2021 v200 (N00E102)
  air quality         Open-Meteo CAMS (~11 km model field, not an observation)

Usage
  python3 cases/singapore/build_case.py fetch    # download raw inputs (resumable)
  python3 cases/singapore/build_case.py build    # write the case package
  python3 cases/singapore/build_case.py report   # print the summary numbers

Raw inputs land in cases/singapore/raw/ (git-ignored), outputs in cases/singapore/.
Schema and conventions are copied from cases/nanjing/.
"""
import collections
import csv
import hashlib
import json
import math
import os
import pathlib
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
import warnings

import certifi

warnings.filterwarnings("ignore")

HERE = pathlib.Path(__file__).resolve().parent
RAW = HERE / "raw"

# ---------------------------------------------------------------- window
LAT, LON = 1.3356, 103.8481          # Toa Payoh town centre
HALF_M = 650.0                       # half-width of the square window
EPSG = 32648                         # UTM 48N
CELL = 500.0
# 500 m lattice origin. The window is snapped to whole cells so that every
# emitted parent cell carries data; a 1300 m window on an unsnapped lattice
# leaves empty columns at the edge.
X0, Y0 = 369000.0, 147000.0
NROW, NCOL = 3, 3

# window bounds in EPSG:32648, filled in once pyproj is imported below
WX0 = WY0 = WX1 = WY1 = None

MAIN_WEEK = "2023-04-17"
SCENARIO_WEEKS = ["2023-04-17"]

UA = {"User-Agent": "UrbanMind/1.0 (case input build)"}
CTX = ssl.create_default_context(cafile=certifi.where())

DATA_GOV_DATASETS = {
    "hdb_footprints": "d_16b157c52ed637edd6ba1232e026258d",
    "hdb_property": "d_17f5382f26140b1fdae0ba2ef6239d2f",
}

# LTA default carriageway widths, metres (case brief)
WIDTH_DEFAULT = {
    "motorway": 45.5, "motorway_link": 45.5,
    "trunk": 38.6, "trunk_link": 38.6,
    "primary": 38.6, "primary_link": 38.6,
    "secondary": 31.8, "secondary_link": 31.8,
    "tertiary": 26.2, "tertiary_link": 26.2,
    "residential": 18.0, "unclassified": 18.0, "living_street": 18.0,
    "service": 10.0,
}
# relative traffic weighting; no Singapore road-class flow survey is published,
# so these are a declared prior (see baseline_provenance.csv)
FLOW_RATIO = {
    "motorway": 1.0, "motorway_link": 1.0, "trunk": 1.0, "trunk_link": 1.0,
    "primary": 1.0, "primary_link": 1.0, "secondary": 0.5, "secondary_link": 0.5,
    "tertiary": 0.5, "tertiary_link": 0.5, "residential": 0.25,
    "unclassified": 0.25, "living_street": 0.25, "service": 0.1,
}
DRIVABLE = set(WIDTH_DEFAULT)

FLOOR_M = 2.9          # HDB storey height, Singapore HDB design norm


# ---------------------------------------------------------------- helpers
def log(msg):
    print(msg, flush=True)


def http_get(url, tries=4, timeout=300, headers=None):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={**UA, **(headers or {})})
            return urllib.request.urlopen(req, context=CTX, timeout=timeout).read()
        except Exception as e:                          # noqa: BLE001
            last = e
            time.sleep(4 + 4 * i)
    raise last


def http_json(url, tries=4, timeout=180):
    return json.loads(http_get(url, tries=tries, timeout=timeout))


def http_post_json(url, body, tries=4, timeout=180):
    data = json.dumps(body).encode()
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(
                url, data=data, headers={**UA, "Content-Type": "application/json"},
                method="POST")
            return json.load(urllib.request.urlopen(req, context=CTX, timeout=timeout))
        except Exception as e:                          # noqa: BLE001
            last = e
            time.sleep(4 + 4 * i)
    raise last


def download(url, out, min_bytes=1, tries=6):
    """Resumable download. Reuses a partial file via a Range request."""
    out = pathlib.Path(out)
    tmp = out.with_suffix(out.suffix + ".part")
    if out.exists() and out.stat().st_size >= min_bytes:
        log(f"  cached {out.name} ({out.stat().st_size} B)")
        return out
    for attempt in range(tries):
        have = tmp.stat().st_size if tmp.exists() else 0
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            req = urllib.request.Request(url, headers={**UA, **headers})
            with urllib.request.urlopen(req, context=CTX, timeout=900) as r:
                mode = "ab" if (have and r.status == 206) else "wb"
                with open(tmp, mode) as fh:
                    while True:
                        chunk = r.read(1 << 18)
                        if not chunk:
                            break
                        fh.write(chunk)
            if tmp.stat().st_size >= min_bytes:
                os.replace(tmp, out)
                log(f"  {out.name}: {out.stat().st_size} B")
                return out
        except Exception as e:                          # noqa: BLE001
            log(f"  retry {attempt + 1}/{tries} {out.name}: {type(e).__name__}")
            time.sleep(5 + 5 * attempt)
    raise RuntimeError(f"download failed: {out.name}")


def rnd(x, n):
    if x is None or x == "":
        return ""
    if isinstance(x, float) and not math.isfinite(x):
        return ""
    return round(float(x), n)


# ---------------------------------------------------------------- geometry
try:
    from shapely.geometry import Polygon, shape, box
    from shapely.ops import transform as sh_transform
    from pyproj import Transformer
    HAVE_SHAPELY = True
except Exception:                                       # noqa: BLE001
    HAVE_SHAPELY = False

T_FWD = Transformer.from_crs("EPSG:4326", f"EPSG:{EPSG}", always_xy=True)
T_INV = Transformer.from_crs(f"EPSG:{EPSG}", "EPSG:4326", always_xy=True)

_WX, _WY = T_FWD.transform(LON, LAT)
# Snap the window to the 500 m lattice: NROW x NCOL whole cells centred on the AOI.
_HALF_GRID = NCOL * CELL / 2.0
X0 = math.floor((_WX - _HALF_GRID) / CELL) * CELL
Y0 = math.floor((_WY - _HALF_GRID) / CELL) * CELL
HALF_M = _HALF_GRID
WX0, WX1 = X0, X0 + NCOL * CELL
WY0, WY1 = Y0, Y0 + NROW * CELL


def utm(lon, lat):
    return T_FWD.transform(lon, lat)


def geo(lonlat):
    return [(lon, lat) for lon, lat in lonlat]


# ---------------------------------------------------------------- fetch
def fetch():
    RAW.mkdir(parents=True, exist_ok=True)

    log("[1/6] data.gov.sg HDB footprints + property information")
    for name, ds in DATA_GOV_DATASETS.items():
        out = RAW / ("hdb_footprints.geojson" if name == "hdb_footprints" else "hdb_property.csv")
        if out.exists() and out.stat().st_size > 1000:
            log(f"  cached {out.name}")
            continue
        meta = http_json(f"https://api-open.data.gov.sg/v1/public/api/datasets/{ds}/poll-download")
        url = meta["data"]["url"]
        (RAW / f"{name}_url.txt").write_text(url)
        download(url, out, min_bytes=1000)
        time.sleep(4)                                   # data.gov.sg courtesy pause

    log("[2/6] OSM Overpass: buildings + highways")
    out = RAW / "overpass_window.json"
    probe = RAW / "probe_overpass.json"
    if not (out.exists() and out.stat().st_size > 1000) and probe.exists():
        out.write_bytes(probe.read_bytes())
        log("  reusing cached Overpass extract")
    if not (out.exists() and out.stat().st_size > 1000):
        # 200 m pad on each side so footprints clipped by the window edge keep
        # their full outline; final assignment is by centroid.
        pad = 200.0
        xa, ya = utm(LON, LAT)
        lon_a, lat_a = T_INV.transform(xa - HALF_M - pad, ya - HALF_M - pad)
        lon_b, lat_b = T_INV.transform(xa + HALF_M + pad, ya + HALF_M + pad)
        q = (f'[out:json][timeout:300];\n(\n'
             f'  way["building"]({lat_a:.6f},{lon_a:.6f},{lat_b:.6f},{lon_b:.6f});\n'
             f'  way["highway"]({lat_a:.6f},{lon_a:.6f},{lat_b:.6f},{lon_b:.6f});\n'
             f');\nout body geom;')
        data = http_post_json("https://overpass-api.de/api/interpreter",
                              {"data": q}, timeout=600)
        out.write_text(json.dumps(data))
        log(f"  overpass: {len(data['elements'])} elements")
    else:
        log("  cached overpass_window.json")

    log("[3/6] Earth Search: least-cloudy 2023 Sentinel-2 scene")
    bbox = [LON - 0.018, LAT - 0.015, LON + 0.018, LAT + 0.015]
    stac = pathlib.Path(RAW / "stac_s2.json")
    if not stac.exists():
        body = {
            "collections": ["sentinel-2-l2a"], "bbox": bbox, "limit": 100,
            "datetime": "2023-01-01T00:00:00Z/2023-12-31T23:59:59Z",
            "query": {"eo:cloud_cover": {"lt": 30}},
            "sortby": [{"field": "properties.eo:cloud_cover", "direction": "asc"}],
            "fields": {"include": ["id", "properties", "assets"], "exclude": []},
        }
        stac.write_text(json.dumps(http_post_json(
            "https://earth-search.aws.element84.com/v1/search", body)))
    items = json.loads(stac.read_text()).get("features", [])
    items = [f for f in items if f["properties"].get("eo:cloud_cover", 99) < 30]
    items.sort(key=lambda f: f["properties"]["eo:cloud_cover"])
    if not items:
        raise SystemExit("no Sentinel-2 scene under 30% cloud in 2023")
    f = items[0]
    log(f"  {len(items)} candidates, using {f['id']} "
        f"({f['properties']['datetime'][:10]}, cloud {f['properties']['eo:cloud_cover']:.1f}%)")
    return f


# ---------------------------------------------------------------- buildings
def haversine(a, b):
    (lon1, lat1), (lon2, lat2) = a, b
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def way_polygon_utm(geom):
    pts = [utm(p["lon"], p["lat"]) for p in geom]
    if len(pts) < 3:
        return None
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    poly = Polygon(pts)
    if not poly.is_valid:
        poly = poly.buffer(0)
    return poly if (poly.geom_type == "Polygon" and poly.area > 0) else None


def way_length_utm(geom, single_pt=None):
    pts = [utm(p["lon"], p["lat"]) for p in geom]
    if len(pts) < 2:
        return 0.0
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def parse_float(v):
    if v is None:
        return None
    s = str(v).strip().lower().replace("m", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_int(v):
    f = parse_float(v)
    return int(f) if f is not None else None


_ABBREV = [(r"\bLORONG\b", "LOR"), (r"\bJALAN\b", "JLN"), (r"\bAVENUE\b", "AVE"),
           (r"\bSTREET\b", "ST"), (r"\bROAD\b", "RD"), (r"\bCRESCENT\b", "CRES"),
           (r"\bDRIVE\b", "DR"), (r"\bPLACE\b", "PL"), (r"\bCLOSE\b", "CL"),
           (r"\bCENTRAL\b", "CTRL"), (r"\bNORTH\b", "NTH"), (r"\bSOUTH\b", "STH"),
           (r"\bUPPER\b", "UPP"), (r"\bLOWER\b", "LOW"), (r"\bGARDENS?\b", "GDN"),
           (r"\bHEIGHTS?\b", "HTS"), (r"\bTERRACE\b", "TER"), (r"\bLINK\b", "LINK"),
           (r"\bVIEW\b", "VIEW"), (r"\bRISE\b", "RISE"), (r"\bWALK\b", "WALK"),
           (r"\bBOULEVARD\b", "BLVD"), (r"\bMOUNT\b", "MT"), (r"\bSAINT\b", "ST")]


def norm_street(name):
    """Normalise a street name to the HDB property CSV's abbreviated style."""
    s = re.sub(r"[^A-Z0-9 ]", " ", str(name).upper())
    s = re.sub(r"\s+", " ", s).strip()
    for pat, rep in _ABBREV:
        s = re.sub(pat, rep, s)
    return re.sub(r"\s+", " ", s).strip()


def onemap_street(postal, tries=3):
    """Road name for a postal code from OneMap's public address search.

    The HDB property CSV carries no postal code and block numbers repeat across
    towns (every town has a block 147), so blk_no+street cannot be resolved
    from the CSV alone. OneMap returns the statutory road name per postal code.
    """
    u = ("https://www.onemap.gov.sg/api/common/elastic/search?"
         + urllib.parse.urlencode({"searchVal": f"SINGAPORE {postal}",
                                   "returnGeom": "N", "getAddrDetails": "Y",
                                   "pageNum": 1}))
    for i in range(tries):
        try:
            d = http_json(u, timeout=60)
            for r in d.get("results", []):
                if str(r.get("POSTAL", "")) == str(postal):
                    return str(r.get("ROAD_NAME", "")).strip().upper()
            return None
        except Exception:                                # noqa: BLE001
            time.sleep(2 + 2 * i)
    return None


def load_hdb():
    """HDB block polygons inside the window, with OneMap-resolved street."""
    src = RAW / "hdb_footprints_clean.geojson"
    if not src.exists():
        src = RAW / "hdb_footprints.geojson"
    gj = json.loads(src.read_text())
    cache_path = RAW / "onemap_streets.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    out = []
    for feat in gj.get("features", []):
        p = feat.get("properties", {})
        blk = str(p.get("BLK_NO", "")).strip()
        postal = str(p.get("POSTAL_COD") or "").strip()
        if not blk:
            continue
        poly = shape(feat["geometry"])
        poly_u = shape(sh_transform(T_FWD.transform, poly))
        if poly_u.is_empty or poly_u.area <= 0:
            continue
        cx, cy = poly_u.centroid.x, poly_u.centroid.y
        # one cell of slack around the window: enough to drop OSM duplicates
        # that straddle the boundary, without pulling in the whole estate
        if not (WX0 - CELL <= cx < WX1 + CELL and WY0 - CELL <= cy < WY1 + CELL):
            continue
        out.append({"blk": blk, "street": "pending", "postal": postal,
                    "poly": poly, "poly_u": poly_u})
    log(f"  HDB footprints in window+halo: {len(out)}")

    missing = sorted({h["postal"] for h in out
                      if h["postal"] and h["postal"] not in cache})
    if missing:
        log(f"  OneMap lookups: {len(missing)}")
        for i, pc in enumerate(missing):
            cache[pc] = onemap_street(pc)
            if i % 10 == 9:
                cache_path.write_text(json.dumps(cache, indent=1))
            time.sleep(0.4)
        cache_path.write_text(json.dumps(cache, indent=1))
    for h in out:
        raw = cache.get(h["postal"]) or ""
        h["street"] = norm_street(raw) if raw else ""
        h["street_raw"] = raw
    return out


def load_hdb_property():
    path = RAW / "hdb_property.csv"
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    log(f"  HDB property rows: {len(rows)} (fields {list(rows[0])[:9]})")
    idx = {}
    for r in rows:
        key = (str(r.get("blk_no", "")).strip(), norm_street(r.get("street", "")))
        idx.setdefault(key, r)
    # fuzzy street fallback: same block number, unique street in property table
    by_blk = collections.defaultdict(list)
    for (b, s), r in idx.items():
        by_blk[b].append((s, r))
    return idx, by_blk


def build_buildings(hdb, prop_idx, prop_by_blk, osm_elems):
    """Merge HDB blocks (authoritative floors) with OSM buildings.

    OSM ways whose centroid falls inside an HDB block are dropped (double
    count); HDB geometry is kept because the statutory floor count joins to it.
    """
    # --- HDB side
    hdb_recs = []
    matched = 0
    for h in hdb:
        poly_u = h["poly_u"]
        cx, cy = poly_u.centroid.x, poly_u.centroid.y
        r = prop_idx.get((h["blk"], h["street"].upper()))
        if r is None:
            cands = prop_by_blk.get(h["blk"], [])
            if len({s for s, _ in cands}) == 1:
                r = cands[0][1]
        rec = {
            "osm_id": f"hdb:{h['blk']}:{h['postal'] or ''}",
            "building": "apartments",
            "levels": "", "start_date": "",
            "height_m": "", "height_source": "pending_hdb_attr",
            "floors": "", "footprint_m2": poly_u.area,
            "perimeter_m": poly_u.length,
            "cx_m": cx, "cy_m": cy,
            "street": h["street"], "postal": h["postal"],
        }
        if r:
            matched += 1
            lv = parse_int(r.get("max_floor_lvl"))
            rec["start_date"] = str(r.get("year_completed") or "").strip()
            if lv:
                rec["floors"] = float(lv)
                rec["levels"] = lv
                rec["height_m"] = lv * FLOOR_M
                rec["height_source"] = "hdb_floors"
            rec["dwelling_units"] = str(r.get("total_dwelling_units") or "").strip()
        hdb_recs.append(rec)

    # --- OSM side
    osm_polys = []
    for e in osm_elems:
        tags = e.get("tags", {})
        if "building" not in tags or "geometry" not in e:
            continue
        poly_u = way_polygon_utm(e["geometry"])
        if poly_u is None:
            continue
        cx, cy = poly_u.centroid.x, poly_u.centroid.y
        if not (WX0 <= cx < WX1 and WY0 <= cy < WY1):
            continue
        osm_polys.append((e, poly_u, cx, cy))

    hdb_union = None
    if hdb_recs:
        from shapely.ops import unary_union
        hdb_polys = [h["poly_u"] for h in hdb]
        hdb_union = unary_union(hdb_polys)

    dropped = 0
    osm_recs = []
    for e, poly_u, cx, cy in osm_polys:
        tags = e["tags"]
        if hdb_union is not None:
            from shapely.geometry import Point
            if hdb_union.contains(Point(cx, cy)):
                dropped += 1
                continue
        h = parse_float(tags.get("height"))
        lv = parse_float(tags.get("building:levels"))
        rec = {
            "osm_id": str(e["id"]),
            "building": tags.get("building", "yes"),
            "levels": int(lv) if lv else "",
            "start_date": str(tags.get("start_date", "")).strip(),
            "height_m": "", "height_source": "", "floors": "",
            "footprint_m2": poly_u.area, "perimeter_m": poly_u.length,
            "cx_m": cx, "cy_m": cy,
        }
        if h:
            rec.update(height_m=h, height_source="osm_height", floors=round(h / FLOOR_M, 2))
        elif lv:
            rec.update(height_m=round(lv * FLOOR_M, 1), height_source="osm_levels", floors=lv)
        else:
            rec["height_source"] = "pending"
        osm_recs.append(rec)

    log(f"  HDB blocks in window: {len(hdb_recs)} ({matched} joined to property table)")
    log(f"  OSM buildings in window: {len(osm_polys)} "
        f"({dropped} dropped as HDB duplicates, {len(osm_recs)} kept)")
    return hdb_recs, osm_recs


# ---------------------------------------------------------------- raster
def raster_products(scene):
    """FVC, albedo and WorldCover fractions per 500 m cell."""
    import numpy as np
    import rasterio
    from rasterio.windows import from_bounds
    from rasterio.warp import reproject, Resampling

    xa, ya = utm(LON, LAT)
    wx0, wy0 = xa - HALF_M, ya - HALF_M
    wx1, wy1 = xa + HALF_M, ya + HALF_M

    def window_for(src, pad=60.0):
        tr = Transformer.from_crs(f"EPSG:{EPSG}", src.crs.to_string(), always_xy=True)
        xs, ys = [], []
        for x, y in [(wx0 - pad, wy0 - pad), (wx1 + pad, wy0 - pad),
                     (wx0 - pad, wy1 + pad), (wx1 + pad, wy1 + pad)]:
            u, v = tr.transform(x, y)
            xs.append(u); ys.append(v)
        return from_bounds(min(xs), min(ys), max(xs), max(ys), src.transform)

    def read(name, band_index=1):
        with rasterio.Env(AWS_NO_SIGN_REQUEST="YES"):
            with rasterio.open(scene["assets"][name]["href"]) as src:
                w = window_for(src)
                a = src.read(band_index, window=w).astype("float32")
                if src.nodata is not None and name != "scl":
                    a = np.where(a == src.nodata, np.nan, a)
                return a, src.transform, w, src.crs

    red, tf, w, crs = read("red")
    ref = (tf, red.shape)
    bands = {"red": red / 10000.0}
    for b in ("blue", "green", "nir", "swir16", "swir22", "scl"):
        a, _, _, _ = read(b)
        if a.shape != ref[1]:
            out = np.full(ref[1], np.nan, "float32")
            reproject(a, out, src_transform=tf, src_crs=crs,
                      dst_transform=tf, dst_crs=crs, resampling=Resampling.nearest)
            a = out
        bands[b] = a if b == "scl" else a / 10000.0
    scl = np.nan_to_num(bands.pop("scl"), nan=0).astype(int)
    clear = np.isin(scl, [4, 5, 6])
    ndvi = (bands["nir"] - bands["red"]) / np.where(
        (bands["nir"] + bands["red"]) == 0, np.nan, bands["nir"] + bands["red"])
    fvc = np.clip((ndvi - 0.15) / (0.85 - 0.15), 0, 1)
    alb = (0.356 * bands["blue"] + 0.130 * bands["red"] + 0.373 * bands["nir"]
           + 0.085 * bands["swir16"] + 0.072 * bands["swir22"] - 0.0018)
    alb = np.clip(alb, 0, 1)
    fvc = np.where(clear, fvc, np.nan)
    alb = np.where(clear & np.isfinite(alb) & (alb > 0), alb, np.nan)
    log(f"  S2 window {red.shape}, clear fraction {clear.mean():.2f}, "
        f"FVC mean {np.nanmean(fvc):.3f}, albedo mean {np.nanmean(alb):.3f}")

    wc_url = ("https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
              "ESA_WorldCover_10m_2021_v200_N00E102_Map.tif")
    with rasterio.open(wc_url) as src:
        ww = window_for(src)
        wc = src.read(1, window=ww)
        wtf, wcrs = src.transform, src.crs

    def cell_mean(a, tf_, w_, x0, y0):
        c0, r0 = ~tf_ * (x0, y0)
        c1, r1 = ~tf_ * (x0 + CELL, y0 + CELL)
        rr0 = int(math.floor(min(r0, r1) - w_.row_off)); rr1 = int(math.ceil(max(r0, r1) - w_.row_off))
        cc0 = int(math.floor(min(c0, c1) - w_.col_off)); cc1 = int(math.ceil(max(c0, c1) - w_.col_off))
        rr0, cc0 = max(0, rr0), max(0, cc0)
        rr1 = min(a.shape[0], max(rr0 + 1, rr1)); cc1 = min(a.shape[1], max(cc0 + 1, cc1))
        blk = a[rr0:rr1, cc0:cc1]
        if blk.size == 0 or not np.isfinite(blk).any():
            return float("nan"), 0.0
        return float(np.nanmean(blk)), float(np.isfinite(blk).mean())

    def wc_frac(x0, y0):
        lon0, lat0 = T_INV.transform(x0, y0)
        lon1, lat1 = T_INV.transform(x0 + CELL, y0 + CELL)
        c0, r0 = ~wtf * (lon0, lat0)
        c1, r1 = ~wtf * (lon1, lat1)
        rr0 = max(0, int(round(min(r0, r1) - ww.row_off)))
        rr1 = min(wc.shape[0], max(rr0 + 1, int(round(max(r0, r1) - ww.row_off))))
        cc0 = max(0, int(round(min(c0, c1) - ww.col_off)))
        cc1 = min(wc.shape[1], max(cc0 + 1, int(round(max(c0, c1) - ww.col_off))))
        blk = wc[rr0:rr1, cc0:cc1]
        if blk.size == 0:
            return {}
        vals, cnt = np.unique(blk, return_counts=True)
        return {int(v): float(c / cnt.sum()) for v, c in zip(vals, cnt)}

    cells = {}
    for r in range(NROW):
        for c in range(NCOL):
            x0, y0 = X0 + c * CELL, Y0 + r * CELL
            fv, fv_cover = cell_mean(fvc, tf, w, x0, y0)
            al, _ = cell_mean(alb, tf, w, x0, y0)
            cells[(r, c)] = {
                "delta_fvc_baseline": round(fv, 4) if math.isfinite(fv) else "",
                "albedo_baseline": round(al, 4) if math.isfinite(al) else "",
                "s2_valid_frac": round(fv_cover, 3),
                "wc": wc_frac(x0, y0),
            }
    return cells, items_meta(scene)


def items_meta(scene):
    return {"scene_id": scene["id"],
            "scene_date": scene["properties"]["datetime"][:10],
            "scene_cloud_pct": round(scene["properties"]["eo:cloud_cover"], 2)}


# ---------------------------------------------------------------- cells
def assign_cell(cx, cy):
    col = int(math.floor((cx - X0) / CELL))
    row = int(math.floor((cy - Y0) / CELL))
    if 0 <= row < NROW and 0 <= col < NCOL:
        return row, col
    return None


def build_grid(buildings, roads, cells):
    """Per-cell morphology, Nanjing column order."""
    from collections import defaultdict
    by = defaultdict(list)
    for b in buildings:
        rc = assign_cell(b["cx_m"], b["cy_m"])
        if rc:
            by[rc].append(b)
    road_w = defaultdict(list)
    for rd in roads:
        mx, my = rd["_mid"]
        rc = assign_cell(mx, my)
        if rc and rd["drivable"]:
            road_w[rc].append(rd["width_m"])

    rows = []
    for r in range(NROW):
        for c in range(NCOL):
            bl = by.get((r, c), [])
            x0, y0 = X0 + c * CELL, Y0 + r * CELL
            lon, lat = T_INV.transform(x0 + CELL / 2, y0 + CELL / 2)
            hs = [b["height_m"] for b in bl if b["height_m"] != ""]
            areas = [b["footprint_m2"] for b in bl]
            farea = sum(areas)
            area_h = sum(b["footprint_m2"] * b["height_m"] for b in bl if b["height_m"] != "")
            h_mean = sum(hs) / len(hs) if hs else ""
            h_aw = area_h / sum(b["footprint_m2"] for b in bl if b["height_m"] != "") \
                if hs else ""
            widths = road_w.get((r, c), [])
            w_mean = sum(widths) / len(widths) if widths else ""
            hw = (h_aw / w_mean) if (h_aw != "" and w_mean != "") else ""
            svf = round(1 / (1 + round(hw, 3)), 3) if hw != "" else ""
            facade = sum(b["perimeter_m"] * b["height_m"] * 0.75
                         for b in bl if b["height_m"] != "")
            mixes = sorted({b["height_source"] for b in bl if b["height_source"]})
            cell = cells.get((r, c), {})
            wc = cell.get("wc", {})
            grass = wc.get(30, 0.0) + wc.get(20, 0.0)
            tree = wc.get(95, 0.0) + wc.get(10, 0.0)
            plantable = round(grass * 0.5 * CELL * CELL)
            rows.append({
                "cell_row": r, "cell_col": c,
                "lon": round(lon, 6), "lat": round(lat, 6),
                "in_district": 1,
                "n_buildings": len(bl),
                "lambda_p": round(farea / (CELL * CELL), 4),
                "h_mean_m": rnd(h_mean, 2),
                "h_area_weighted_m": rnd(h_aw, 2),
                "road_width_mean_m": rnd(w_mean, 1),
                "h_over_w": rnd(hw, 3),
                "svf": svf,
                "lcz": 4,
                "koppen": "Af",
                "footprint_area_m2": round(farea, 1),
                "facade_area_m2": round(facade, 1),
                "height_source_mix": ";".join(mixes),
                "delta_fvc_baseline": cell.get("delta_fvc_baseline", ""),
                "albedo_baseline": cell.get("albedo_baseline", ""),
                "lst_day_c": "", "lst_night_c": "",
                "pm25_ugm3": "", "no2_ugm3": "",
                "energy_kwh_m2_day": "",
                "tree_count_plantable": round(plantable / 115.0),
                "building_year": "",
                "baseline_status": "geometry_complete;observation_complete;lst_pending;energy_pending",
                "scenario_case_id": 2, "main_week": MAIN_WEEK,
                # extras (appended after the Nanjing columns)
                "plantable_area_m2": plantable,
                "wc_tree_frac": round(tree, 4),
                "wc_grass_frac": round(grass, 4),
                "wc_built_frac": round(wc.get(50, 0.0), 4),
                "wc_crop_frac": round(wc.get(40, 0.0), 4),
                "s2_valid_frac": cell.get("s2_valid_frac", ""),
            })
    return rows


# ---------------------------------------------------------------- main build
def build():
    log("[build] reading raw inputs")
    hdb = load_hdb()
    prop_idx, prop_by_blk = load_hdb_property()
    osm = json.loads((RAW / "overpass_window.json").read_text())["elements"]

    hdb_recs, osm_recs = build_buildings(hdb, prop_idx, prop_by_blk, osm)
    buildings = hdb_recs + osm_recs

    # --- footprints.csv
    fp_cols = ["osm_id", "building", "levels", "start_date", "height_m", "height_source",
               "floors", "footprint_m2", "perimeter_m", "facade_m2", "cx_m", "cy_m",
               "cell_row", "cell_col"]
    out_rows = []
    for b in buildings:
        rc = assign_cell(b["cx_m"], b["cy_m"])
        if not rc:
            continue
        row = {k: b.get(k, "") for k in fp_cols}
        row["footprint_m2"] = round(b["footprint_m2"], 1)
        row["perimeter_m"] = round(b["perimeter_m"], 1)
        row["facade_m2"] = (round(b["perimeter_m"] * b["height_m"] * 0.75, 1)
                            if b["height_m"] != "" else "")
        row["cx_m"] = round(b["cx_m"], 1)
        row["cy_m"] = round(b["cy_m"], 1)
        row["cell_row"], row["cell_col"] = rc
        out_rows.append(row)
    out_rows.sort(key=lambda x: (x["cell_row"], x["cell_col"], x["osm_id"]))
    write_csv(HERE / "footprints.csv", fp_cols, out_rows)
    log(f"  footprints.csv: {len(out_rows)}")

    # --- roads.csv
    rd_rows = []
    for e in osm:
        tags = e.get("tags", {})
        hw = tags.get("highway")
        if not hw or "geometry" not in e:
            continue
        pts = [utm(p["lon"], p["lat"]) for p in e["geometry"]]
        if len(pts) < 2:
            continue
        length = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
        mid = pts[len(pts) // 2]
        # keep centre lines that enter the window, with one cell of slack
        if not (WX0 - CELL <= mid[0] < WX1 + CELL and
                WY0 - CELL <= mid[1] < WY1 + CELL):
            continue
        wd = tags.get("width")
        lanes = tags.get("lanes")
        w_m, ws = None, ""
        w_parsed = parse_float(wd)
        if w_parsed:
            w_m = w_parsed * (0.3048 if wd.strip().lower().endswith("ft") else 1.0)
            ws = "osm_width"
        elif parse_int(lanes):
            w_m = parse_int(lanes) * 3.5
            ws = "osm_lanes"
        elif hw in WIDTH_DEFAULT:
            w_m = WIDTH_DEFAULT[hw]
            ws = "lta_default"
        else:
            w_m = 0.0
            ws = "pending"
        rd_rows.append({
            "osm_id": str(e["id"]), "highway": hw,
            "width_m": round(w_m, 1), "width_source": ws,
            "flow_ratio": FLOW_RATIO.get(hw, 0.0),
            "length_m": round(length, 1),
            "drivable": 1 if (hw in DRIVABLE and w_m > 0) else 0,
            "_mid": mid,
        })
    rc_cols = ["osm_id", "highway", "width_m", "width_source", "flow_ratio", "length_m", "drivable"]
    write_csv(HERE / "roads.csv", rc_cols, [{k: r[k] for k in rc_cols} for r in rd_rows])
    log(f"  roads.csv: {len(rd_rows)}")

    # --- rasters
    log("[build] raster products")
    scene = pick_scene()
    cells, meta = raster_products(scene)

    # --- grids
    log("[build] grid")
    grid = build_grid(buildings, rd_rows, cells)
    gcols = ["cell_row", "cell_col", "lon", "lat", "in_district", "n_buildings", "lambda_p",
             "h_mean_m", "h_area_weighted_m", "road_width_mean_m", "h_over_w", "svf",
             "lcz", "koppen", "footprint_area_m2", "facade_area_m2", "height_source_mix"]
    write_csv(HERE / "grid_500m.csv", gcols, [{k: g[k] for k in gcols} for g in grid])
    log(f"  grid_500m.csv: {len(grid)}")

    bcols = gcols + ["delta_fvc_baseline", "albedo_baseline", "lst_day_c", "lst_night_c",
                     "pm25_ugm3", "no2_ugm3", "energy_kwh_m2_day", "tree_count_plantable",
                     "building_year", "baseline_status", "scenario_case_id", "main_week",
                     "plantable_area_m2", "wc_tree_frac", "wc_grass_frac", "wc_built_frac",
                     "wc_crop_frac", "s2_valid_frac"]
    write_csv(HERE / "baseline.csv", bcols, [{k: g[k] for k in bcols} for g in grid])
    write_csv(HERE / "baseline_provenance.csv", ["field", "rule", "status", "source"],
              [dict(zip(["field", "rule", "status", "source"], r))
               for r in provenance_rows(meta)])
    log(f"  baseline.csv: {len(grid)}")

    write_json(HERE / "grid_origin.json",
               {"x0": X0, "y0": Y0, "nrow": NROW, "ncol": NCOL, "epsg": EPSG})
    write_scenario(meta, grid)

    # --- air quality (CAMS model field)
    log("[build] air quality (CAMS ~11 km field)")
    aq = cams(LAT, LON, MAIN_WEEK)
    log(f"  PM2.5 {aq['pm25_ugm3']} ug/m3, NO2 {aq['no2_ugm3']} ug/m3 (model field)")

    # --- provenance / status
    write_source_status(meta, aq, grid, buildings)
    summary(meta, aq, grid)


def pick_scene():
    items = json.loads((RAW / "stac_s2.json").read_text()).get("features", [])
    items = [f for f in items if f["properties"].get("eo:cloud_cover", 99) < 30]
    items.sort(key=lambda f: f["properties"]["eo:cloud_cover"])
    return items[0]


def cams(lat, lon, day):
    q = urllib.parse.urlencode({
        "latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}",
        "hourly": "pm2_5,nitrogen_dioxide",
        "start_date": day, "end_date": day, "timezone": "Asia/Singapore"})
    r = http_json("https://air-quality-api.open-meteo.com/v1/air-quality?" + q)
    pm = [v for v in r["hourly"]["pm2_5"] if v is not None]
    no2 = [v for v in r["hourly"]["nitrogen_dioxide"] if v is not None]
    return {"pm25_ugm3": round(sum(pm) / len(pm), 2) if pm else "",
            "no2_ugm3": round(sum(no2) / len(no2), 2) if no2 else ""}


def provenance_rows(meta):
    return [
        ("delta_fvc_baseline",
         f"Sentinel-2 L2A {meta['scene_id']} ({meta['scene_date']}, cloud {meta['scene_cloud_pct']}%), "
         "SCL 4/5/6 mask, NDVI -> clip((NDVI-0.15)/0.70,0,1), mean of 10 m pixels in cell",
         "derived", "Earth Search STAC sentinel-2-l2a"),
        ("albedo_baseline",
         "Liang (2001) broadband albedo 0.356*B02+0.130*B04+0.373*B08+0.085*B11+0.072*B12-0.0018, "
         "SCL-masked, mean of 10 m pixels in cell",
         "derived", "Earth Search STAC sentinel-2-l2a"),
        ("lst_day_c", "MODIS MOD11A1 daytime, 1 km -> 500 m", "pending",
         "LP DAAC (needs Earthdata credentials; no credential-free endpoint in scope)"),
        ("lst_night_c", "MODIS MYD11A1 nighttime, 1 km -> 500 m", "pending",
         "LP DAAC (needs Earthdata credentials)"),
        ("pm25_ugm3",
         "CAMS global atmospheric composition ~11 km model field, 24 h mean at window centre "
         "for the main week; NOT a station observation",
         "derived", "Open-Meteo air-quality API (CAMS)"),
        ("no2_ugm3", "CAMS ~11 km model field, 24 h mean at window centre", "derived",
         "Open-Meteo air-quality API (CAMS)"),
        ("energy_kwh_m2_day",
         "No credential-free building-energy dataset for Singapore; would need EMA/MSD "
         "sector totals x LCZ 4 typical EUI",
         "pending", "EMA Singapore Energy Statistics / BCA"),
        ("tree_count_plantable",
         "plantable = 0.5 x (WorldCover 30 grass + 20 shrub/bare) x cell area, minus existing "
         "tree cover (10/95) not applied; divided by 115 m2 mean crown area",
         "derived", "ESA WorldCover 2021 v200 + crown-area literature"),
        ("building_year",
         "HDB year_completed (authoritative); non-HDB OSM start_date where tagged",
         "derived", "data.gov.sg d_17f5382f26140b1fdae0ba2ef6239d2f; OSM start_date"),
        ("hdb_floors",
         "max_floor_lvl from HDB Property Information; height_m = floors x 2.9 m",
         "derived", "data.gov.sg d_17f5382f26140b1fdae0ba2ef6239d2f"),
        ("road_width_flow",
         "LTA class defaults for width; flow_ratio is a declared class prior",
         "derived", "case brief / LTA default widths; no Singapore flow survey"),
        ("svf", "svf = 1/(1 + H/W) with H = area-weighted mean building height, "
                "W = mean drivable carriageway width in the cell",
         "derived", "footprints.csv + roads.csv"),
        ("lambda_p", "footprint area / 250000 m2", "derived", "footprints.csv"),
        ("lcz", "LCZ 4 (open high-rise) inferred from HDB slab floor distribution", "derived",
         "footprints.csv floor distribution"),
    ]


def write_scenario(meta, grid):
    doc = f"""case_id: 2
site: Toa Payoh, Singapore
country: Singapore
admin_unit: Toa Payoh (HDB new town, 12 planning sub-zones)
centre:
  lat: {LAT}
  lon: {LON}
koppen: Af
lcz: 4
intervention: height redistribution with street-tree canopy increase
intervention_type: compound
active_components:
- height_redistribution
- delta_fvc
scenario_vector:
  delta_fvc: 0.04
  delta_albedo_roof: 0.0
  delta_r_wall: 0.0
  delta_s_emit: 0.0
height_redistribution:
  conservation: gross_floor_area
  max_height_m: 60.0
  min_height_m: 12.0
edit_script_grid:
  delta_fvc:
  - 0.0
  - 0.02
  - 0.04
  height_shift_m:
  - -15
  - -8
  - 0
  - 8
  - 15
evaluation_weeks:
  main: '{MAIN_WEEK}'
  all:
  - '{MAIN_WEEK}'
runtime_geometry: true
subgraph:
  adjacency_L: 2
  wind_reachable: true
  halo: true
  parent_cells: {len(grid)}
  parent_cells_in_window: {len(grid)}
  parent_cells_in_district: {len(grid)}
  scope: window parent cells
modified_nodes: all building cells in the {int(2 * HALF_M)} m window
week_selection:
  exclude_daily_pm25_gt: null
  modis_min_clear_days: null
  no_missing_wind: true
emission_edge_extent:
  classes: []
  length_km: 0.0
  scaling: none; delta_s_emit is zero in this case
reencode_scope: window parent cells with canopy or height change
retrofit_scope:
  construction_year_max: null
  rule: not applicable; delta_r_wall is zero in this case
  facade_area_rule: perimeter x height x 0.75
cost_basis: not applicable; no retrofit or low-emission-zone spend in this case
cost_reference: not applicable; no intervention cost is claimed without a Singapore price reference
bci:
  ref:
    T_surf_c: 2.5
    pm25_ugm3: 10
    energy_pct: 20
    coverage_pp: 8
  T_weight_main_week: 0.0
  weights: equal
  T_sensitivity: 0.4
  form: max(B,0)/(max(B,0)+c)
  clip: aggregate only
  cost: one-off, undiscounted
energy_output:
  primary: total_percent
  secondary:
  - cooling_percent
  - heating_percent
window_candidates:
- 'Toa Payoh: Lorong 1/2 slab-block estate'
- 'Toa Payoh: Lorong 4-6 slab-block estate'
window:
  centre_lat: {LAT}
  centre_lon: {LON}
  half_width_m: {int(HALF_M)}
  grid_origin_epsg: {EPSG}
  parent_cells: {NROW} x {NCOL}
data_gaps:
- LST (MODIS) needs Earthdata credentials
- energy baseline (EMA/BCA sector totals x LCZ EUI)
- OSM building heights for untagged non-HDB buildings
"""
    (HERE / "scenario.yaml").write_text(doc)


def write_source_status(meta, aq, grid, buildings):
    hdb_n = sum(1 for b in buildings if str(b["osm_id"]).startswith("hdb:"))
    doc = {
        "generated_by": "cases/singapore/build_case.py",
        "window": {"name": "Toa Payoh", "centre": [LAT, LON], "half_width_m": HALF_M,
                   "epsg": EPSG, "parent_cells": [NROW, NCOL], "main_week": MAIN_WEEK},
        "fields": {
            "hdb_block_geometry": {"status": "real", "count": hdb_n,
                                   "endpoint": "https://api-open.data.gov.sg/v1/public/api/datasets/"
                                               "d_16b157c52ed637edd6ba1232e026258d/poll-download"},
            "hdb_floor_count": {"status": "real", "field": "max_floor_lvl",
                                "endpoint": "https://api-open.data.gov.sg/v1/public/api/datasets/"
                                            "d_17f5382f26140b1fdae0ba2ef6239d2f/poll-download"},
            "hdb_completion_year": {"status": "real", "field": "year_completed",
                                    "endpoint": "data.gov.sg d_17f5382f26140b1fdae0ba2ef6239d2f"},
            "osm_building_geometry": {"status": "real",
                                      "endpoint": "https://overpass-api.de/api/interpreter"},
            "osm_building_height": {"status": "derived",
                                    "rule": "height tag, else building:levels x 2.9 m",
                                    "endpoint": "https://overpass-api.de/api/interpreter"},
            "building_footprint_area": {"status": "derived", "rule": "UTM 48N polygon area"},
            "facade_m2": {"status": "derived", "rule": "perimeter x height x 0.75"},
            "road_geometry": {"status": "real", "endpoint": "https://overpass-api.de/api/interpreter"},
            "road_width": {"status": "derived",
                           "rule": "width tag, else lanes x 3.5 m, else LTA class default"},
            "fvc": {"status": "derived", "scene": meta["scene_id"],
                    "endpoint": "https://earth-search.aws.element84.com/v1/search"},
            "albedo": {"status": "derived", "scene": meta["scene_id"],
                       "endpoint": "https://earth-search.aws.element84.com/v1/search"},
            "land_cover": {"status": "real",
                           "endpoint": "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/"
                                       "2021/map/ESA_WorldCover_10m_2021_v200_N00E102_Map.tif"},
            "pm25_ugm3": {"status": "derived", "value": aq["pm25_ugm3"],
                          "note": "CAMS ~11 km model field, not an observation",
                          "endpoint": "https://air-quality-api.open-meteo.com/v1/air-quality"},
            "no2_ugm3": {"status": "derived", "value": aq["no2_ugm3"],
                         "note": "CAMS ~11 km model field, not an observation",
                         "endpoint": "https://air-quality-api.open-meteo.com/v1/air-quality"},
            "lst_day_c": {"status": "pending", "reason": "MODIS requires Earthdata credentials",
                          "intended_source": "LP DAAC MOD11A1"},
            "lst_night_c": {"status": "pending", "reason": "MODIS requires Earthdata credentials",
                            "intended_source": "LP DAAC MYD11A1"},
            "energy_kwh_m2_day": {"status": "pending",
                                  "reason": "no credential-free building-energy field for Singapore",
                                  "intended_source": "EMA Energy Statistics x LCZ 4 EUI"},
            "tree_count_plantable": {"status": "derived",
                                     "rule": "0.5 x WorldCover grass x cell area / 115 m2"},
            "building_year_non_hdb": {"status": "derived",
                                      "rule": "OSM start_date where tagged, else empty"},
        },
        "notes": [
            "data.gov.sg calls are spaced by a few seconds.",
            "Sentinel-2 scene is the least-cloudy 2023 acquisition under 30% cloud; "
            "SCL classes 4,5,6 retained.",
            "OSM building ways whose centroid falls inside an HDB block are dropped.",
        ],
    }
    write_json(HERE / "SOURCE_STATUS.json", doc)


# ---------------------------------------------------------------- io
def write_csv(path, cols, rows):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def write_json(path, obj):
    path.write_text(json.dumps(obj, indent=2) + "\n")


# ---------------------------------------------------------------- summary
def summary(meta, aq, grid):
    fp = list(csv.DictReader(open(HERE / "footprints.csv")))
    rd = list(csv.DictReader(open(HERE / "roads.csv")))
    hdb = [b for b in fp if b["osm_id"].startswith("hdb:")]
    osm = [b for b in fp if not b["osm_id"].startswith("hdb:")]
    floors = collections.Counter(int(float(b["floors"])) for b in hdb if b["floors"])
    years = [b["start_date"] for b in hdb if b["start_date"]]
    drv = [r for r in rd if r["drivable"] == "1"]
    out = {
        "hdb_blocks": len(hdb),
        "osm_buildings": len(osm),
        "floor_distribution": dict(sorted(floors.items())),
        "hdb_height_median_m": sorted(float(b["height_m"]) for b in hdb if b["height_m"])[
            len(hdb) // 2] if hdb else None,
        "completion_year_coverage": f"{len(years)}/{len(hdb)}",
        "footprint_ha": round(sum(float(b["footprint_m2"]) for b in fp) / 1e4, 2),
        "facade_m2": round(sum(float(b["facade_m2"]) for b in fp if b["facade_m2"]), 1),
        "roads": len(rd),
        "road_km": round(sum(float(r["length_m"]) for r in rd) / 1000, 2),
        "drivable_roads": len(drv),
        "drivable_km": round(sum(float(r["length_m"]) for r in drv) / 1000, 2),
        "parent_cells": len(grid),
        "fvc_range": [min(float(g["delta_fvc_baseline"]) for g in grid if g["delta_fvc_baseline"]),
                      max(float(g["delta_fvc_baseline"]) for g in grid if g["delta_fvc_baseline"])],
        "albedo_range": [min(float(g["albedo_baseline"]) for g in grid if g["albedo_baseline"]),
                         max(float(g["albedo_baseline"]) for g in grid if g["albedo_baseline"])],
        "plantable_area_m2": sum(int(g["plantable_area_m2"]) for g in grid),
        "tree_count": sum(int(g["tree_count_plantable"]) for g in grid),
        "pm25_ugm3": aq["pm25_ugm3"], "no2_ugm3": aq["no2_ugm3"],
        "lcz": 4,
        "scene": meta,
    }
    out["_pending_fields"] = sum(
        1 for g in grid for k in ("lst_day_c", "lst_night_c", "energy_kwh_m2_day")
        if g[k] == "")
    write_json(HERE / "build_summary.json", out)
    log(json.dumps(out, indent=2))


def report():
    print((HERE / "build_summary.json").read_text())


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    if cmd == "fetch":
        fetch()
    elif cmd == "build":
        build()
    elif cmd == "report":
        report()
    else:
        raise SystemExit(__doc__)

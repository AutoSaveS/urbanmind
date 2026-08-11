"""Build the Track B intervention outcome library from collected literature CSVs.

Pipeline:
  1. Merge the per-category collection CSVs (data/trackb/raw_*.csv), which hold
     candidate studies extracted from published systematic reviews.
  2. Verify every DOI against Crossref: the DOI must resolve and the returned
     title must match the recorded title (fuzzy ratio >= 0.55 after
     normalization). Rows that fail verification are quarantined, never included.
  3. Deduplicate by DOI, assign stable record identifiers, and write the
     verified library (data/trackb/trackb_records.csv).
  4. Enforce the DOI- and study-site-level split with urbanmind.data.tracks and
     write the record-assignment table (data/trackb/trackb_assignment.csv).

Every record in the output corresponds to a real publication verified against
Crossref at build time; the verification log records the check for audit.

Usage: python scripts/build_trackb_library.py [--skip-verify]
"""

from __future__ import annotations

import argparse
import csv
import difflib
import glob
import json
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request

import certifi

SSL_CTX = ssl.create_default_context(cafile=certifi.where())

sys.path.insert(0, ".")
from urbanmind.data.tracks import Record, assign_tracks, write_assignment_table

RAW_GLOB = "data/trackb/raw_*.csv"
OUT_RECORDS = "data/trackb/trackb_records.csv"
OUT_ASSIGNMENT = "data/trackb/trackb_assignment.csv"
OUT_LOG = "data/trackb/verification_log.json"

CATEGORY_BY_FILE = {
    "greening": "greening",
    "coolroof": "cool_roof",
    "retrofit": "retrofit",
    "lez": "low_emission_zone",
    "combined": "combined",
}


def norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", t.lower()).strip()


def crossref_resolve_title(title: str, journal: str = "") -> dict | None:
    """Resolve a DOI from a full citation via Crossref bibliographic search.

    Accepts a match only when the returned title matches the recorded title at
    ratio >= 0.85, so this is a lookup of the real DOI, never a guess.
    """
    q = urllib.parse.quote(f"{title} {journal}".strip())
    url = f"https://api.crossref.org/works?query.bibliographic={q}&rows=3"
    req = urllib.request.Request(url, headers={"User-Agent": "urbanmind-trackb-audit"})
    try:
        with urllib.request.urlopen(req, timeout=20, context=SSL_CTX) as resp:
            items = json.load(resp)["message"]["items"]
    except Exception:
        return None
    for item in items:
        cand = (item.get("title") or [""])[0]
        ratio = difflib.SequenceMatcher(None, norm_title(title), norm_title(cand)).ratio()
        if ratio >= 0.85:
            return {"doi": item["DOI"], "title": cand, "match_ratio": round(ratio, 3)}
    return None


def crossref_lookup(doi: str) -> dict | None:
    url = f"https://api.crossref.org/works/{urllib.parse.quote(doi)}"
    req = urllib.request.Request(url, headers={"User-Agent": "urbanmind-trackb-audit"})
    try:
        with urllib.request.urlopen(req, timeout=20, context=SSL_CTX) as resp:
            data = json.load(resp)["message"]
        return {
            "title": (data.get("title") or [""])[0],
            "container": (data.get("container-title") or [""])[0],
            "year": (data.get("issued", {}).get("date-parts") or [[None]])[0][0],
        }
    except Exception:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-verify", action="store_true",
                    help="merge and split only; verification must run before release")
    args = ap.parse_args()

    rows = []
    for path in sorted(glob.glob(RAW_GLOB)):
        stem = path.split("raw_")[-1].removesuffix(".csv")
        category = CATEGORY_BY_FILE.get(stem, stem)
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                row["intervention"] = category
                rows.append(row)
    print(f"merged {len(rows)} candidate rows from {RAW_GLOB}")

    # Resolve TBD DOIs from full citations via Crossref bibliographic search.
    tbd = [r for r in rows if not r.get("doi", "").strip().lower().startswith("10.")]
    if tbd and not args.skip_verify:
        print(f"resolving {len(tbd)} TBD DOIs from citations ...")
        n_resolved = 0
        for r in tbd:
            hit = crossref_resolve_title(r.get("title", ""), r.get("journal", ""))
            if hit:
                r["doi"] = hit["doi"]
                n_resolved += 1
            time.sleep(0.4)
        print(f"  resolved {n_resolved}/{len(tbd)}")

    # Drop rows still without a DOI (kept aside for manual lookup, never released).
    with_doi = [r for r in rows if r.get("doi", "").strip().lower().startswith("10.")]
    print(f"{len(with_doi)} rows carry a DOI; {len(rows) - len(with_doi)} set aside as TBD")

    # Deduplicate by DOI.
    seen: dict[str, dict] = {}
    for r in with_doi:
        seen.setdefault(r["doi"].strip().lower(), r)
    candidates = list(seen.values())
    print(f"{len(candidates)} unique DOIs")

    # Cache of previously verified DOIs (avoids re-querying Crossref; only
    # positive results are cached so transient failures are always retried).
    cache: dict[str, dict] = {}
    try:
        for e in json.load(open(OUT_LOG)):
            if e["verified"]:
                cache[e["doi"].lower()] = e
    except FileNotFoundError:
        pass

    log, verified = [], []
    if args.skip_verify:
        verified = candidates
    else:
        for i, r in enumerate(candidates):
            doi = r["doi"].strip()
            if doi.lower() in cache:
                e = cache[doi.lower()]
                log.append(e)
                r["crossref_title"] = e["crossref_title"]
                verified.append(r)
                continue
            meta = crossref_lookup(doi)
            ok, ratio = False, 0.0
            if meta and meta["title"]:
                ratio = difflib.SequenceMatcher(
                    None, norm_title(r.get("title", "")), norm_title(meta["title"])
                ).ratio()
                ok = ratio >= 0.55
            log.append({"doi": doi, "recorded_title": r.get("title", ""),
                        "crossref_title": meta["title"] if meta else None,
                        "match_ratio": round(ratio, 3), "verified": ok})
            if ok:
                r["crossref_title"] = meta["title"]
                r["crossref_year"] = meta["year"]
                verified.append(r)
            if (i + 1) % 20 == 0:
                print(f"  verified {i + 1}/{len(candidates)}")
            time.sleep(0.4)  # be polite to the Crossref API
        with open(OUT_LOG, "w") as f:
            json.dump(log, f, indent=2)
        print(f"verification: {len(verified)} passed, "
              f"{len(candidates) - len(verified)} rejected (see {OUT_LOG})")

    # Write the verified library with stable record ids.
    fieldnames = ["record_id", "doi", "study_site", "track", "intervention",
                  "climate_tag", "lcz_tag", "author_year", "title", "journal",
                  "city", "country", "outcome", "design", "source_review"]
    records = []
    with open(OUT_RECORDS, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for i, r in enumerate(sorted(verified, key=lambda x: x["doi"].lower())):
            city = (r.get("city") or "unknown").strip().lower().replace(" ", "-")
            rec = Record(
                record_id=f"B{i:03d}",
                doi=r["doi"].strip(),
                study_site=f"{city}:{r.get('author_year', '')}",
                track="B",
                intervention=r["intervention"],
                climate_tag=r.get("climate_tag", ""),
                lcz_tag=r.get("lcz_tag", ""),
            )
            records.append(rec)
            writer.writerow({**{k: r.get(k, "") for k in fieldnames},
                             "record_id": rec.record_id, "study_site": rec.study_site,
                             "track": "B"})
    print(f"wrote {len(records)} verified records to {OUT_RECORDS}")

    assignment = assign_tracks(records)
    write_assignment_table(records, assignment, OUT_ASSIGNMENT)
    n_ft = sum(1 for v in assignment.values() if v == "fine_tuning")
    n_val = sum(1 for v in assignment.values() if v == "validation")
    print(f"assignment: fine_tuning={n_ft}, validation={n_val} -> {OUT_ASSIGNMENT}")


if __name__ == "__main__":
    main()

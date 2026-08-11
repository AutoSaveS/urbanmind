"""Audit a BibTeX file against Crossref by DOI.

For every entry with a DOI, fetches the Crossref metadata and compares title and
first-author family name. Reports mismatches so fabricated or corrupted entries
(like the pre-revision chew2025digitaltwin) are caught mechanically.

Usage: python scripts/audit_bibliography.py path/to/main.bib [--out report.csv]
"""

import argparse
import csv
import re
import sys
import time

import requests

CROSSREF = "https://api.crossref.org/works/{doi}"


def parse_bib(path: str) -> list[dict]:
    text = open(path, encoding="utf-8").read()
    entries = []
    for m in re.finditer(r"@\w+\{([^,]+),(.*?)\n\}", text, re.S):
        key, body = m.group(1).strip(), m.group(2)
        fields = dict(
            (fm.group(1).lower(), re.sub(r"\s+", " ", fm.group(2)).strip("{} "))
            for fm in re.finditer(r"(\w+)\s*=\s*[{\"](.*?)[}\"]\s*,?\s*\n", body, re.S)
        )
        fields["key"] = key
        entries.append(fields)
    return entries


def normalize(s: str) -> str:
    s = re.sub(r"\\.|[{}$\\]", "", s or "")
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def audit_entry(entry: dict) -> dict:
    doi = entry.get("doi")
    result = {"key": entry["key"], "doi": doi or "", "status": "no_doi"}
    if not doi:
        return result
    try:
        resp = requests.get(
            CROSSREF.format(doi=doi), timeout=20,
            headers={"User-Agent": "urbanmind-bib-audit"},
        )
        if resp.status_code == 404:
            result["status"] = "doi_not_found"
            return result
        resp.raise_for_status()
        work = resp.json()["message"]
    except Exception as exc:
        result.update(status="fetch_error", detail=repr(exc))
        return result

    cr_title = normalize((work.get("title") or [""])[0])
    bib_title = normalize(entry.get("title", ""))
    title_ok = bool(cr_title and bib_title) and (
        cr_title in bib_title or bib_title in cr_title
    )

    cr_family = normalize((work.get("author") or [{}])[0].get("family", ""))
    bib_first = normalize(entry.get("author", "").split(" and ")[0].split(",")[0])
    author_ok = bool(cr_family) and cr_family in bib_first or bib_first in cr_family

    result.update(
        status="ok" if (title_ok and author_ok) else "mismatch",
        title_match=title_ok,
        author_match=author_ok,
        crossref_title=(work.get("title") or [""])[0][:120],
        crossref_first_author=cr_family,
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bibfile")
    parser.add_argument("--out", default="bib_audit_report.csv")
    args = parser.parse_args()

    entries = parse_bib(args.bibfile)
    print(f"{len(entries)} entries parsed")
    rows = []
    for i, entry in enumerate(entries, 1):
        row = audit_entry(entry)
        rows.append(row)
        flag = "" if row["status"] == "ok" else "  <-- CHECK"
        print(f"[{i}/{len(entries)}] {row['key']}: {row['status']}{flag}")
        time.sleep(0.5)  # be polite to Crossref

    with open(args.out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=sorted({k for r in rows for k in r}))
        writer.writeheader()
        writer.writerows(rows)
    bad = [r for r in rows if r["status"] not in ("ok", "no_doi")]
    print(f"\nreport written to {args.out}; {len(bad)} entries need attention")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

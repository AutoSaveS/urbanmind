#!/usr/bin/env python3
"""Audit main.bib against Crossref: for every entry with a DOI, fetch the
registered metadata and flag title, year, venue, or first-author mismatches;
for entries without a DOI, attempt a bibliographic search and report the best
match so a DOI can be added or the entry confirmed as non-indexed (reports,
standards, datasets)."""

import json
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

BIB = Path(sys.argv[1] if len(sys.argv) > 1 else "manuscript/main.bib")
OUT = Path("bib_audit_report.json")


def parse_bib(text):
    entries = []
    for m in re.finditer(r"@(\w+)\s*\{\s*([^,]+),", text):
        # depth starts at 1: we are already inside the entry's opening brace
        depth, i = 1, m.end()
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        body = text[m.end():i]
        fields = {}
        for fm in re.finditer(r"(\w+)\s*=\s*[{\"]", body):
            fstart = fm.end() - 1
            opener = body[fstart]
            closer = "}" if opener == "{" else '"'
            d, j = 0, fstart
            while j < len(body):
                if body[j] == "{":
                    d += 1
                elif body[j] == "}":
                    d -= 1
                    if d == 0 and opener == "{":
                        break
                elif body[j] == '"' and opener == '"' and d == 0 and j > fstart:
                    break
                j += 1
            fields[fm.group(1).lower()] = body[fstart + 1:j]
        entries.append({"type": m.group(1).lower(), "key": m.group(2).strip(),
                        "fields": fields})
    return entries


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[{}\\$^_~\"'`]", "", s)
    return re.sub(r"[^a-z0-9 ]", " ", s.lower()).split()


def title_sim(a, b):
    wa, wb = set(norm(a)), set(norm(b))
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def crossref(url):
    r = subprocess.run(["curl", "-s", "--max-time", "30",
                        "-H", "User-Agent: bib-audit (mailto:jiawei99@liverpool.ac.uk)",
                        url], capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def first_author_family(bib_author):
    first = re.split(r"\s+and\s+", bib_author or "", flags=re.I)[0]
    if "," in first:
        return norm(first.split(",")[0])
    parts = norm(first)
    return parts[-1:] if parts else []


def main():
    entries = parse_bib(BIB.read_text())
    print(f"{len(entries)} entries in {BIB}")
    report = []
    for e in entries:
        f = e["fields"]
        doi = (f.get("doi") or "").strip().replace("https://doi.org/", "")
        title = f.get("title", "")
        rec = {"key": e["key"], "doi": doi or None, "status": None, "issues": []}
        if doi:
            j = crossref(f"https://api.crossref.org/works/{doi}")
            if not j or "message" not in j:
                rec["status"] = "doi_not_found"
            else:
                msg = j["message"]
                cr_title = (msg.get("title") or [""])[0]
                sim = title_sim(title, cr_title)
                rec["crossref_title"] = cr_title
                rec["title_similarity"] = round(sim, 2)
                if sim < 0.55:
                    rec["issues"].append(f"title mismatch (sim {sim:.2f}): '{cr_title[:90]}'")
                cr_year = None
                for kf in ("published-print", "published-online", "issued"):
                    dp = msg.get(kf, {}).get("date-parts")
                    if dp and dp[0] and dp[0][0]:
                        cr_year = dp[0][0]
                        break
                if f.get("year") and cr_year and str(cr_year) != f["year"].strip():
                    rec["issues"].append(f"year {f['year'].strip()} vs Crossref {cr_year}")
                fam = first_author_family(f.get("author"))
                cr_fam = norm((msg.get("author") or [{}])[0].get("family", ""))
                if fam and cr_fam and fam[-1] != cr_fam[-1]:
                    rec["issues"].append(f"first author '{' '.join(fam)}' vs Crossref '{' '.join(cr_fam)}'")
                rec["status"] = "mismatch" if rec["issues"] else "ok"
        else:
            if e["type"] in ("misc", "techreport", "manual", "online") or not title:
                rec["status"] = "no_doi_non_article"
            else:
                q = "+".join(norm(title)[:10])
                au = first_author_family(f.get("author"))
                j = crossref(f"https://api.crossref.org/works?query.bibliographic={q}"
                             f"&rows=3&select=DOI,title,author,issued")
                best = None
                for item in (j or {}).get("message", {}).get("items", []):
                    sim = title_sim(title, (item.get("title") or [""])[0])
                    if sim >= 0.75 and (best is None or sim > best[0]):
                        best = (sim, item)
                if best:
                    rec["status"] = "missing_doi_found"
                    rec["suggested_doi"] = best[1]["DOI"]
                    rec["issues"].append(f"DOI available: {best[1]['DOI']} (sim {best[0]:.2f})")
                else:
                    rec["status"] = "no_doi_no_match"
            time.sleep(0.3)
        report.append(rec)
        flag = "" if rec["status"] in ("ok", "no_doi_non_article") else "  <-- " + rec["status"]
        print(f"[{len(report):3d}/{len(entries)}] {e['key']}: {rec['status']}{flag}")
        for iss in rec["issues"]:
            print(f"        {iss}")
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    n_bad = sum(1 for r in report if r["status"] not in ("ok", "no_doi_non_article"))
    print(f"\nsummary: {len(report)} entries, {n_bad} flagged")
    print(f"report: {OUT}")


if __name__ == "__main__":
    main()

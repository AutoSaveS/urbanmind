"""PRISMA Track A/B record management and record-level split enforcement.

Track A: Domain Knowledge dataset (physical constraints; grounds the KRCG stage).
Track B: Intervention Outcome dataset, further partitioned into

  - a *fine-tuning* subset, used only in Phase-3 alignment, and
  - a *validation* subset, used only to construct Experiment-2 reference effects.

The partition is enforced at the DOI **and** study-site level: no publication or
monitored site may contribute to both subsets, and multi-site publications are
assigned as whole units. This module generates the record-assignment table released
with the manuscript's supplementary data (Appendix A.5).
"""

import csv
import hashlib
from dataclasses import dataclass, asdict
from typing import Iterable


@dataclass(frozen=True)
class Record:
    record_id: str
    doi: str
    study_site: str          # normalized site key, e.g. "sg:jurong-east"
    track: str               # "A" or "B"
    intervention: str = ""   # e.g. "greening", "cool_roof" (Track B)
    climate_tag: str = ""    # Koeppen class
    lcz_tag: str = ""


def _unit_key(record: Record) -> str:
    """Publications and sites move together: the assignment unit is the pair."""
    return f"{record.doi.lower()}|{record.study_site.lower()}"


def assign_tracks(
    records: Iterable[Record],
    validation_fraction: float = 0.5,
    seed: str = "urbanmind-trackb-v1",
) -> dict[str, str]:
    """Deterministically assign Track B records to 'fine_tuning' or 'validation'.

    Assignment is by stable hash of (DOI, site) so it is reproducible from the
    record list alone and cannot drift between reruns. Records sharing a DOI or a
    study site are forced into the same subset (transitive closure via union-find),
    which guarantees the disjointness property claimed in the manuscript.

    Returns {record_id: subset} where subset is 'track_a', 'fine_tuning', or
    'validation'.
    """
    records = list(records)

    # Union-find over Track B records linking shared DOI or shared site.
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        parent[find(a)] = find(b)

    by_doi: dict[str, str] = {}
    by_site: dict[str, str] = {}
    track_b = [r for r in records if r.track == "B"]
    for r in track_b:
        key = _unit_key(r)
        find(key)
        doi, site = r.doi.lower(), r.study_site.lower()
        if doi in by_doi:
            union(key, by_doi[doi])
        else:
            by_doi[doi] = key
        if site in by_site:
            union(key, by_site[site])
        else:
            by_site[site] = key

    assignment: dict[str, str] = {}
    for r in records:
        if r.track == "A":
            assignment[r.record_id] = "track_a"
            continue
        group = find(_unit_key(r))
        digest = hashlib.sha256(f"{seed}:{group}".encode()).digest()
        u = int.from_bytes(digest[:8], "big") / 2**64
        assignment[r.record_id] = "validation" if u < validation_fraction else "fine_tuning"
    return assignment


def verify_disjoint(records: Iterable[Record], assignment: dict[str, str]) -> None:
    """Raise if any DOI or study site appears in both Track B subsets."""
    seen: dict[str, str] = {}
    for r in records:
        if r.track != "B":
            continue
        subset = assignment[r.record_id]
        for key in (f"doi:{r.doi.lower()}", f"site:{r.study_site.lower()}"):
            if key in seen and seen[key] != subset:
                raise ValueError(f"Leakage: {key} appears in both {seen[key]} and {subset}")
            seen[key] = subset


def write_assignment_table(records: Iterable[Record], assignment: dict[str, str], path: str) -> None:
    """Write the supplementary record-assignment CSV (Appendix A.5)."""
    records = list(records)
    verify_disjoint(records, assignment)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["record_id", "doi", "study_site", "track", "subset",
                        "intervention", "climate_tag", "lcz_tag"],
        )
        writer.writeheader()
        for r in records:
            row = asdict(r)
            row["subset"] = assignment[r.record_id]
            writer.writerow(row)

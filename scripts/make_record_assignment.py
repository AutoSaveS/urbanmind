"""Generate the supplementary record-assignment table (manuscript Appendix A.5).

Input: a CSV of PRISMA-retained records with at least the columns
  record_id, doi, study_site, track, intervention, climate_tag, lcz_tag
Extra columns (e.g. the bibliographic fields in data/trackb/trackb_records.csv)
are ignored.

The `climate_tag` column is filled from the climate-group table written by
scripts/assign_climate_groups.py (columns record_id, climate_group), joined on
record_id. A record listed under several groups gets them joined with ";"; a
record absent from that table keeps the tag carried in the input (usually
empty) and is reported. Climate tags do not enter the split hash, so filling
them never changes the subset assignment.

Output: the same rows plus a `subset` column (track_a / fine_tuning / validation),
with DOI- and study-site-level disjointness verified before writing.

Usage:
  python scripts/make_record_assignment.py records.csv assignment.csv \
      [--climate-groups data/trackb/climate_groups.csv]
"""

import argparse
import csv
import os
import sys
from collections import defaultdict
from dataclasses import fields

sys.path.insert(0, ".")
from urbanmind.data.tracks import Record, assign_tracks, write_assignment_table

DEFAULT_CLIMATE_GROUPS = "data/trackb/climate_groups.csv"
RECORD_FIELDS = [f.name for f in fields(Record)]


def load_climate_tags(path: str) -> dict[str, str]:
    """Return {record_id: climate tag}; several groups per record are joined with ';'."""
    groups: dict[str, list[str]] = defaultdict(list)
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            group = row["climate_group"].strip()
            if group and group not in groups[row["record_id"]]:
                groups[row["record_id"]].append(group)
    return {rid: ";".join(gs) for rid, gs in groups.items()}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("records", help="input record CSV")
    parser.add_argument("assignment", help="output assignment CSV")
    parser.add_argument("--climate-groups", default=DEFAULT_CLIMATE_GROUPS,
                        help="record_id,climate_group CSV used to fill climate_tag "
                             "(default: %(default)s)")
    args = parser.parse_args()

    climate: dict[str, str] = {}
    if os.path.exists(args.climate_groups):
        climate = load_climate_tags(args.climate_groups)
    else:
        print(f"warning: {args.climate_groups} not found; climate_tag left as in input",
              file=sys.stderr)

    records, untagged = [], []
    with open(args.records, newline="") as f:
        for row in csv.DictReader(f):
            kwargs = {k: row.get(k, "") for k in RECORD_FIELDS}
            tag = climate.get(row["record_id"], "")
            if tag:
                kwargs["climate_tag"] = tag
            elif climate:
                untagged.append(row["record_id"])
            records.append(Record(**kwargs))

    assignment = assign_tracks(records)
    write_assignment_table(records, assignment, args.assignment)
    n_val = sum(1 for v in assignment.values() if v == "validation")
    n_ft = sum(1 for v in assignment.values() if v == "fine_tuning")
    n_tagged = sum(1 for r in records if r.climate_tag)
    print(f"{len(records)} records -> fine_tuning={n_ft}, validation={n_val}; "
          f"climate_tag filled for {n_tagged}/{len(records)}; wrote {args.assignment}")
    if untagged:
        shown = ", ".join(untagged[:10]) + (" ..." if len(untagged) > 10 else "")
        print(f"{len(untagged)} record(s) without a climate group: {shown}")


if __name__ == "__main__":
    main()

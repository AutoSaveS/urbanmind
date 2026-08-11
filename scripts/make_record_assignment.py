"""Generate the supplementary record-assignment table (manuscript Appendix A.5).

Input: a CSV of PRISMA-retained records with columns
  record_id, doi, study_site, track, intervention, climate_tag, lcz_tag
Output: the same rows plus a `subset` column (track_a / fine_tuning / validation),
with DOI- and study-site-level disjointness verified before writing.

Usage: python scripts/make_record_assignment.py records.csv assignment.csv
"""

import csv
import sys

sys.path.insert(0, ".")
from urbanmind.data.tracks import Record, assign_tracks, write_assignment_table


def main() -> None:
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, newline="") as f:
        records = [Record(**row) for row in csv.DictReader(f)]
    assignment = assign_tracks(records)
    write_assignment_table(records, assignment, dst)
    n_val = sum(1 for v in assignment.values() if v == "validation")
    n_ft = sum(1 for v in assignment.values() if v == "fine_tuning")
    print(f"{len(records)} records -> fine_tuning={n_ft}, validation={n_val}; wrote {dst}")


if __name__ == "__main__":
    main()

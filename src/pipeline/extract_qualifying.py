"""Qualifying results subset (PLAN.md §1.4). Derived, no network.

Filters match_results.csv to every "... qualification" tournament and carries
the rows through verbatim plus a `campaign` column (the tournament label). This
is the raw subset; the per-team-per-campaign qualifying features (qual_ppg,
result volatility, opponent-Elo-adjusted form, …) are built on top of it at
indices time (PLAN.md §1.4 / Stage 3), not here.

Derived + regenerable -> gitignored. Stdlib only.
Run: python -m src.pipeline.extract_qualifying
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RESULTS_CSV = REPO / "data" / "raw" / "match_results.csv"
QUALIFYING_CSV = REPO / "data" / "raw" / "qualifying_results.csv"


def extract(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        if "qualification" in r["tournament"].lower():
            out.append({**r, "campaign": r["tournament"]})
    return out


def main() -> None:
    rows = list(csv.DictReader(RESULTS_CSV.open()))
    qual = extract(rows)
    if not qual:
        raise ValueError("no qualification matches found in match_results.csv")

    fields = list(rows[0].keys()) + ["campaign"]
    QUALIFYING_CSV.parent.mkdir(parents=True, exist_ok=True)
    with QUALIFYING_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(qual)
    print(f"wrote {len(qual)} qualifying matches -> {QUALIFYING_CSV.relative_to(REPO)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"qualifying extract failed: {e}", file=sys.stderr)
        sys.exit(1)

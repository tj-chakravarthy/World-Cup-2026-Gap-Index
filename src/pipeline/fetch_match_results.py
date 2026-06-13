"""International match results + shootouts (PLAN.md §1.4, §1.8).

Source: martj42/international_results on GitHub (keyless raw CSVs), not the
Kaggle mirror the plan named — same data, no credentials, so it runs in CI and
the daily cron without a secret. results.csv covers 1872..2026 (incl. the WC26
fixtures themselves, NA-scored until played) and feeds the Dixon-Coles goals
model; shootouts.csv backs the §1.8 shootout features and the §5.3 penalties
nudge.

Raw passthrough by design. Team names are kept verbatim — martj42 spellings
("Czech Republic", "South Korea", "United States") differ from the fixtures'
FIFA codes, and reconciling them is the name_matcher step, not this fetch.
Importance weighting (§1.4) and the WC26 / unplayed exclusions are applied at
training-set assembly, not here. Scores normalised NA -> "" to match
fixtures_2026.csv.

Output is large and fully regenerable from the URL, so it stays gitignored
(unlike the small canonical fixtures/venues spine). Stdlib only.
"""

from __future__ import annotations

import csv
import io
import sys
import urllib.request
from pathlib import Path

BASE = "https://raw.githubusercontent.com/martj42/international_results/master"
RESULTS_URL = f"{BASE}/results.csv"
SHOOTOUTS_URL = f"{BASE}/shootouts.csv"

REPO = Path(__file__).resolve().parents[2]
RESULTS_CSV = REPO / "data" / "raw" / "match_results.csv"
SHOOTOUTS_CSV = REPO / "data" / "raw" / "shootout_history.csv"

_SCORE_COLS = ("home_score", "away_score")


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "gapindex-results"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read().decode("utf-8")


def normalize_results(text: str) -> tuple[list[str], list[dict]]:
    """Parse martj42 results.csv; turn NA scores into "" so unplayed/future
    rows read like the rest of the pipeline. Names and tournament kept verbatim."""
    reader = csv.DictReader(io.StringIO(text))
    fields = reader.fieldnames or []
    rows = []
    for row in reader:
        for c in _SCORE_COLS:
            if row.get(c) == "NA":
                row[c] = ""
        rows.append(row)
    return fields, rows


def parse_shootouts(text: str) -> tuple[list[str], list[dict]]:
    reader = csv.DictReader(io.StringIO(text))
    return reader.fieldnames or [], list(reader)


def _write(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    rfields, results = normalize_results(fetch_text(RESULTS_URL))
    sfields, shootouts = parse_shootouts(fetch_text(SHOOTOUTS_URL))

    if len(results) < 40_000:
        raise ValueError(f"results.csv suspiciously short: {len(results)} rows")
    if {"date", "home_team", "away_team", "home_score", "away_score",
            "tournament"} - set(rfields):
        raise ValueError(f"unexpected results columns: {rfields}")
    if len(shootouts) < 400:
        raise ValueError(f"shootouts.csv suspiciously short: {len(shootouts)} rows")

    _write(RESULTS_CSV, rfields, results)
    _write(SHOOTOUTS_CSV, sfields, shootouts)
    played = sum(1 for r in results if r["home_score"] != "")
    print(f"wrote {len(results)} results ({played} played) -> {RESULTS_CSV}")
    print(f"wrote {len(shootouts)} shootouts -> {SHOOTOUTS_CSV}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"fetch_match_results failed: {e}", file=sys.stderr)
        sys.exit(1)

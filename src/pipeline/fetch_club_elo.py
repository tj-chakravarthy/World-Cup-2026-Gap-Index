"""Club Elo snapshot — clubelo.com (PLAN.md §1.8). Keyless, no scraping.

clubelo serves the whole table valid on a given date as CSV
(Rank,Club,Country,Level,Elo,From,To). We keep the current snapshot; mapping
each squad player's club onto these names (and the mean_club_elo / top11 /
variance features) is downstream feature work — clubelo is Europe-centric, so
non-European clubs get a documented FBref league-median fallback there, not here.

Snapshot, regenerable -> gitignored (unlike the canonical spine). Stdlib only.
Run: python -m src.pipeline.fetch_club_elo
"""

from __future__ import annotations

import csv
import io
import sys
import urllib.request
from datetime import date, timezone, datetime
from pathlib import Path

API = "http://api.clubelo.com/{day}"

REPO = Path(__file__).resolve().parents[2]
CLUB_ELO_CSV = REPO / "data" / "raw" / "club_elo_current.csv"
FIELDS = ["club", "country", "level", "elo", "rank", "as_of"]


def parse_snapshot(text: str, as_of: str) -> list[dict]:
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        if not r.get("Elo"):
            continue
        rows.append({
            "club": r["Club"], "country": r["Country"], "level": r["Level"],
            "elo": round(float(r["Elo"]), 2), "rank": r["Rank"], "as_of": as_of,
        })
    return rows


def main(day: str | None = None) -> None:
    day = day or datetime.now(timezone.utc).date().isoformat()
    with urllib.request.urlopen(API.format(day=day), timeout=30) as resp:
        text = resp.read().decode("utf-8")
    rows = parse_snapshot(text, day)
    if len(rows) < 100:
        raise ValueError(f"clubelo returned only {len(rows)} clubs for {day}")

    CLUB_ELO_CSV.parent.mkdir(parents=True, exist_ok=True)
    with CLUB_ELO_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} club Elo ratings (as_of {day}) -> {CLUB_ELO_CSV.relative_to(REPO)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"club elo fetch failed: {e}", file=sys.stderr)
        sys.exit(1)

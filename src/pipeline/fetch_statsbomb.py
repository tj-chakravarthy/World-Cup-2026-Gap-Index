"""StatsBomb open-data match index (PLAN.md §1.3). Keyless GitHub raw, no statsbombpy.

Pulls the match list for the five backtest/CV tournaments — WC 2018/2022, Euro
2020/2024, Copa América 2024 (PLAN.md §4.5 folds) — into data/raw/statsbomb_events/.
This is the index only: which matches exist, their teams, date and score. The
full event download (the GBs that feed VAEP training) is Stage 2 work and is left
to event_url() below, not run here — no point dragging it in before the VAEP
pipeline exists.

Index + events are a regenerable cache -> gitignored. Stdlib only.
Run: python3 -m src.pipeline.fetch_statsbomb
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

RAW = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
MATCHES_URL = RAW + "/matches/{cid}/{sid}.json"

REPO = Path(__file__).resolve().parents[2]
SB_DIR = REPO / "data" / "raw" / "statsbomb_events"

# (competition_id, season_id, label) — verified present in competitions.json.
TARGETS = [
    (43, 3, "world_cup_2018"),
    (43, 106, "world_cup_2022"),
    (55, 43, "euro_2020"),
    (55, 282, "euro_2024"),
    (223, 282, "copa_america_2024"),
]


def event_url(match_id: int) -> str:
    """Per-match events endpoint — for the Stage-2 VAEP download, not used here."""
    return f"{RAW}/events/{match_id}.json"


def _get(url: str):
    return json.load(urllib.request.urlopen(url, timeout=30))


def fetch_index() -> list[tuple[str, int]]:
    """Write each tournament's match list; return (label, n_matches)."""
    SB_DIR.mkdir(parents=True, exist_ok=True)
    summary = []
    for cid, sid, label in TARGETS:
        matches = _get(MATCHES_URL.format(cid=cid, sid=sid))
        if not matches:
            raise ValueError(f"no matches for {label} (cid={cid}, sid={sid})")
        (SB_DIR / f"matches_{cid}_{sid}.json").write_text(json.dumps(matches, indent=2))
        summary.append((label, len(matches)))
    return summary


def main() -> None:
    for label, n in fetch_index():
        print(f"  {n:>3} matches  {label}")
    print(f"wrote match index for {len(TARGETS)} tournaments -> {SB_DIR.relative_to(REPO)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"statsbomb index fetch failed: {e}", file=sys.stderr)
        sys.exit(1)

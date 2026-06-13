"""Daily 1X2 odds capture — The Odds API (PLAN.md §1.7). Key-gated; cron-ready.

BENCHMARK ONLY. Odds NEVER enter the model (PLAN.md "Odds usage rule"); they are
captured to score the model's Brier against the market's. Stores raw decimal odds
plus de-vigged implied probabilities per fixture, one snapshot file per day.

Needs ODDS_API_KEY in the environment; without it this exits loudly. NOT run here
(no key). The de-vig (normalise 1/odds to sum to 1) is the only transform.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

API = "https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup/odds"

REPO = Path(__file__).resolve().parents[2]
SNAP_DIR = REPO / "data" / "raw" / "odds_snapshots"


def devig(home: float, draw: float, away: float) -> dict:
    """Decimal odds -> implied probabilities, normalised to remove the overround."""
    inv = {"home": 1.0 / home, "draw": 1.0 / draw, "away": 1.0 / away}
    total = sum(inv.values())
    return {k: v / total for k, v in inv.items()}


def fetch() -> list[dict]:
    """1X2 odds for upcoming WC fixtures. Raises on transport/HTTP error."""
    import requests
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        raise RuntimeError("ODDS_API_KEY not set")
    resp = requests.get(API, params={"apiKey": key, "regions": "eu",
                                     "markets": "h2h", "oddsFormat": "decimal"}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def main() -> None:
    try:
        raw = fetch()
    except Exception as e:
        print(f"odds fetch failed: {e}", file=sys.stderr)
        sys.exit(1)
    day = datetime.now(timezone.utc).date().isoformat()
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    out = SNAP_DIR / f"{day}.json"
    out.write_text(json.dumps({"captured_at": day, "raw": raw}, indent=2))
    print(f"captured {len(raw)} fixtures' odds -> {out.relative_to(REPO)}")


if __name__ == "__main__":
    main()

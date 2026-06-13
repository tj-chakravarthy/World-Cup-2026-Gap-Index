"""Injury snapshot — API-Football (PLAN.md §1.6). Key-gated; cron-ready.

Snapshots current injuries for the squads so the live feature state can carry
key_player_out / starters_out_count. Needs API_FOOTBALL_KEY in the environment;
without it this exits loudly rather than writing an empty snapshot. On a fetch
failure it falls back to the last good snapshot and marks it stale (PLAN.md §6
operational robustness) — one broken scraper degrades one panel, never the site.

NOT run in this environment (no key present). Wired so a cron run with the key
set works unchanged. requests is in the apt base.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

API = "https://v3.football.api-sports.io/injuries"

REPO = Path(__file__).resolve().parents[2]
SNAPSHOT = REPO / "data" / "raw" / "injuries_snapshot.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def fetch(season: int = 2026) -> dict:
    """Live injuries for the tournament. Raises on transport/HTTP error so the
    caller can decide to fall back to cache."""
    import requests
    key = os.environ.get("API_FOOTBALL_KEY")
    if not key:
        raise RuntimeError("API_FOOTBALL_KEY not set")
    resp = requests.get(API, headers={"x-apisports-key": key},
                        params={"season": season}, timeout=30)
    resp.raise_for_status()
    return {"generated_at": _now(), "stale": False, "response": resp.json().get("response", [])}


def main() -> None:
    try:
        snap = fetch()
    except Exception as e:
        if SNAPSHOT.exists():
            snap = json.loads(SNAPSHOT.read_text())
            snap["stale"] = True
            print(f"injury fetch failed ({e}); kept cached snapshot, marked stale", file=sys.stderr)
        else:
            print(f"injury fetch failed and no cache to fall back on: {e}", file=sys.stderr)
            sys.exit(1)
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps(snap, indent=2))
    print(f"wrote injury snapshot ({len(snap['response'])} records, stale={snap['stale']}) "
          f"-> {SNAPSHOT.relative_to(REPO)}")


if __name__ == "__main__":
    main()

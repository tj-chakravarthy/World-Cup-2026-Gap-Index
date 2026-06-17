"""National Elo — current snapshot (PLAN.md §1.8).

Source: eloratings.net World.tsv (current ranking) joined to en.teams.tsv
(eloratings 2-letter code -> country name). Keyless TSV, no Kaggle creds. This
is the CURRENT snapshot only, which is exactly what the Elo-sigmoid baseline
(member E) needs for the 2026 fixtures.

World.tsv has no header; columns used: 0 = rank, 2 = eloratings code, 3 =
current Elo. en.teams.tsv is `code <tab> name [<tab> aliases...]`.

The backtest folds' pre-tournament Elo for past years isn't fetched here — eloratings has no
stable historical-file URL, so elo_history.py computes it from match results instead
(docs/deviations.md).

Names are eloratings' English spellings; the crosswalk eloratings-code ->
FIFA-trigram (to join the 2026 fixtures) is the name_matcher step, not this fetch.
Output is regenerable from the URL, so it stays gitignored. Stdlib only.
"""

from __future__ import annotations

import csv
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

WORLD_URL = "http://eloratings.net/World.tsv"
TEAMS_URL = "http://eloratings.net/en.teams.tsv"

REPO = Path(__file__).resolve().parents[2]
ELO_CSV = REPO / "data" / "raw" / "elo_national_current.csv"

# World.tsv column positions (no header)
_RANK, _CODE, _ELO = 0, 2, 3


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "gapindex-elo"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def parse_teams(text: str) -> dict[str, str]:
    """eloratings code -> primary English name (col 1; later cols are aliases)."""
    out = {}
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0]:
            out[parts[0]] = parts[1]
    return out


def build_elo(world_text: str, teams: dict[str, str], as_of: str) -> list[dict]:
    rows = []
    for line in world_text.splitlines():
        c = line.split("\t")
        if len(c) <= _ELO or not c[_CODE]:
            continue
        code = c[_CODE]
        rows.append({
            "elo_code": code,
            "team_name": teams.get(code, ""),
            "rank": int(c[_RANK]),
            "elo": int(c[_ELO]),
            "as_of": as_of,
        })
    return rows


def main() -> None:
    as_of = datetime.now(timezone.utc).date().isoformat()
    teams = parse_teams(fetch_text(TEAMS_URL))
    rows = build_elo(fetch_text(WORLD_URL), teams, as_of)

    if len(rows) < 150:
        raise ValueError(f"World.tsv suspiciously short: {len(rows)} teams")
    unmatched = [r["elo_code"] for r in rows if not r["team_name"]]
    if unmatched:
        # not fatal — name is for readability; the join key is the code
        print(f"warning: {len(unmatched)} elo codes without a name: {unmatched[:10]}",
              file=sys.stderr)

    ELO_CSV.parent.mkdir(parents=True, exist_ok=True)
    with ELO_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["elo_code", "team_name", "rank", "elo", "as_of"])
        w.writeheader()
        w.writerows(rows)
    top = ", ".join(f"{r['team_name'] or r['elo_code']} {r['elo']}" for r in rows[:3])
    print(f"wrote {len(rows)} national Elo rows (as of {as_of}) -> {ELO_CSV}")
    print(f"  top: {top}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"fetch_elo failed: {e}", file=sys.stderr)
        sys.exit(1)

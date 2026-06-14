"""Manager-per-team table (PLAN.md §3 context feature — manager-quality gap explainer).

The thin model gives a squad-talent baseline; manager quality is a Stage-3 feature
that predicts the *gap* (over/under-performance vs talent), which is where a
top-club manager (Tuchel, Ancelotti) would show up. This builds the identity layer:
which manager led which team. Pedigree features (clubs managed, club Elo of those
clubs, win rate) are a later enrichment that joins onto this table.

Two sources:
- Historical (backtest tournaments): managers are in the StatsBomb match metadata
  we already mirror locally — keyless, no scrape. Fully built here. Regenerable
  from the mirror, so gitignored.
- WC2026: managers come from Wikipedia head-coach listings; that scrape is not yet
  wired, so a skeleton (the 48 teams from squads_2026.csv, manager blank) is
  emitted to be filled. Tracked as canonical (like squads_2026.csv).

Run: python -m src.pipeline.fetch_managers
"""

from __future__ import annotations

import csv
import glob
import json
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"
SB_ROOT = RAW / "statsbomb-open-data"


def _team_managers(match: dict) -> list[dict]:
    """Both teams' (team, manager) rows from one StatsBomb match. Pure, testable."""
    out = []
    for side in ("home", "away"):
        team = match.get(f"{side}_team", {}) or {}
        name = team.get(f"{side}_team_name")
        for mgr in (team.get("managers") or []):
            if not name or not mgr.get("name"):
                continue
            out.append({
                "team": name,
                "manager_id": mgr.get("id"),
                "manager_name": mgr.get("name"),
                "manager_nickname": mgr.get("nickname"),
                "manager_dob": mgr.get("dob"),
                "manager_country": (mgr.get("country") or {}).get("name"),
            })
    return out


def managers_from_statsbomb(root: Path = SB_ROOT) -> list[dict]:
    """One row per (tournament, season, team): the modal manager across the run
    (handles mid-tournament caretaker noise by taking the most frequent)."""
    by_key: dict[tuple, Counter] = {}
    meta: dict[tuple, dict] = {}
    for f in sorted(glob.glob(str(root / "matches" / "*" / "*.json"))):
        for m in json.load(open(f)):
            comp = (m.get("competition") or {}).get("competition_name", "?")
            season = (m.get("season") or {}).get("season_name", "?")
            for r in _team_managers(m):
                key = (comp, season, r["team"])
                by_key.setdefault(key, Counter())[r["manager_name"]] += 1
                meta[(key, r["manager_name"])] = r
    rows = []
    for (comp, season, team), cnt in sorted(by_key.items()):
        top = cnt.most_common(1)[0][0]
        rows.append({"tournament": comp, "season": season, "team": team,
                     **meta[((comp, season, team), top)]})
    return rows


def build_2026_skeleton(squads_csv: Path = RAW / "squads_2026.csv") -> list[dict]:
    """48-team skeleton from squads_2026.csv, manager blank (Wikipedia fill TODO)."""
    seen: dict[str, str] = {}
    with open(squads_csv) as f:
        for row in csv.DictReader(f):
            seen[row["country_code"]] = row["country"]
    return [{"country_code": cc, "country": c, "manager_name": "",
             "manager_dob": "", "source": "TODO:wikipedia"}
            for cc, c in sorted(seen.items())]


def main() -> None:
    hist = managers_from_statsbomb()
    out_h = RAW / "managers_historical.csv"
    with open(out_h, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["tournament", "season", "team", "manager_id",
            "manager_name", "manager_nickname", "manager_dob", "manager_country"])
        w.writeheader()
        w.writerows(hist)
    print(f"historical: {len(hist)} (tournament,team) rows -> {out_h.name}")

    out_s = RAW / "managers_2026.csv"
    if out_s.exists():
        print(f"2026: {out_s.name} exists, not overwritten (won't clobber filled data)")
    else:
        skel = build_2026_skeleton()
        with open(out_s, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["country_code", "country",
                "manager_name", "manager_dob", "source"])
            w.writeheader()
            w.writerows(skel)
        print(f"2026 skeleton: {len(skel)} teams (manager blank) -> {out_s.name}")


if __name__ == "__main__":
    main()

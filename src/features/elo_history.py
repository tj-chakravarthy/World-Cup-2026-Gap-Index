"""National Elo computed from international results (PLAN.md §1.8 / §4.5).

PLAN named the eloratings.net Kaggle dataset for year-end Elo snapshots; that
isn't keyless, and fetch_elo.py carries only the current snapshot. The backtest
folds (§4.5) and the per-tournament ELO index need Elo *as it stood before each
past tournament*, so we compute our own series from the ~150y of match_results we
already have. Reproducible, keyless, queryable as-of any date.

Method (World Football Elo Ratings conventions): start 1500; expected score from
the rating gap + 100 home advantage on non-neutral games; update
elo += K * G * (S - E), with K by match importance and G a goal-difference
multiplier. Divergence from the Kaggle feed recorded in docs/deviations.md.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RESULTS_CSV = REPO / "data" / "raw" / "match_results.csv"
OUT_CSV = REPO / "data" / "processed" / "elo_pretournament.csv"

START_ELO = 1500.0
HOME_ADV = 100.0

# continental championship finals (not qualification) — K=50
_CONTINENTAL_FINALS = {
    "UEFA Euro", "Copa América", "African Cup of Nations", "AFC Asian Cup",
    "Gold Cup", "CONCACAF Championship", "OFC Nations Cup", "Confederations Cup",
}

# pre-tournament snapshot dates (day before kickoff): backtest folds + live
TOURNAMENT_CUTOFFS = {
    "world_cup_2018": "2018-06-13",
    "euro_2020": "2021-06-10",
    "world_cup_2022": "2022-11-19",
    "euro_2024": "2024-06-13",
    "copa_america_2024": "2024-06-19",
    "world_cup_2026": "2026-06-10",
}


def match_weight(tournament: str) -> int:
    """K-factor by match importance (World Football Elo Ratings)."""
    t = tournament or ""
    tl = t.lower()
    if t == "FIFA World Cup":
        return 60
    if "qualification" in tl:
        return 40
    if "nations league" in tl:
        return 40
    if t in _CONTINENTAL_FINALS:
        return 50
    if tl == "friendly":
        return 20
    return 30


def gd_multiplier(gd: int) -> float:
    """Goal-difference weight: 1 for 0/1, 1.5 for 2, (11+gd)/8 for 3+."""
    gd = abs(gd)
    if gd <= 1:
        return 1.0
    if gd == 2:
        return 1.5
    return (11 + gd) / 8.0


def expected(rh: float, ra: float, home_adv: float) -> float:
    return 1.0 / (1.0 + 10.0 ** (-((rh + home_adv) - ra) / 400.0))


def run_elo(matches):
    """matches = iterable of (date, home, away, hg, ag, neutral, tournament),
    processed in date order. Returns (final_ratings, history); history maps
    team -> chronological list of (date, elo_after_match)."""
    ratings: dict[str, float] = {}
    history: dict[str, list] = defaultdict(list)
    for date, home, away, hg, ag, neutral, tournament in sorted(matches):
        rh = ratings.get(home, START_ELO)
        ra = ratings.get(away, START_ELO)
        ha = 0.0 if neutral else HOME_ADV
        eh = expected(rh, ra, ha)
        sh = 1.0 if hg > ag else 0.5 if hg == ag else 0.0
        delta = match_weight(tournament) * gd_multiplier(hg - ag) * (sh - eh)
        ratings[home] = rh + delta
        ratings[away] = ra - delta
        history[home].append((date, ratings[home]))
        history[away].append((date, ratings[away]))
    return ratings, history


def snapshot(history, as_of: str) -> dict[str, float]:
    """Each team's most recent Elo on or before `as_of` (history is chronological)."""
    out = {}
    for team, recs in history.items():
        e = None
        for d, elo in recs:
            if d <= as_of:
                e = elo
            else:
                break
        if e is not None:
            out[team] = round(e, 1)
    return out


def load_matches(path: Path = RESULTS_CSV):
    out = []
    for r in csv.DictReader(path.open()):
        d = r.get("date")
        if not d:
            continue
        try:
            hg, ag = int(r["home_score"]), int(r["away_score"])
        except (ValueError, KeyError):
            continue
        out.append((d, r["home_team"], r["away_team"], hg, ag,
                    r["neutral"].strip().lower() == "true", r["tournament"]))
    return out


def main() -> None:
    _, history = run_elo(load_matches())
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tournament", "as_of", "team", "elo"])
        for label, cutoff in TOURNAMENT_CUTOFFS.items():
            for team, elo in sorted(snapshot(history, cutoff).items(), key=lambda kv: -kv[1]):
                w.writerow([label, cutoff, team, elo])
    print(f"wrote pre-tournament Elo snapshots -> {OUT_CSV.relative_to(REPO)}")
    live = snapshot(history, TOURNAMENT_CUTOFFS["world_cup_2026"])
    print("top 12 by computed Elo (as of 2026-06-10):")
    for t, e in sorted(live.items(), key=lambda kv: -kv[1])[:12]:
        print(f"  {e:7.1f}  {t}")


if __name__ == "__main__":
    main()

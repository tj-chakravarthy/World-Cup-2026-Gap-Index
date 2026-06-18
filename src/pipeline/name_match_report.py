"""Name-match coverage report: FBref (basic) <-> Understat (xG) club players.

PLAN's highest-risk data step. Runs the fuzzy matcher across the real club feeds
and reports how cleanly they join, plus the unmatched worklist that seeds the
manual name_overrides.csv review. Does NOT auto-write overrides — auto-match the
easy majority, surface the rest. Match is per (league, season): the candidate set
is that league-season's FBref players. Stdlib (rapidfuzz used if present).

Run: python3 -m src.pipeline.name_match_report
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from src.pipeline.name_matcher import _HAS_RAPIDFUZZ, Matcher, load_overrides

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"

LEAGUE_MAP = {"EPL": "ENG", "La_liga": "ESP", "Bundesliga": "GER",
              "Serie_A": "ITA", "Ligue_1": "FRA"}
SEASON_MAP = {"2017": "2017-2018", "2020": "2020-2021", "2021": "2021-2022",
              "2023": "2023-2024", "2025": "2025-2026"}


def _col(path: Path, col: str) -> list[str]:
    return [r[col] for r in csv.DictReader(path.open()) if r.get(col)]


def report(seasons=("2023",)) -> None:
    overrides = load_overrides(context="player")
    total = Counter()
    unmatched: list[tuple[str, str, float]] = []
    for us_season in seasons:
        fb_season = SEASON_MAP[us_season]
        for ul, fl in LEAGUE_MAP.items():
            fb_path = RAW / f"fbref_{fl}_{fb_season}_standard.csv"
            us_path = RAW / f"understat_{ul}_{us_season}.csv"
            if not fb_path.exists() or not us_path.exists():
                continue
            m = Matcher(choices=_col(fb_path, "player"), overrides=overrides)
            for name in _col(us_path, "player_name"):
                _, score, method = m.match(name)
                total[method] += 1
                if method == "none":
                    unmatched.append((f"{ul} {us_season}", name, round(score, 2)))

    n = sum(total.values()) or 1
    print(f"matcher backend: {'rapidfuzz' if _HAS_RAPIDFUZZ else 'difflib'}")
    print(f"matched {sum(total.values())} Understat players -> FBref [{', '.join(seasons)}]:")
    for meth in ("exact", "override", "fuzzy", "none"):
        print(f"  {meth:9s} {total[meth]:5d}  ({total[meth] / n:.1%})")

    out = RAW / "name_unmatched_understat_fbref.csv"
    unmatched.sort(key=lambda r: -r[2])
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["context", "source_name", "best_score"])
        w.writerows(unmatched)
    print(f"\nunmatched worklist ({len(unmatched)}) -> {out.name} (near-misses first):")
    for ctx, name, score in unmatched[:12]:
        print(f"  {score:.2f}  {name:28s} [{ctx}]")


if __name__ == "__main__":
    report()

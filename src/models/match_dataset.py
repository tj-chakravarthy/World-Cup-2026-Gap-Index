"""Match training set (PLAN.md §4.1) — one row per fixture.

A row holds team1 and team2 squad-index *levels* and *differentials* plus a single
3-class target {0: team1 win, 1: draw, 2: team2 win}. The modelling unit is the
fixture, never the team-match (no mirrored two-rows-per-fixture). To kill ordering
bias, training augments each fixture with BOTH orderings (swap team1<->team2 and flip
the target); inference averages over both orderings elsewhere.

Training fixtures are the backtest tournaments' matches (WC2018, Euro2020, WC2022,
Euro2024, Copa2024) from match_results.csv, joined to that tournament's squad indices
(src/features/indices.py). WC2026 is the prediction target, not training. Team names
are matched per tournament to the index team set (small candidate set, reliable).
pandas only.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.features.indices import INDEX_COLS
from src.pipeline.name_matcher import Matcher

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"
PROC = REPO / "data" / "processed"

# tournament -> (match_results tournament label, date window that isolates the edition)
TOURNAMENT_WINDOW = {
    "world_cup_2018": ("FIFA World Cup", "2018-06-01", "2018-07-31"),
    "euro_2020": ("UEFA Euro", "2021-06-01", "2021-07-31"),  # COVID-delayed to 2021
    "world_cup_2022": ("FIFA World Cup", "2022-11-01", "2022-12-31"),
    "euro_2024": ("UEFA Euro", "2024-06-01", "2024-07-31"),
    "copa_america_2024": ("Copa América", "2024-06-01", "2024-07-31"),
}


def outcome(score1, score2) -> int:
    """3-class result from team1's perspective: 0 win, 1 draw, 2 loss."""
    if score1 > score2:
        return 0
    return 1 if score1 == score2 else 2


def tournament_matches(results: pd.DataFrame, tournament: str) -> pd.DataFrame:
    """The played matches of one tournament edition (label + date window)."""
    label, d0, d1 = TOURNAMENT_WINDOW[tournament]
    d = results["date"].astype(str)
    m = results[(results["tournament"] == label) & (d >= d0) & (d <= d1)]
    return m.dropna(subset=["home_score", "away_score"])


def _fixture_row(tournament, team1, team2, i1, i2, score1, score2) -> dict:
    """One fixture row: index levels for both teams + symmetric differentials +
    3-class target. Pure."""
    row = {"tournament": tournament, "team1": team1, "team2": team2,
           "target": outcome(score1, score2)}
    for c in INDEX_COLS:
        row[f"{c}1"], row[f"{c}2"] = i1[c], i2[c]
        row[f"{c}_diff"] = i1[c] - i2[c]
    return row


def build_match_dataset(indices: pd.DataFrame, results: pd.DataFrame,
                        tournaments: list[str] | None = None,
                        augment: bool = True) -> pd.DataFrame:
    """Assemble the fixture-level training set over the backtest tournaments. Each
    fixture is emitted in both orderings when `augment` (swap-augmentation, §4.1)."""
    names = tournaments or list(TOURNAMENT_WINDOW)
    rows = []
    for t in names:
        idx = indices[indices["tournament"] == t]
        if idx.empty:
            continue
        by_team = idx.set_index("team")
        matcher = Matcher(choices=list(by_team.index))
        for _, m in tournament_matches(results, t).iterrows():
            h = matcher.match(m["home_team"])[0]
            a = matcher.match(m["away_team"])[0]
            if h is None or a is None:  # a non-participant (e.g. a friendly) — skip
                continue
            i1, i2 = by_team.loc[h], by_team.loc[a]
            hs, as_ = m["home_score"], m["away_score"]
            rows.append(_fixture_row(t, h, a, i1, i2, hs, as_))
            if augment:
                rows.append(_fixture_row(t, a, h, i2, i1, as_, hs))
    return pd.DataFrame(rows)


def feature_columns() -> list[str]:
    """The model feature columns: both teams' index levels + the differentials."""
    cols = []
    for c in INDEX_COLS:
        cols += [f"{c}1", f"{c}2", f"{c}_diff"]
    return cols


def main() -> None:
    indices = pd.read_csv(PROC / "squad_indices.csv")
    results = pd.read_csv(RAW / "match_results.csv")
    ds = build_match_dataset(indices, results)
    PROC.mkdir(parents=True, exist_ok=True)
    out = PROC / "match_training_set.csv"
    ds.to_csv(out, index=False)
    n_fix = len(ds) // 2
    print(f"match training set: {len(ds)} rows ({n_fix} fixtures, swap-augmented) "
          f"-> {out.relative_to(REPO)}")
    print(ds.groupby("tournament").size().to_string())
    print("\ntarget balance (0 t1win / 1 draw / 2 t2win):",
          ds["target"].value_counts().sort_index().to_dict())


if __name__ == "__main__":
    main()

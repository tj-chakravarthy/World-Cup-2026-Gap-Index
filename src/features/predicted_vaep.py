"""Predicted VAEP — the club-to-country translation model (PLAN.md §2.2).

The project's signature method. Observed tournament VAEP exists only for players
who appeared in a past tournament; it is stale or missing for most 2026 squads. So
we train a regression that predicts a player's *tournament* VAEP-per-90 from his
*club-season* stats (the season preceding the tournament), then apply it to every
2026 player with 2025/26 club stats.

Training rows: each (player, tournament) with observed VAEP and club stats in the
preceding season (PLAN's tournament->season map below). Features today are the
basic FBref box-score rates (the Opta advanced columns are withheld, see
docs/deviations.md); Understat xG, league strength and market-value percentile slot
in as the feeds land — the FEATURES list and the optional merges are the only edit.
Model: shallow HistGradientBoosting (handles missing features natively — non-Big-5
players have no Understat xG, some have no market value).

Honesty (PLAN "Known Challenges"): club form genuinely doesn't fully translate, so
expect a modest R² (~0.3-0.5) — that gap *is* the thesis. The reported R²/MAE come
from leave-one-tournament-out CV (each tournament predicted by a model blind to it),
the same blind-fold scatter shown on /method. The production model (for the live
2026 prediction) trains on everything; the nested-CV refit per fold is Stage 3.

Run: python3 -m src.features.predicted_vaep
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, r2_score

from src.features.player_features import load_player_features
from src.pipeline.name_matcher import Matcher, normalize

REPO = Path(__file__).resolve().parents[2]
PROC = REPO / "data" / "processed"

# tournament (vaep.py label) -> preceding Tier-1 club season (PLAN §1.2 table).
TOURNAMENT_SEASON = {
    "world_cup_2018": "2017-2018",
    "euro_2020": "2020-2021",
    "world_cup_2022": "2021-2022",
    "euro_2024": "2023-2024",
    "copa_america_2024": "2023-2024",
}
LIVE_SEASON = "2025-2026"  # for the 2026 prediction
POS_GROUPS = ["GK", "DF", "MF", "FW"]

# Per-90 club percentiles (within season+position, leakage-safe — PLAN §2.2/§3) plus
# age and club minutes. Percentiles normalise league/era scale; the `_pct` columns
# come from player_features.build_features. Understat xG percentiles are NaN for
# non-Big-5 players — HGB handles that natively. Market-value percentile slots in
# here once the Transfermarkt squad values are joined.
FEATURES = [
    "age", "minutes_90s",
    "goals_per90_pct", "assists_per90_pct",
    "shooting_shots_per90_pct", "shooting_shots_on_target_per90_pct",
    "us_xg_per90_pct", "us_npxg_per90_pct", "us_xa_per90_pct",
    "us_key_passes_per90_pct", "us_xgchain_per90_pct", "us_xgbuildup_per90_pct",
]
TARGET = "vaep_per90"
MIN_TOURNAMENT_MINUTES = 90.0  # PLAN §2.2: observed VAEP with >= 90 min


def position_onehot(pos_group: pd.Series) -> pd.DataFrame:
    """Stable GK/DF/MF/FW one-hot (fixed columns so train/predict align)."""
    g = pos_group.where(pos_group.isin(POS_GROUPS))
    return pd.DataFrame({f"pos_{p}": (g == p).astype(float) for p in POS_GROUPS},
                        index=pos_group.index)


def feature_matrix(df: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    """Numeric features + position one-hot, in a stable column order. Missing
    feature columns are added as NaN (HGB handles them); pos one-hot from pos_group."""
    num = pd.DataFrame(index=df.index)
    for c in features:
        num[c] = pd.to_numeric(df[c], errors="coerce") if c in df.columns else np.nan
    return pd.concat([num, position_onehot(df["pos_group"])], axis=1)


def _club_row_for(matcher: Matcher, club_by_norm: dict[str, pd.Series],
                  name: str) -> pd.Series | None:
    """Resolve an observed-VAEP player name to that season's club-stats row."""
    target, _score, method = matcher.match(name)
    if target is None:
        return None
    return club_by_norm.get(normalize(target))


def build_training_table(observed: pd.DataFrame, club_feats: pd.DataFrame,
                         min_minutes: float = MIN_TOURNAMENT_MINUTES) -> pd.DataFrame:
    """Join observed tournament VAEP to each player's preceding club-season stats.

    For each tournament, restrict club_feats to the preceding season, fuzzy-match the
    observed players (StatsBomb names) to that season's FBref players, and attach the
    club features. Players without a Tier-1 club-season match are dropped (no
    features). One row per matched (player, tournament)."""
    obs = observed[observed["minutes"].fillna(0) >= min_minutes].copy()
    out_rows = []
    for tournament, season in TOURNAMENT_SEASON.items():
        season_club = club_feats[club_feats["season"] == season]
        if season_club.empty:
            continue
        # one club row per player-name in this season (the max-minutes club if a
        # mid-season transfer split the player across two clubs)
        sc = (season_club.sort_values("minutes_90s", ascending=False)
                         .drop_duplicates("player_name_norm"))
        club_by_norm = {r["player_name_norm"]: r for _, r in sc.iterrows()}
        matcher = Matcher(choices=list(sc["player"]))
        for _, o in obs[obs["tournament"] == tournament].iterrows():
            crow = _club_row_for(matcher, club_by_norm, o["player_name"])
            if crow is None:
                continue
            row = {"tournament": tournament, "season": season,
                   "player_name": o["player_name"], TARGET: o[TARGET],
                   "tournament_minutes": o["minutes"], "pos_group": crow["pos_group"]}
            for c in FEATURES:
                row[c] = crow.get(c, np.nan)
            out_rows.append(row)
    return pd.DataFrame(out_rows)


def train_model(table: pd.DataFrame, features: list[str] = FEATURES,
                exclude_tournament: str | None = None) -> HistGradientBoostingRegressor:
    """Fit the shallow gradient-boosting regressor. `exclude_tournament` drops that
    tournament's rows — the hook the Stage-3 nested CV uses to refit per fold."""
    t = table[table["tournament"] != exclude_tournament] if exclude_tournament else table
    X = feature_matrix(t, features)
    # Heavily regularized depth-1 stumps. Club form translates only weakly to
    # tournament VAEP (PLAN "Known Challenges"); a leave-one-tournament-out sweep
    # showed anything deeper overfits to a negative held-out R2, while this stump
    # ensemble lands a slightly-positive R2 that beats the position-mean baseline.
    # Additive single-feature tilt, no interactions — honest given the thin signal.
    model = HistGradientBoostingRegressor(
        max_depth=1, max_iter=80, learning_rate=0.05,
        min_samples_leaf=80, l2_regularization=5.0, random_state=0)
    model.fit(X.to_numpy(), t[TARGET].to_numpy())
    return model


def leave_one_tournament_out(table: pd.DataFrame,
                             features: list[str] = FEATURES) -> pd.DataFrame:
    """Predict each tournament from a model blind to it. Returns the table with a
    `vaep_per90_pred` column — the honest observed-vs-predicted for /method."""
    preds = pd.Series(np.nan, index=table.index)
    for tournament in table["tournament"].unique():
        model = train_model(table, features, exclude_tournament=tournament)
        mask = table["tournament"] == tournament
        preds[mask] = model.predict(feature_matrix(table[mask], features).to_numpy())
    return table.assign(vaep_per90_pred=preds)


def report(scored: pd.DataFrame) -> None:
    """Print honest CV metrics: overall R²/MAE and per-position MAE."""
    y, yhat = scored[TARGET].to_numpy(), scored["vaep_per90_pred"].to_numpy()
    print(f"leave-one-tournament-out: n={len(scored)}  "
          f"R2={r2_score(y, yhat):.3f}  MAE={mean_absolute_error(y, yhat):.4f}")
    print("  per tournament:")
    for t, g in scored.groupby("tournament"):
        print(f"    {t:18s} n={len(g):4d}  R2={r2_score(g[TARGET], g['vaep_per90_pred']):.3f}"
              f"  MAE={mean_absolute_error(g[TARGET], g['vaep_per90_pred']):.4f}")
    print("  per position (MAE):")
    for p, g in scored.groupby("pos_group"):
        print(f"    {p:3s} n={len(g):4d}  MAE={mean_absolute_error(g[TARGET], g['vaep_per90_pred']):.4f}")


def predict_live(model: HistGradientBoostingRegressor, squad_csv: Path,
                 club_feats: pd.DataFrame, features: list[str] = FEATURES,
                 season: str = LIVE_SEASON) -> pd.DataFrame:
    """Predicted VAEP for a squad's players from their `season` club stats. Defaults
    to the live 2025/26 season; the index builder (§3) and nested CV (§4.5) pass each
    backtest tournament's preceding season instead."""
    squad = pd.read_csv(squad_csv)
    season_club = club_feats[club_feats["season"] == season]
    sc = (season_club.sort_values("minutes_90s", ascending=False)
                     .drop_duplicates("player_name_norm"))
    club_by_norm = {r["player_name_norm"]: r for _, r in sc.iterrows()}
    matcher = Matcher(choices=list(sc["player"]))
    rows = []
    for _, p in squad.iterrows():
        crow = _club_row_for(matcher, club_by_norm, p["player_name"])
        if crow is None:
            continue
        rows.append({"country_code": p["country_code"], "player_name": p["player_name"],
                     "pos_group": crow["pos_group"],
                     **{c: crow.get(c, np.nan) for c in features}})
    live = pd.DataFrame(rows)
    if live.empty:
        return live
    live["vaep_per90_pred"] = model.predict(feature_matrix(live, features).to_numpy())
    return live


def main() -> None:
    observed = pd.read_csv(PROC / "vaep_observed.csv")
    if "tournament" not in observed.columns:
        raise SystemExit("vaep_observed.csv has no `tournament` column — rerun "
                         "`python3 -m src.features.vaep` first (PLAN §2.2 needs the grain)")
    club_feats = load_player_features()
    table = build_training_table(observed, club_feats)
    print(f"training rows (matched player-tournaments): {len(table)}")
    scored = leave_one_tournament_out(table)
    report(scored)

    model = train_model(table)
    live = predict_live(model, REPO / "data" / "raw" / "squads_2026.csv", club_feats)
    PROC.mkdir(parents=True, exist_ok=True)
    out = PROC / "predicted_vaep.csv"
    live.to_csv(out, index=False)
    print(f"\npredicted VAEP for {len(live)} of 2026 squad players -> {out.relative_to(REPO)}")


if __name__ == "__main__":
    main()

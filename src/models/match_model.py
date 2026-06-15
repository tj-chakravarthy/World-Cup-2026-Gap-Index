"""Production match model — calibrated W/D/L for 2026 fixtures (PLAN.md §4).

Trains on ALL backtest fixtures (no held-out split — this is the live model, not the
§4.5 evaluation) and applies to the 2026 group fixtures. Feature set is Elo + market
value: the ablation's best, and predicted-VAEP adds nothing over it (deviations.md), so
the honest live model leans on Elo+market. The squad indices still exist for display
(radar/gap), they just don't earn a place in the predictor.

Inference is order-invariant (§4.1): each fixture is scored in both team orderings and
averaged, so team1/team2 assignment can't tilt the prediction. Output is one calibrated
3-way distribution per fixture, the input the scoreline model and the Monte-Carlo sim
build on. pandas + sklearn.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from src.features.indices import INDEX_COLS, build_indices
from src.features.player_features import load_player_features
from src.features.predicted_vaep import build_training_table, train_model
from src.models.evaluate import FEATURE_GROUPS, LOGIT_C, diff_cols
from src.models.match_dataset import build_match_dataset

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"
PROC = REPO / "data" / "processed"

PRODUCTION_COLS = FEATURE_GROUPS["+ market value"]  # ELO + MKT (the live feature set)
LIVE = "world_cup_2026"


def make_classifier(C: float = LOGIT_C):
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                         LogisticRegression(max_iter=2000, C=C))


def train_production(dataset: pd.DataFrame, cols: list[str]):
    """Fit on the full backtest dataset (swap-augmented), no held-out split."""
    clf = make_classifier()
    clf.fit(dataset[diff_cols(cols)].to_numpy(), dataset["target"].to_numpy())
    return clf


def fixture_index_diffs(fixtures: pd.DataFrame, indices: pd.DataFrame,
                        cols: list[str]) -> tuple[pd.DataFrame, np.ndarray]:
    """For each 2026 group fixture, the team1-team2 index differentials. Returns the
    fixture rows (home as team1) and the diff matrix."""
    idx = indices[indices["tournament"] == LIVE].set_index("country_code")
    fg = fixtures[(fixtures["stage"] == "group")
                  & fixtures["home_code"].isin(idx.index)
                  & fixtures["away_code"].isin(idx.index)].copy()
    diffs = np.column_stack([idx.loc[fg["home_code"], c].to_numpy()
                             - idx.loc[fg["away_code"], c].to_numpy() for c in cols])
    return fg.reset_index(drop=True), diffs


def predict_wdl(clf, diffs: np.ndarray) -> np.ndarray:
    """Order-invariant 3-way distribution per fixture: score (team1-team2) diffs and the
    swapped (negated) diffs, average so ordering can't bias the call. Columns are
    [team1 win, draw, team2 win]."""
    cls = clf.classes_.astype(int)
    def aligned(d):
        p = clf.predict_proba(d)
        full = np.zeros((len(d), 3))
        full[:, cls] = p
        return full
    p = aligned(diffs)
    psw = aligned(-diffs)  # swapped orientation: its team1 is our team2
    out = np.empty_like(p)
    out[:, 0] = 0.5 * (p[:, 0] + psw[:, 2])
    out[:, 1] = 0.5 * (p[:, 1] + psw[:, 1])
    out[:, 2] = 0.5 * (p[:, 2] + psw[:, 0])
    return out


def predict_2026(indices: pd.DataFrame, results: pd.DataFrame, fixtures: pd.DataFrame,
                 cols: list[str] = PRODUCTION_COLS) -> pd.DataFrame:
    """Train the production model on the backtest fixtures, predict the 2026 group
    fixtures' W/D/L. Already-played fixtures keep their real result alongside the model
    call (evidence, never a training target here)."""
    dataset = build_match_dataset(indices, results)
    clf = train_production(dataset, cols)
    fg, diffs = fixture_index_diffs(fixtures, indices, cols)
    probs = predict_wdl(clf, diffs)
    out = fg[["fixture_id", "group", "home_team", "away_team", "home_code", "away_code",
              "played", "home_score", "away_score"]].copy()
    out["p_home"], out["p_draw"], out["p_away"] = probs[:, 0], probs[:, 1], probs[:, 2]
    return out


def main() -> None:
    club_feats = load_player_features()
    observed = pd.read_csv(PROC / "vaep_observed.csv")
    indices = build_indices(model=train_model(build_training_table(observed, club_feats)),
                            club_feats=club_feats)
    results = pd.read_csv(RAW / "match_results.csv")
    fixtures = pd.read_csv(RAW / "fixtures_2026.csv")
    preds = predict_2026(indices, results, fixtures)
    PROC.mkdir(parents=True, exist_ok=True)
    out = PROC / "predictions_2026_wdl.csv"
    preds.to_csv(out, index=False)
    print(f"2026 group-fixture W/D/L: {len(preds)} fixtures -> {out.relative_to(REPO)}")
    # sanity: biggest home favourites
    top = preds.assign(fav=preds[["p_home", "p_away"]].max(axis=1)).nlargest(8, "fav")
    for r in top.itertuples():
        s = "home" if r.p_home >= r.p_away else "away"
        print(f"  {r.home_team} v {r.away_team}: "
              f"{r.p_home:.2f}/{r.p_draw:.2f}/{r.p_away:.2f} ({s} fav)")


if __name__ == "__main__":
    main()

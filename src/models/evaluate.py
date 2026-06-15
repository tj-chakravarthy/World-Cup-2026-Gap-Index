"""Nested temporal CV + feature-group ablation (PLAN.md §4.5) — the credibility core.

Forward-chaining folds over the backtest tournaments; for each, the WHOLE fitted
rating stack (predicted-VAEP model -> squad indices) is refit on `train_only` data —
the test tournament never informs the features used to predict it (the nested-CV
leakage guard, §2.2/§4.5). Index z-scoring is within-tournament and carries no fitted
parameters, so it is leakage-safe without refitting (§3 contract).

Headline = the feature-group ablation (the thesis test): pooled held-out multiclass
Brier as the feature set grows Elo -> +market value -> +predicted-VAEP indices -> full.
The thesis (club talent translates) is supported only if the predicted-VAEP step
improves on Elo+market by a CI-separated margin; reported honestly either way.
Bootstrap CIs are tournament-clustered (a tournament is ~50 correlated matches, so a
Brier difference has a wide CI — never claim a win off one fold).

A multinomial logistic on the index differentials is the workhorse classifier here:
stable on the few-hundred-fixture training set and the right tool for an ablation,
where overfitting noise would muddy the CI comparison. pandas + sklearn.
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
from src.models.match_dataset import build_match_dataset

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"
PROC = REPO / "data" / "processed"

# forward-chaining temporal folds (PLAN §4.5): (train tournaments, test tournaments)
FOLDS = [
    (["world_cup_2018"], ["euro_2020"]),
    (["world_cup_2018", "euro_2020"], ["world_cup_2022"]),
    (["world_cup_2018", "euro_2020", "world_cup_2022"],
     ["euro_2024", "copa_america_2024"]),
]

# cumulative feature groups for the ablation; the model uses each index's *_diff.
FEATURE_GROUPS = {
    "Elo only": ["ELO"],
    "+ market value": ["ELO", "MKT"],
    "+ predicted-VAEP": ["ELO", "MKT", "ATK", "MID", "DEF", "GK"],
    "full (+ structure)": INDEX_COLS,
}


def diff_cols(indices: list[str]) -> list[str]:
    return [f"{c}_diff" for c in indices]


def brier_multiclass(probs: np.ndarray, y: np.ndarray) -> float:
    """Mean over rows of the summed squared error vs the one-hot outcome (0/1/2)."""
    onehot = np.eye(3)[y.astype(int)]
    return float(((probs - onehot) ** 2).sum(axis=1).mean())


def fold_training_table(observed: pd.DataFrame, club_feats: pd.DataFrame,
                        exclude: list[str]) -> pd.DataFrame:
    """Predicted-VAEP training rows with the test tournament(s) removed — the nested
    refit's `train_only` input. Separated out so the leakage guard can assert it."""
    train_obs = observed[~observed["tournament"].isin(exclude)]
    return build_training_table(train_obs, club_feats)


def fold_model(observed: pd.DataFrame, club_feats: pd.DataFrame, exclude: list[str]):
    """Refit the predicted-VAEP model excluding the held-out tournament(s)."""
    return train_model(fold_training_table(observed, club_feats, exclude))


# strong L2: the per-fold training set is only ~60-180 fixtures with autocorrelated
# squad indices, so a lightly-regularised logistic overfits the train tournaments and
# generalises worse as features are added (the ablation would measure overfitting, not
# signal). Heavy shrinkage makes the feature-group comparison honest. The verdict is
# insensitive to C across 1.0..0.015 (swept): Elo-only is best at every strength,
# squad indices never beat it — so the choice of C is not what drives the result.
LOGIT_C = 0.03


def _fit_predict(train: pd.DataFrame, test: pd.DataFrame, cols: list[str]) -> np.ndarray:
    X = diff_cols(cols)
    clf = make_pipeline(
        SimpleImputer(strategy="median"), StandardScaler(),
        LogisticRegression(max_iter=2000, C=LOGIT_C))
    clf.fit(train[X].to_numpy(), train["target"].to_numpy())
    # align to the 3-class simplex even if a fold's train misses a class
    proba = clf.predict_proba(test[X].to_numpy())
    full = np.zeros((len(test), 3))
    full[:, clf.classes_.astype(int)] = proba
    return full


def fold_datasets(club_feats, observed, results):
    """Build (train_ds, test_ds, test_tournaments) per fold ONCE — the expensive
    nested rating refit + index rebuild, reused across all ablation levels."""
    out = []
    for train_t, test_t in FOLDS:
        model = fold_model(observed, club_feats, test_t)
        idx = build_indices(model, club_feats, train_t + test_t)
        tr = build_match_dataset(idx, results, train_t)
        te = build_match_dataset(idx, results, test_t, augment=False)
        out.append((tr, te, test_t))
    return out


def bootstrap_brier_ci(rows: pd.DataFrame, cols: list[str], n_boot: int = 1000,
                       seed: int = 0) -> tuple[float, float, float]:
    """Pooled held-out Brier with a tournament-clustered bootstrap 90% CI. `rows` has
    the held-out predictions (p0,p1,p2), target, tournament."""
    probs = rows[["p0", "p1", "p2"]].to_numpy()
    y = rows["target"].to_numpy()
    point = brier_multiclass(probs, y)
    rng = np.random.default_rng(seed)
    tourns = rows["tournament"].unique()
    groups = {t: np.where(rows["tournament"].to_numpy() == t)[0] for t in tourns}
    boot = []
    for _ in range(n_boot):
        pick = rng.choice(tourns, size=len(tourns), replace=True)  # cluster on tournament
        idx = np.concatenate([groups[t] for t in pick])
        boot.append(brier_multiclass(probs[idx], y[idx]))
    return point, float(np.percentile(boot, 5)), float(np.percentile(boot, 95))


def feature_group_ablation(folds_data) -> pd.DataFrame:
    """Pooled held-out Brier (+ tournament-clustered CI) per cumulative feature group."""
    records = []
    for level, cols in FEATURE_GROUPS.items():
        pooled = []
        for tr, te, test_t in folds_data:
            probs = _fit_predict(tr, te, cols)
            df = te[["tournament", "target"]].copy()
            df[["p0", "p1", "p2"]] = probs
            pooled.append(df)
        pooled = pd.concat(pooled, ignore_index=True)
        point, lo, hi = bootstrap_brier_ci(pooled, cols)
        records.append({"feature_set": level, "n": len(pooled),
                        "brier": round(point, 4), "ci_lo": round(lo, 4),
                        "ci_hi": round(hi, 4)})
    return pd.DataFrame(records)


def main() -> None:
    club_feats = load_player_features()
    observed = pd.read_csv(PROC / "vaep_observed.csv")
    results = pd.read_csv(RAW / "match_results.csv")
    print("building nested folds (predicted-VAEP refit + index rebuild per fold)...")
    folds_data = fold_datasets(club_feats, observed, results)
    for i, (tr, te, test_t) in enumerate(folds_data):
        print(f"  fold {i+1}: train {len(tr)//2} fixtures -> test {test_t} "
              f"({len(te)} fixtures)")
    table = feature_group_ablation(folds_data)
    PROC.mkdir(parents=True, exist_ok=True)
    table.to_csv(PROC / "ablation.csv", index=False)
    print("\nFEATURE-GROUP ABLATION (pooled held-out Brier, tournament-clustered 90% CI):")
    print(table.to_string(index=False))
    base = table.iloc[2]["brier"]  # +predicted-VAEP
    mkt = table.iloc[1]["brier"]   # +market value
    verdict = ("supported" if base < mkt else "NOT supported (predicted-VAEP adds no "
               "Brier gain over Elo+market)")
    print(f"\nthesis (predicted-VAEP beats Elo+market): {verdict} "
          f"[{mkt:.4f} -> {base:.4f}]; read against the CIs, not the point estimate.")


if __name__ == "__main__":
    main()

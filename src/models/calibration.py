"""Calibration assessment (PLAN.md §4.4 + the pre-registered success criterion).

The project's pre-registered deliverable is a *calibrated* match model — reliability
close to the diagonal, low ECE — explicitly decoupled from beating Elo or the market.
This measures it on the leave-one-tournament-out held-out predictions (each tournament
predicted by a model blind to it, so the calibration number is honest, not in-sample
and not recalibrated on the same data). The live W/D/L model is Elo + market value, the
ablation's best feature set (predicted-VAEP adds nothing — see deviations.md).

ECE is top-label (bin by the predicted-class confidence, compare to the realised
accuracy in the bin). The per-outcome table is the reliability diagram's data (one
curve per W/D/L). Isotonic recalibration (PLAN §4.4) is a production refinement layered
on top; the raw held-out number here is the honest baseline. pandas + sklearn.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.features.player_features import load_player_features
from src.models.evaluate import (FEATURE_GROUPS, brier_multiclass, fold_datasets,
                                  pooled_predictions)

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"
PROC = REPO / "data" / "processed"

PRODUCTION_FEATURES = FEATURE_GROUPS["+ market value"]  # the live W/D/L model
_OUTCOME = {0: "team1 win", 1: "draw", 2: "team2 win"}


def top_label_ece(probs: np.ndarray, y: np.ndarray, n_bins: int = 10) -> float:
    """Expected calibration error on the predicted (argmax) class: the count-weighted
    mean gap between bin confidence and bin accuracy. Pure."""
    conf = probs.max(axis=1)
    correct = (probs.argmax(axis=1) == y).astype(float)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf > lo) & (conf <= hi)
        if m.any():
            ece += m.mean() * abs(correct[m].mean() - conf[m].mean())
    return float(ece)


def reliability_table(probs: np.ndarray, y: np.ndarray, n_bins: int = 10) -> pd.DataFrame:
    """Top-label reliability bins: predicted confidence vs realised accuracy. Pure."""
    conf = probs.max(axis=1)
    correct = (probs.argmax(axis=1) == y).astype(float)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    rows = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf > lo) & (conf <= hi)
        if m.any():
            rows.append({"bin_lo": round(lo, 2), "bin_hi": round(hi, 2),
                         "n": int(m.sum()), "confidence": round(conf[m].mean(), 3),
                         "accuracy": round(correct[m].mean(), 3)})
    return pd.DataFrame(rows)


def per_outcome_reliability(probs: np.ndarray, y: np.ndarray, n_bins: int = 5) -> pd.DataFrame:
    """One-vs-rest reliability per outcome (W/D/L): predicted prob vs observed rate —
    the reliability diagram's curves. Pure."""
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    rows = []
    for k, name in _OUTCOME.items():
        p, hit = probs[:, k], (y == k).astype(float)
        for lo, hi in zip(edges[:-1], edges[1:]):
            m = (p > lo) & (p <= hi)
            if m.any():
                rows.append({"outcome": name, "bin_lo": round(lo, 2),
                             "n": int(m.sum()), "pred_mean": round(p[m].mean(), 3),
                             "obs_rate": round(hit[m].mean(), 3)})
    return pd.DataFrame(rows)


def main() -> None:
    club_feats = load_player_features()
    observed = pd.read_csv(PROC / "vaep_observed.csv")
    results = pd.read_csv(RAW / "match_results.csv")
    print("building nested folds for the production model (Elo + market value)...")
    folds = fold_datasets(club_feats, observed, results)
    pooled = pooled_predictions(folds, PRODUCTION_FEATURES)
    probs = pooled[["p0", "p1", "p2"]].to_numpy()
    y = pooled["target"].to_numpy()

    ece = top_label_ece(probs, y)
    brier = brier_multiclass(probs, y)
    print(f"\nPRODUCTION MATCH MODEL (Elo + market value), held-out n={len(y)}:")
    print(f"  ECE (top-label, 10 bins) = {ece:.3f}   multiclass Brier = {brier:.4f}")
    print("\ntop-label reliability (confidence vs accuracy):")
    print(reliability_table(probs, y).to_string(index=False))
    pod = per_outcome_reliability(probs, y)
    PROC.mkdir(parents=True, exist_ok=True)
    pod.to_csv(PROC / "calibration_reliability.csv", index=False)
    print(f"\nper-outcome reliability -> {(PROC / 'calibration_reliability.csv').relative_to(REPO)}")
    verdict = ("well calibrated" if ece < 0.06 else
               "moderately calibrated" if ece < 0.12 else "poorly calibrated")
    print(f"\nverdict: {verdict} (ECE {ece:.3f}); the pre-registered success metric is "
          f"calibration, not beating Elo/market.")


if __name__ == "__main__":
    main()

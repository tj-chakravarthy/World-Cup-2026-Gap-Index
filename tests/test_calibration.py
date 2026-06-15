"""Calibration metrics (PLAN.md §4.4 / pre-registered success criterion)."""

import numpy as np
import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("sklearn")

from src.models.calibration import (  # noqa: E402
    per_outcome_reliability, reliability_table, top_label_ece)


def test_ece_zero_when_confidence_matches_accuracy():
    # 10 rows, all predict class 0 at confidence 0.7; exactly 7 are class 0
    probs = np.tile([0.7, 0.2, 0.1], (10, 1))
    y = np.array([0] * 7 + [1] * 3)
    assert top_label_ece(probs, y, n_bins=10) == pytest.approx(0.0, abs=1e-9)


def test_ece_positive_when_overconfident():
    # predict class 0 at 0.9 but only half are right -> gap ~0.4
    probs = np.tile([0.9, 0.05, 0.05], (10, 1))
    y = np.array([0] * 5 + [1] * 5)
    assert top_label_ece(probs, y, n_bins=10) == pytest.approx(0.4, abs=1e-9)


def test_reliability_table_bins_and_counts():
    probs = np.tile([0.7, 0.2, 0.1], (10, 1))
    y = np.array([0] * 7 + [1] * 3)
    tbl = reliability_table(probs, y, n_bins=10)
    assert tbl["n"].sum() == 10
    row = tbl.iloc[0]
    assert row["confidence"] == pytest.approx(0.7)
    assert row["accuracy"] == pytest.approx(0.7)


def test_per_outcome_reliability_covers_three_outcomes():
    rng = np.random.default_rng(0)
    probs = rng.dirichlet([1, 1, 1], size=60)
    y = rng.integers(0, 3, size=60)
    pod = per_outcome_reliability(probs, y, n_bins=5)
    assert set(pod["outcome"]) == {"team1 win", "draw", "team2 win"}

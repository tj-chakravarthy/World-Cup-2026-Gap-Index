"""Thin Dixon-Coles goals model (member C, PLAN.md §4.2 / Stage 0).

Synthetic-league tests: properties that must hold regardless of the fit's exact
numbers — stronger teams rate higher and win more, the scoreline grid is a
proper distribution, neutral prediction is order-invariant, and the tau
correction actually moves the low-score cells.
"""

import dataclasses

import pytest

pytest.importorskip("scipy")

import numpy as np  # noqa: E402

from src.models.dixon_coles import fit  # noqa: E402


def _league(n: int = 40) -> list[tuple]:
    """STRONG > MID > WEAK by construction, recent dates so decay ~ 1, neutral."""
    d = "2025-01-01"
    rows = []
    for _ in range(n):
        rows += [
            (d, "STRONG", "WEAK", 3, 0, True),
            (d, "MID", "WEAK", 2, 0, True),
            (d, "STRONG", "MID", 2, 1, True),
        ]
    return rows


def test_stronger_team_rates_higher_and_wins_more():
    m = fit(_league(), min_date="2020-01-01")
    assert m.attack["STRONG"] > m.attack["MID"] > m.attack["WEAK"]
    w = m.predict("STRONG", "WEAK")["wdl"]
    assert w["team1"] > w["team2"]


def test_wdl_sums_to_one_and_in_unit_interval():
    m = fit(_league(), min_date="2020-01-01")
    w = m.predict("STRONG", "MID")["wdl"]
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert all(0.0 <= v <= 1.0 for v in w.values())


def test_scoreline_matrix_is_a_distribution():
    m = fit(_league(), min_date="2020-01-01")
    grid = m.scoreline_matrix("STRONG", "WEAK")
    assert abs(grid.sum() - 1.0) < 1e-9
    assert (grid >= 0).all()


def test_neutral_prediction_is_order_invariant():
    m = fit(_league(), min_date="2020-01-01")
    a = m.predict("STRONG", "WEAK")["wdl"]
    b = m.predict("WEAK", "STRONG")["wdl"]
    assert a["team1"] == pytest.approx(b["team2"])
    assert a["draw"] == pytest.approx(b["draw"])


def test_rho_moves_low_score_cells():
    m = fit(_league(), min_date="2020-01-01")
    assert m.rho != 0.0
    m0 = dataclasses.replace(m, rho=0.0)
    grid = m.scoreline_matrix("MID", "WEAK")
    grid0 = m0.scoreline_matrix("MID", "WEAK")
    assert not np.isclose(grid[0, 0], grid0[0, 0])

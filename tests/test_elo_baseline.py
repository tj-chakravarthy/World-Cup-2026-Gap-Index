"""Elo-sigmoid baseline (member E, PLAN.md §4.2). Pure arithmetic, no deps."""

import pytest

from src.models.elo_baseline import elo_wdl, win_prob


def test_win_prob_monotonic_and_symmetric():
    assert win_prob(2000, 1600) > win_prob(1800, 1600) > 0.5
    assert win_prob(1700, 1700) == pytest.approx(0.5)
    assert win_prob(1600, 2000) == pytest.approx(1.0 - win_prob(2000, 1600))


def test_wdl_sums_to_one_and_in_unit_interval():
    for e1, e2 in [(2000, 1500), (1700, 1700), (1600, 1900)]:
        w = elo_wdl(e1, e2)
        assert abs(sum(w.values()) - 1.0) < 1e-12
        assert all(0.0 <= v <= 1.0 for v in w.values())


def test_equal_elo_is_symmetric_with_base_draw():
    w = elo_wdl(1800, 1800, base_draw=0.231)
    assert w["team1"] == pytest.approx(w["team2"])
    assert w["draw"] == pytest.approx(0.231)


def test_draw_share_shrinks_with_rating_gap():
    assert elo_wdl(2200, 1500)["draw"] < elo_wdl(1800, 1750)["draw"]

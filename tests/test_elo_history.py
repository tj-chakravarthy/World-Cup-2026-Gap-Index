"""National Elo computation (PLAN.md §1.8 / §4.5). Stdlib only, CI-safe."""

from src.features.elo_history import (expected, gd_multiplier, match_weight,
                                      run_elo, snapshot)


def test_match_weight_by_importance():
    assert match_weight("FIFA World Cup") == 60
    assert match_weight("FIFA World Cup qualification") == 40
    assert match_weight("UEFA Euro") == 50
    assert match_weight("UEFA Nations League") == 40
    assert match_weight("Friendly") == 20
    assert match_weight("Gulf Cup") == 30


def test_gd_multiplier():
    assert gd_multiplier(0) == 1.0 and gd_multiplier(1) == 1.0
    assert gd_multiplier(2) == 1.5
    assert gd_multiplier(4) == (11 + 4) / 8.0


def test_expected_home_advantage():
    assert expected(1500, 1500, 0) == 0.5
    assert expected(1500, 1500, 100) > 0.5


def test_run_elo_zero_sum_and_direction():
    # equal teams, neutral friendly, home wins 1-0: K=20, G=1, E=0.5 -> delta=10
    ratings, _ = run_elo([("2020-01-01", "A", "B", 1, 0, True, "Friendly")])
    assert round(ratings["A"], 1) == 1510.0
    assert round(ratings["B"], 1) == 1490.0
    assert round(ratings["A"] + ratings["B"], 1) == 3000.0  # zero-sum


def test_snapshot_as_of_is_point_in_time():
    _, hist = run_elo([("2019-06-01", "A", "B", 2, 0, True, "Friendly"),
                       ("2021-06-01", "A", "B", 0, 1, True, "Friendly")])
    s2020 = snapshot(hist, "2020-01-01")
    s2022 = snapshot(hist, "2022-01-01")
    assert s2020["A"] > 1500              # up after the first win
    assert s2022["A"] < s2020["A"]        # later loss pulled it back

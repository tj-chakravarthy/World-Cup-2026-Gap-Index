"""Composite player score (PLAN.md §2.3). Pure-function coverage."""

import math

import pytest

pd = pytest.importorskip("pandas")

from src.features.player_scores import (  # noqa: E402
    W_MARKET, W_OBS, W_PRED, _tm_pos_group, composite, join_market_value,
    percentile_within_position)


def test_tm_pos_group_maps_strings():
    assert _tm_pos_group("Goalkeeper") == "GK"
    assert _tm_pos_group("Centre-Back") == "DF"
    assert _tm_pos_group("Attacking Midfield") == "MF"
    assert _tm_pos_group("Centre-Forward") == "FW"


def test_join_market_value_disambiguates_name_collision_by_position():
    # two BRA players fold to the same key: a GK and a MF with different values
    squads = pd.DataFrame({
        "country_code": ["BRA", "BRA"],
        "player_name": ["Ederson", "Éderson"], "position": ["GK", "MF"]})
    tm = {"BRA": [
        {"player_name": "Ederson", "position": "Goalkeeper", "market_value_eur": 30_000_000},
        {"player_name": "Éderson", "position": "Central Midfield", "market_value_eur": 50_000_000},
    ]}
    mv, unmatched = join_market_value(squads, tm)
    assert mv.iloc[0] == 30_000_000   # the GK gets the keeper's value, not the MF's
    assert mv.iloc[1] == 50_000_000
    assert unmatched == []

NAN = float("nan")


def test_composite_is_market_anchored():
    # all three present -> weighted by W_MARKET/W_OBS/W_PRED (sum to 1)
    assert composite(0.5, 0.4, 0.9) == pytest.approx(
        W_MARKET * 0.9 + W_OBS * 0.5 + W_PRED * 0.4)
    # market + observed (no predicted) -> renormalise over the two
    assert composite(0.5, NAN, 0.9) == pytest.approx(
        (W_MARKET * 0.9 + W_OBS * 0.5) / (W_MARKET + W_OBS))
    # market only
    assert composite(NAN, NAN, 0.5) == pytest.approx(0.5)


def test_composite_unrated_without_market_or_observed():
    # predicted VAEP alone (R^2~=0) is not a credible rating -> unrated, not high
    assert math.isnan(composite(NAN, 0.95, NAN))
    assert math.isnan(composite(NAN, NAN, NAN))
    # but a recent observed VAEP alone is enough to rate
    assert composite(0.7, NAN, NAN) == pytest.approx(0.7)


def test_market_value_dominates_a_middling_tournament():
    # a top-market player with one average tournament still rates high (the bug fix)
    assert composite(0.5, 0.8, 1.0) > 0.7


def test_percentile_within_position_groups_and_keeps_nan():
    val = pd.Series([1.0, 2.0, 3.0, 10.0, 20.0, float("nan")])
    pos = pd.Series(["FW", "FW", "FW", "DF", "DF", "DF"])
    pct = percentile_within_position(val, pos)
    # ranked within FW: 1<2<3 -> 1/3, 2/3, 1.0
    assert pct.iloc[0] == pytest.approx(1 / 3)
    assert pct.iloc[2] == pytest.approx(1.0)
    # DF ranked among the two DFs with values; the NaN DF stays NaN
    assert pct.iloc[3] == pytest.approx(0.5)
    assert pct.iloc[4] == pytest.approx(1.0)
    assert pd.isna(pct.iloc[5])

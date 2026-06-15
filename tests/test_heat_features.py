"""Pure-function tests for the heat context (PLAN §1.5).

Heat-index monotonicity, kickoff-hour modulation, roofed damping. pandas isn't
always in the CI dev subset, so importorskip.
"""

import pytest

pytest.importorskip("pandas")
import pandas as pd

from src.features.heat_features import (
    attach_fixture_heat,
    heat_index_c,
    hour_scale,
    kickoff_heat_c,
)


def test_heat_index_monotonic_in_temp():
    # warm range: hotter dry temp -> higher apparent temp
    a = heat_index_c(30, 60)
    b = heat_index_c(35, 60)
    c = heat_index_c(40, 60)
    assert a < b < c


def test_heat_index_monotonic_in_humidity():
    a = heat_index_c(35, 30)
    b = heat_index_c(35, 60)
    c = heat_index_c(35, 90)
    assert a < b < c


def test_heat_index_passthrough_below_threshold():
    # below ~26.7C the regression isn't meaningful -> dry temp returned
    assert heat_index_c(20, 50) == 20
    assert heat_index_c(15, 90) == 15


def test_hour_scale_afternoon_hotter_than_evening():
    assert hour_scale(13) > hour_scale(18) > hour_scale(22)
    assert hour_scale(13) == 1.0  # noon at the daily high


def test_kickoff_heat_afternoon_hotter_than_evening():
    afternoon = kickoff_heat_c(35, 55, 15, roofed=0)
    evening = kickoff_heat_c(35, 55, 21, roofed=0)
    assert afternoon > evening


def test_roofed_damps_heat():
    open_v = kickoff_heat_c(35, 55, 15, roofed=0)
    roofed_v = kickoff_heat_c(35, 55, 15, roofed=1)
    # roofed pulled toward the indoor baseline -> cooler than open-air
    assert roofed_v < open_v


def test_attach_fixture_heat_uses_local_hour_and_roof():
    fixtures = pd.DataFrame({
        "fixture_id": ["F1", "F2"],
        # 19:00Z at Mexico City (-6) = 13:00 local (afternoon);
        # 02:00Z next day = 20:00 local prior day (evening)
        "kickoff_utc": ["2026-06-11T19:00:00Z", "2026-06-12T02:00:00Z"],
        "venue_key": ["V1", "V1"],
    })
    venues = pd.DataFrame({
        "venue_key": ["V1"],
        "tz": ["America/Mexico_City"],
        "roofed": [0],
        "climate_high_c": [34],
        "climate_rh_pct": [55],
    })
    out = attach_fixture_heat(fixtures, venues).set_index("fixture_id")
    assert out.loc["F1", "local_hour"] == 13
    assert out.loc["F2", "local_hour"] == 20
    # afternoon kickoff hotter than the evening one at the same venue
    assert out.loc["F1", "heat_index_c"] > out.loc["F2", "heat_index_c"]

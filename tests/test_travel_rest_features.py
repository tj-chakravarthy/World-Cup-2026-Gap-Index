"""Pure-function tests for the travel/rest context builder (PLAN §1.5).

No network, no coords from disk — small constructed frames. pandas isn't always
in the CI dev subset, so importorskip rather than break collection.
"""

import pytest

pytest.importorskip("pandas")
import pandas as pd

from src.features.travel_rest_features import (
    DEFAULT_FIRST_REST_DAYS,
    build_travel_rest,
    haversine_km,
    join_venue_coords,
)


def test_haversine_known_distance():
    # JFK -> LAX, published great-circle ~3983 km; allow a small tolerance.
    d = haversine_km(40.6413, -73.7781, 33.9416, -118.4085)
    assert abs(d - 3983.0) < 30.0
    # identical points -> exactly zero
    assert haversine_km(19.303, -99.15, 19.303, -99.15) == 0.0


def _two_match_fixtures():
    # one team (AAA) plays two matches 4 days apart at two venues; the opponents
    # differ. Coords: venue1 ~ Mexico City, venue2 ~ Toronto.
    return pd.DataFrame({
        "fixture_id": ["F1", "F2"],
        "kickoff_utc": ["2026-06-11T19:00:00Z", "2026-06-15T19:00:00Z"],
        "home_code": ["AAA", "AAA"],
        "away_code": ["BBB", "CCC"],
        "home_lat": [19.303, 43.633],
        "home_lon": [-99.15, -79.418],
        "home_tz": ["America/Mexico_City", "America/Toronto"],
        "home_altitude_m": [2240, 76],
        "away_lat": [19.303, 43.633],
        "away_lon": [-99.15, -79.418],
        "away_tz": ["America/Mexico_City", "America/Toronto"],
        "away_altitude_m": [2240, 76],
    })


def test_rest_days_first_match_default_then_gap():
    out = build_travel_rest(_two_match_fixtures())
    aaa = out[out["team_code"] == "AAA"].sort_values("kickoff_utc")
    assert list(aaa["rest_days"]) == [DEFAULT_FIRST_REST_DAYS, 4.0]


def test_travel_accumulates_and_first_is_zero():
    out = build_travel_rest(_two_match_fixtures())
    aaa = out[out["team_code"] == "AAA"].sort_values("kickoff_utc").reset_index(drop=True)
    assert aaa.loc[0, "travel_km_since_last"] == 0.0
    leg = haversine_km(19.303, -99.15, 43.633, -79.418)
    assert abs(aaa.loc[1, "travel_km_since_last"] - leg) < 1e-6
    # cumulative = sum of legs
    assert abs(aaa.loc[1, "cumulative_travel_km"] - leg) < 1e-6
    assert aaa.loc[0, "context_missing"] == False  # coords present


def test_timezone_shift_and_altitude_passthrough():
    out = build_travel_rest(_two_match_fixtures())
    aaa = out[out["team_code"] == "AAA"].sort_values("kickoff_utc").reset_index(drop=True)
    # Mexico City (-6 in June, no DST) -> Toronto (-4 EDT) = +2h shift
    assert aaa.loc[0, "timezone_shift_hours"] == 0.0
    assert abs(aaa.loc[1, "timezone_shift_hours"] - 2.0) < 1e-6
    assert aaa.loc[0, "venue_altitude_m"] == 2240
    assert aaa.loc[1, "venue_altitude_m"] == 76


def test_rest_diff_is_opponent_relative():
    # BBB's first match is F1 (default rest); AAA's is also F1 (default) -> diff 0.
    out = build_travel_rest(_two_match_fixtures())
    f1 = out[out["fixture_id"] == "F1"].set_index("team_code")
    assert f1.loc["AAA", "rest_diff"] == 0.0
    assert f1.loc["BBB", "rest_diff"] == 0.0


def test_missing_coords_sets_context_missing():
    # no venue columns at all -> historical-style frame; rest still computes,
    # travel/tz/altitude NaN, context_missing True.
    fx = pd.DataFrame({
        "fixture_id": ["H1", "H2"],
        "kickoff_utc": ["2026-06-11T19:00:00Z", "2026-06-14T19:00:00Z"],
        "home_code": ["AAA", "AAA"],
        "away_code": ["BBB", "CCC"],
    })
    out = build_travel_rest(fx)
    aaa = out[out["team_code"] == "AAA"].sort_values("kickoff_utc").reset_index(drop=True)
    assert list(aaa["rest_days"]) == [DEFAULT_FIRST_REST_DAYS, 3.0]
    assert aaa["context_missing"].all()
    assert aaa["travel_km_since_last"].isna().all()
    assert aaa["timezone_shift_hours"].isna().all()


def test_join_venue_coords_attaches_both_sides():
    fixtures = pd.DataFrame({
        "fixture_id": ["F1"],
        "kickoff_utc": ["2026-06-11T19:00:00Z"],
        "venue_key": ["V1"],
        "home_code": ["AAA"],
        "away_code": ["BBB"],
    })
    venues = pd.DataFrame({
        "venue_key": ["V1"],
        "lat": [19.303], "lon": [-99.15],
        "tz": ["America/Mexico_City"], "altitude_m": [2240],
    })
    out = join_venue_coords(fixtures, venues)
    assert out.loc[0, "home_lat"] == 19.303 and out.loc[0, "away_lat"] == 19.303
    assert out.loc[0, "home_altitude_m"] == 2240

"""Odds-movement builder (src/update/movement.py) — the 'what changed' panel."""

import pytest

pd = pytest.importorskip("pandas")

from src.update.movement import build_movement  # noqa: E402


def _sim(ts, teams):
    return {"generated_at": ts, "teams": teams}


def _fixtures():
    return pd.DataFrame([{"fixture_id": "WC26-M050", "stage": "group",
                          "home_code": "BRA", "away_code": "ARG",
                          "home_score": 0, "away_score": 1}])


def test_build_movement_deltas_sorting_and_resolved():
    before = _sim("T0", [
        {"country_code": "ARG", "p_winner": 0.10, "p_R32": 0.80},
        {"country_code": "BRA", "p_winner": 0.12, "p_R32": 0.90},
        {"country_code": "ESP", "p_winner": 0.11, "p_R32": 0.85},
    ])
    after = _sim("T1", [
        {"country_code": "ARG", "p_winner": 0.13, "p_R32": 0.82},     # +0.03 win, +0.02 adv
        {"country_code": "BRA", "p_winner": 0.09, "p_R32": 0.60},     # -0.03 win, -0.30 adv
        {"country_code": "ESP", "p_winner": 0.1103, "p_R32": 0.8503}, # both < MIN_DELTA
    ])
    mv = build_movement(before, after, {"WC26-M050", "WC26-MUNKNOWN"}, _fixtures())

    assert mv["generated_at"] == "T1" and mv["since"] == "T0"
    # resolved card: only the known, scored fixture; outcome 2 = away (ARG) won
    assert mv["newly_resolved"] == [{"fixture_id": "WC26-M050", "team1": "BRA",
                                     "team2": "ARG", "score": "0-1", "outcome": 2}]
    # title movers: ARG and BRA qualify, ESP (~0) dropped
    tm = {m["country_code"]: m["delta"] for m in mv["title_movers"]}
    assert set(tm) == {"ARG", "BRA"}
    assert tm["ARG"] == pytest.approx(0.03) and tm["BRA"] == pytest.approx(-0.03)
    # advance movers: BRA's -0.30 is the biggest swing, ranked first
    assert mv["advance_movers"][0]["country_code"] == "BRA"
    assert mv["advance_movers"][0]["delta"] == pytest.approx(-0.30)


def test_build_movement_empty_before_has_no_movers():
    after = _sim("T1", [{"country_code": "ARG", "p_winner": 0.13, "p_R32": 0.82}])
    mv = build_movement({}, after, {"WC26-M050"}, _fixtures())
    assert mv["title_movers"] == [] and mv["advance_movers"] == []
    assert mv["since"] is None and len(mv["newly_resolved"]) == 1

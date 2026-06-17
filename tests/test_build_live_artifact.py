"""Live artifact assembly (PLAN.md §6). Pure pieces + schema validity."""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("scipy")

from src.pipeline.build_live_artifact import (build_live, model_inputs,  # noqa: E402
                                              top_scorelines)


def test_top_scorelines_orders_and_formats():
    m = np.zeros((4, 4))
    m[2, 1] = 0.5   # 2-1
    m[1, 1] = 0.3   # 1-1
    m[0, 0] = 0.2   # 0-0
    sc = top_scorelines(m, n=3)
    assert [s["score"] for s in sc] == ["2-1", "1-1", "0-0"]
    assert sc[0]["p"] == pytest.approx(0.5)
    assert all(0.0 <= s["p"] <= 1.0 for s in sc)


class _DummyDC:
    """Empty attack -> build_live takes the base-rate path, so no .rates() call is needed."""
    intercept = 0.0
    attack: dict = {}
    rho = 0.0


def _inputs():
    # kickoff in the future so build_live treats it as upcoming (it excludes post-kickoff)
    future = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    preds = pd.DataFrame([{
        "fixture_id": "WC26-M100", "played": False, "home_code": "ESP", "away_code": "FRA",
        "p_home": 0.45, "p_draw": 0.30, "p_away": 0.25,
    }])
    fixtures = pd.DataFrame([{"fixture_id": "WC26-M100", "stage": "group", "kickoff_utc": future}])
    return preds, fixtures


def test_fresh_marks_nothing_stale():
    preds, fixtures = _inputs()
    art = build_live(preds, fixtures, _DummyDC(), {})
    assert all(s["stale"] is False for s in art["sources"])
    assert art["predictions"][0]["stale"] is False


def test_stale_flags_only_the_fixtures_source():
    # run_all's fixture refresh fell back to cache (fresh=False) -> stale=True
    preds, fixtures = _inputs()
    art = build_live(preds, fixtures, _DummyDC(), {}, stale=True)
    by = {s["name"]: s["stale"] for s in art["sources"]}
    assert by["fixtures"] is True              # the live feed that went stale
    assert by["match_results"] is False        # static, not live-refreshed
    assert by["match_model"] is False          # the fixed pre-tournament bundle
    assert art["predictions"][0]["stale"] is True


def test_build_live_excludes_post_kickoff_fixture():
    # a kicked-off match the feed still marks unplayed (lagging) must NOT be published — it goes
    # to excluded, so the published set stays == the logged set (both pre-kickoff)
    preds = pd.DataFrame([{
        "fixture_id": "WC26-M013", "played": False, "home_code": "KSA", "away_code": "URU",
        "p_home": 0.13, "p_draw": 0.23, "p_away": 0.64,
    }])
    fixtures = pd.DataFrame([{"fixture_id": "WC26-M013", "stage": "group",
                              "kickoff_utc": "2020-01-01T00:00:00Z"}])
    art = build_live(preds, fixtures, _DummyDC(), {})
    assert art["predictions"] == []
    assert "WC26-M013" in art["coverage"]["excluded_played_fixture_ids"]
    assert "WC26-M013" not in art["coverage"]["covered_fixture_ids"]


def test_build_live_rejects_silently_dropped_group_fixture():
    # a group fixture present in fixtures but missing from preds (group_fixture_wdl dropped a pair
    # it couldn't score) must fail loudly, not vanish into pending_undetermined and still validate
    future = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    preds = pd.DataFrame([{
        "fixture_id": "WC26-M100", "played": False, "home_code": "ESP", "away_code": "FRA",
        "p_home": 0.45, "p_draw": 0.30, "p_away": 0.25,
    }])
    fixtures = pd.DataFrame([
        {"fixture_id": "WC26-M100", "stage": "group", "kickoff_utc": future},
        {"fixture_id": "WC26-M101", "stage": "group", "kickoff_utc": future},  # no preds row
    ])
    with pytest.raises(ValueError, match="neither predicted nor excluded"):
        build_live(preds, fixtures, _DummyDC(), {})


def test_build_live_allows_pending_knockout():
    # an unpredicted KNOCKOUT slot (teams TBD) is legitimately pending — the guard must not fire
    future = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    preds = pd.DataFrame([{
        "fixture_id": "WC26-M100", "played": False, "home_code": "ESP", "away_code": "FRA",
        "p_home": 0.45, "p_draw": 0.30, "p_away": 0.25,
    }])
    fixtures = pd.DataFrame([
        {"fixture_id": "WC26-M100", "stage": "group", "kickoff_utc": future},
        {"fixture_id": "WC26-R32-01", "stage": "R32", "kickoff_utc": future},  # teams TBD
    ])
    art = build_live(preds, fixtures, _DummyDC(), {})
    assert "WC26-R32-01" in art["coverage"]["pending_undetermined_fixture_ids"]
    assert "WC26-M100" in art["coverage"]["covered_fixture_ids"]


def test_model_inputs_percentiles_and_shape():
    # the two live-model inputs per group fixture, as within-field percentiles
    idx = pd.DataFrame({
        "tournament": ["world_cup_2026"] * 4,
        "country_code": ["ESP", "FRA", "CPV", "QAT"],
        "ELO": [2.0, 1.0, -1.0, -2.0],
        "MKT": [1.5, 2.0, -1.5, -2.0],
    })
    fixtures = pd.DataFrame([
        {"fixture_id": "WC26-M100", "stage": "group", "home_code": "ESP", "away_code": "CPV"},
        {"fixture_id": "WC26-M200", "stage": "knockout", "home_code": "ESP", "away_code": "FRA"},
        {"fixture_id": "WC26-M300", "stage": "group", "home_code": "ESP", "away_code": "XXX"},
    ])
    mi = model_inputs(idx, fixtures)
    assert mi["metric"] == "percentile_within_field" and mi["field"] == "world_cup_2026"
    # only group fixtures with both codes in the field — knockout + unknown code dropped
    assert set(mi["fixtures"]) == {"WC26-M100"}
    row = mi["fixtures"]["WC26-M100"]
    assert row["team1"] == "ESP" and row["team2"] == "CPV"
    assert row["elo1"] > row["elo2"] and row["mkt1"] > row["mkt2"]
    assert all(0 <= row[k] <= 100 for k in ("elo1", "elo2", "mkt1", "mkt2"))

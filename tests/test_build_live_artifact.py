"""Live artifact assembly (PLAN.md §6). Pure pieces + schema validity."""

import numpy as np
import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("scipy")

from src.pipeline.build_live_artifact import build_live, top_scorelines  # noqa: E402


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
    preds = pd.DataFrame([{
        "fixture_id": "WC26-M100", "played": False, "home_code": "ESP", "away_code": "FRA",
        "p_home": 0.45, "p_draw": 0.30, "p_away": 0.25,
    }])
    fixtures = pd.DataFrame([{"fixture_id": "WC26-M100", "kickoff_utc": "2026-06-20T19:00:00Z"}])
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

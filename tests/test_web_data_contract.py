"""Guard the contract between the published artifacts and the website.

web/public/app.js reads these JSON fields at runtime to render the page. The pipeline
writes them (monte_carlo.write_simulation_json, build_live_artifact). If a pipeline
change drops or renames a field, the live site breaks silently — there's no build step
to catch it. This test pins the fields the site depends on, run on the committed
artifacts in CI. Keep it in sync with app.js (renderMeta / renderForecast / renderFixtures).
"""

import json
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parents[1] / "web" / "public" / "data"

# (key in team object) the forecast heat-table columns + the sort key, see app.js COLS
TEAM_NUMERIC = ("p_R32", "p_R16", "p_QF", "p_SF", "p_final", "p_winner")


def _load(name: str) -> dict:
    p = DATA / name
    if not p.exists():
        pytest.skip(f"{name} not published yet")
    return json.loads(p.read_text())


def test_simulation_json_contract():
    """renderMeta + renderForecast: generated_at, n_sims, teams[].{country_code, p_*}."""
    d = _load("simulation.json")
    assert isinstance(d.get("generated_at"), str) and d["generated_at"]
    assert isinstance(d.get("n_sims"), int) and d["n_sims"] > 0
    teams = d.get("teams")
    assert isinstance(teams, list) and teams, "teams must be a non-empty list"
    for t in teams:
        assert isinstance(t.get("country_code"), str) and t["country_code"]
        missing = [k for k in TEAM_NUMERIC if k not in t]
        assert not missing, f"team {t.get('country_code')} missing {missing}"
        for k in TEAM_NUMERIC:
            assert isinstance(t[k], (int, float)), f"{t['country_code']}.{k} not numeric"
            assert 0.0 <= t[k] <= 1.0, f"{t['country_code']}.{k}={t[k]} not a probability"


def test_predictions_live_json_contract():
    """renderMeta + renderFixtures + renderLive: generated_at, sources[].stale, predictions[].*,
    live_now[].{team1,team2,kickoff_utc}."""
    d = _load("predictions_live.json")
    assert isinstance(d.get("generated_at"), str) and d["generated_at"]
    assert isinstance(d.get("sources"), list)
    assert all("stale" in s for s in d["sources"]), "every source needs a 'stale' flag"
    # renderLive: a list (usually empty); each entry is an in-progress match with no odds
    live_now = d.get("live_now")
    assert isinstance(live_now, list), "live_now must be present (a list, possibly empty)"
    for g in live_now:
        for k in ("team1", "team2", "kickoff_utc"):
            assert isinstance(g.get(k), str), f"live_now entry missing/!str {k}"
    preds = d.get("predictions")
    assert isinstance(preds, list) and preds, "predictions must be a non-empty list"
    for p in preds:
        for k in ("fixture_id", "stage", "kickoff_utc", "team1", "team2"):
            assert k in p and isinstance(p[k], str), f"prediction missing/!str {k}"
        wdl = p.get("wdl")
        assert isinstance(wdl, dict) and {"team1", "draw", "team2"} <= wdl.keys()
        assert all(isinstance(wdl[k], (int, float)) for k in ("team1", "draw", "team2"))
        for s in p.get("scorelines", []):  # optional, but if present: {score, p}
            assert isinstance(s.get("score"), str) and isinstance(s.get("p"), (int, float))


def test_model_inputs_json_contract():
    """renderFixtures/renderTrack tale-of-the-tape: fixtures[fid].{team1,team2,elo*,mkt*}."""
    d = _load("model_inputs.json")
    fx = d.get("fixtures")
    assert isinstance(fx, dict) and fx, "fixtures must be a non-empty map"
    # app.js looks these up by fixture_id (inputs[p.fixture_id]); a re-key would silently drop the tape
    assert all(k.startswith("WC26-M") for k in fx), "fixtures must be keyed by fixture_id"
    for fid, r in fx.items():
        assert isinstance(r.get("team1"), str) and isinstance(r.get("team2"), str)
        for k in ("elo1", "elo2", "mkt1", "mkt2"):
            assert k in r, f"{fid} missing {k}"
            assert r[k] is None or (isinstance(r[k], (int, float)) and 0 <= r[k] <= 100)


def test_movement_json_contract():
    """renderMovement: newly_resolved[], title_movers[], advance_movers[]."""
    d = _load("movement.json")
    assert isinstance(d.get("newly_resolved"), list)
    for c in d["newly_resolved"]:
        assert isinstance(c.get("team1"), str) and isinstance(c.get("team2"), str)
        assert isinstance(c.get("score"), str) and c.get("outcome") in (0, 1, 2)
    for lst in ("title_movers", "advance_movers"):
        assert isinstance(d.get(lst), list)
        for m in d[lst]:
            assert isinstance(m.get("country_code"), str)
            for k in ("before", "after", "delta"):
                assert isinstance(m.get(k), (int, float))


def test_analysis_json_contract():
    """renderGap/renderPlayers/renderCalibration/renderAblation: the bottom analysis tabs."""
    d = _load("analysis.json")
    g = d.get("gap")
    assert isinstance(g, dict) and isinstance(g.get("teams"), list) and g["teams"], "gap teams"
    assert isinstance(g.get("r2"), (int, float))
    for t in g["teams"]:
        for k in ("code", "team", "t"):
            assert isinstance(t.get(k), str), f"gap row missing/!str {k}"
        for k in ("gap", "lo", "hi", "talent"):
            assert isinstance(t.get(k), (int, float)), f"gap row {k}"
    players = d.get("players")
    assert isinstance(players, list) and players, "players list"
    assert isinstance(d.get("players_rated"), int) and d["players_rated"] >= len(players), "rated pool"
    for p in players:
        assert isinstance(p.get("name"), str) and isinstance(p.get("code"), str)
        assert isinstance(p.get("score"), (int, float))
        assert p.get("mv") is None or isinstance(p["mv"], (int, float))
    ab = d.get("ablation")
    assert isinstance(ab, dict) and isinstance(ab.get("rows"), list) and ab["rows"]
    assert any(r.get("set") == "+ market value" for r in ab["rows"]), "the live-model row (badge)"
    for r in ab["rows"]:
        assert isinstance(r.get("set"), str), "ablation row 'set' (app.js renders + branches on it)"
        for k in ("brier", "lo", "hi"):
            assert isinstance(r.get(k), (int, float)), f"ablation {k}"
    cal = d.get("calibration")
    assert isinstance(cal, list) and cal, "calibration points"
    for c in cal:
        assert isinstance(c.get("outcome"), str)
        for k in ("pred", "obs"):
            assert isinstance(c.get(k), (int, float)) and 0 <= c[k] <= 1, f"calibration {k}"


def test_track_record_json_contract():
    """renderTrack: n_receipts, n_audit_rows, n_resolved, resolved[].{teams, p_*, actual, model…}."""
    d = _load("track_record.json")
    for k in ("n_receipts", "n_audit_rows", "n_resolved"):
        assert isinstance(d.get(k), int), k
    resolved = d.get("resolved")
    assert isinstance(resolved, list)
    for g in resolved:
        # app.js sorts the whole track list by kickoff_utc; if it's missing the sort silently breaks
        for k in ("team1", "team2", "actual", "model", "kickoff_utc"):
            assert isinstance(g.get(k), str)
        for k in ("p_team1", "p_draw", "p_team2"):
            assert isinstance(g.get(k), (int, float))
        assert g.get("outcome") in (0, 1, 2)
        assert isinstance(g.get("called"), bool) and isinstance(g.get("exact_hit"), bool)

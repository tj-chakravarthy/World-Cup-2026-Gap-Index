"""Append-only prediction log (src/update/prediction_log.py).

Guards: idempotent append on (model_version, fixture_id); resolve() scores against
the realised result and leaves unplayed fixtures null; track_record's called rate and
multiclass Brier match a hand-computed small set, excluding unresolved rows.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("pyarrow")

from src.update.prediction_log import (  # noqa: E402
    LOG_COLUMNS,
    import_locked_receipts,
    latest_per_fixture,
    load_log,
    log_predictions,
    resolve,
    track_record,
    track_record_artifact,
)

_REPO = Path(__file__).resolve().parents[1]


def test_latest_per_fixture_keeps_standing_prediction():
    # two pre-kickoff logs (different model versions) -> keep the later one (the standing call)
    log = pd.DataFrame({
        "logged_at": ["2026-06-14T10:00:00Z", "2026-06-14T12:00:00Z"],
        "kickoff_utc": ["2026-06-14T19:00:00Z", "2026-06-14T19:00:00Z"],
        "model_source": ["live_full", "live_full"],
        "fixture_id": ["WC26-M050", "WC26-M050"],
        "model_version": ["live@aaa", "live@bbb"],
    })
    out = latest_per_fixture(log)
    assert len(out) == 1
    assert out.iloc[0]["model_version"] == "live@bbb"  # the later pre-kickoff version stands


def test_latest_per_fixture_ignores_post_kickoff_rows():
    # the bug: a lagging score feed re-logs a fixture AFTER kickoff. Score the latest row
    # still strictly before kickoff, never the post-kickoff one (the WC26-M013 case).
    log = pd.DataFrame({
        "logged_at":    ["2026-06-15T15:33:23Z", "2026-06-15T23:15:47Z"],
        "kickoff_utc":  ["2026-06-15T22:00:00Z", "2026-06-15T22:00:00Z"],
        "model_source": ["live_full", "live_full"],
        "fixture_id":   ["WC26-M013", "WC26-M013"],
        "model_version": ["live@2f441c0", "live@nogit"],
    })
    out = latest_per_fixture(log)
    assert len(out) == 1
    assert out.iloc[0]["logged_at"] == "2026-06-15T15:33:23Z"   # the pre-kickoff row
    assert out.iloc[0]["model_version"] == "live@2f441c0"
    # the guarantee, as an invariant: nothing selected was logged at/after its kickoff
    assert bool((out["logged_at"] < out["kickoff_utc"]).all())


def test_latest_per_fixture_drops_fixture_with_only_post_kickoff_rows():
    # no honest pre-kickoff prediction exists -> the fixture is excluded entirely, not scored
    log = pd.DataFrame({
        "logged_at":    ["2026-06-15T23:15:47Z"],
        "kickoff_utc":  ["2026-06-15T22:00:00Z"],
        "model_source": ["live_full"],
        "fixture_id":   ["WC26-M013"],
        "model_version": ["live@nogit"],
    })
    assert latest_per_fixture(log).empty


def _future(days):
    """Kickoff strictly after the wall-clock logged_at log_predictions stamps, so the
    pre-kickoff selector keeps the row (a logged prediction is for a not-yet-played match)."""
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _artifact(model_version="m@v1", preds=None):
    if preds is None:
        preds = [
            {
                "fixture_id": "WC26-M001",
                "stage": "group",
                "kickoff_utc": _future(1),
                "team1": "MEX",
                "team2": "RSA",
                "model_source": "live_full",
                "wdl": {"team1": 0.6, "draw": 0.25, "team2": 0.15},
                "scorelines": [{"score": "2-0", "p": 0.18}, {"score": "1-0", "p": 0.12}],
            },
            {
                "fixture_id": "WC26-M002",
                "stage": "group",
                "kickoff_utc": _future(2),
                "team1": "KOR",
                "team2": "CZE",
                "model_source": "live_full",
                "wdl": {"team1": 0.2, "draw": 0.3, "team2": 0.5},
                "scorelines": [{"score": "0-1", "p": 0.15}, {"score": "1-1", "p": 0.10}],
            },
        ]
    return {"model_version": model_version, "predictions": preds}


def _fixtures(rows):
    cols = ["fixture_id", "home_code", "away_code", "home_score", "away_score", "played"]
    return pd.DataFrame(rows, columns=cols)


def test_log_predictions_idempotent(tmp_path):
    log_path = tmp_path / "log.parquet"
    art = _artifact()

    assert log_predictions(art, log_path) == 2  # both new
    assert log_predictions(art, log_path) == 0  # same key -> nothing

    df = load_log(log_path)
    assert len(df) == 2
    assert list(df.columns) == LOG_COLUMNS
    # top_score is argmax of scorelines
    assert df.set_index("fixture_id").loc["WC26-M001", "top_score"] == "2-0"

    # a different model_version logs fresh even for the same fixtures
    assert log_predictions(_artifact(model_version="m@v2"), log_path) == 2
    assert len(load_log(log_path)) == 4


def test_log_predictions_skips_post_kickoff(tmp_path):
    # a lagging feed can re-include a kicked-off fixture; its post-kickoff row must NOT be logged
    log_path = tmp_path / "log.parquet"
    past = _artifact(preds=[{
        "fixture_id": "WC26-M013", "stage": "group", "kickoff_utc": "2020-01-01T00:00:00Z",
        "team1": "KSA", "team2": "URU", "model_source": "live_full",
        "wdl": {"team1": 0.2, "draw": 0.3, "team2": 0.5},
        "scorelines": [{"score": "0-1", "p": 0.12}]}])
    assert log_predictions(past, log_path) == 0
    assert load_log(log_path).empty
    # a genuinely upcoming fixture (future kickoff) is logged
    assert log_predictions(_artifact(), log_path) == 2


def test_load_log_missing(tmp_path):
    df = load_log(tmp_path / "nope.parquet")
    assert df.empty
    assert list(df.columns) == LOG_COLUMNS


def test_resolve_played_and_unplayed(tmp_path):
    log_path = tmp_path / "log.parquet"
    log_predictions(_artifact(), log_path)
    log = load_log(log_path)

    fixtures = _fixtures(
        [
            # M001: home 2-0 -> outcome 0 (team1 win); p_team1 is argmax -> called True; top "2-0" hits
            ("WC26-M001", "MEX", "RSA", 2, 0, True),
            # M002: not played -> stays null
            ("WC26-M002", "KOR", "CZE", None, None, False),
        ]
    )
    r = resolve(log, fixtures).set_index("fixture_id")

    assert r.loc["WC26-M001", "actual_outcome"] == 0
    assert bool(r.loc["WC26-M001", "called"]) is True
    assert bool(r.loc["WC26-M001", "exact_score_hit"]) is True

    assert pd.isna(r.loc["WC26-M002", "actual_outcome"])
    assert pd.isna(r.loc["WC26-M002", "called"])
    assert pd.isna(r.loc["WC26-M002", "exact_score_hit"])


def test_resolve_handles_string_played_flag(tmp_path):
    # the brittleness: a fixtures feed (or CSV round-trip) encoding played as 'True'/'False'
    # strings. resolve() used `== True`, which silently missed string-encoded played matches;
    # now it goes through played_mask, so a string 'True' still resolves and 'False' stays null
    log_path = tmp_path / "log.parquet"
    log_predictions(_artifact(), log_path)
    log = load_log(log_path)

    fixtures = _fixtures([
        ("WC26-M001", "MEX", "RSA", 2, 0, "True"),     # played (string) -> must resolve
        ("WC26-M002", "KOR", "CZE", "", "", "False"),  # not played (string) -> stays null
    ])
    r = resolve(log, fixtures).set_index("fixture_id")

    assert r.loc["WC26-M001", "actual_outcome"] == 0      # picked up despite the string flag
    assert pd.isna(r.loc["WC26-M002", "actual_outcome"])  # 'False' not treated as played


def test_resolve_exact_score_miss_and_outcomes(tmp_path):
    log_path = tmp_path / "log.parquet"
    log_predictions(_artifact(), log_path)
    log = load_log(log_path)

    fixtures = _fixtures(
        [
            # M002: home 0-1 -> outcome 2 (team2 win); p_team2=0.5 argmax -> called True; top "0-1" hits
            ("WC26-M002", "KOR", "CZE", 0, 1, True),
            # M001: home 1-1 -> outcome 1 (draw); argmax is p_team1 -> called False; top "2-0" != "1-1"
            ("WC26-M001", "MEX", "RSA", 1, 1, True),
        ]
    )
    r = resolve(log, fixtures).set_index("fixture_id")

    assert r.loc["WC26-M002", "actual_outcome"] == 2
    assert bool(r.loc["WC26-M002", "called"]) is True
    assert bool(r.loc["WC26-M002", "exact_score_hit"]) is True

    assert r.loc["WC26-M001", "actual_outcome"] == 1
    assert bool(r.loc["WC26-M001", "called"]) is False
    assert bool(r.loc["WC26-M001", "exact_score_hit"]) is False


def test_track_record_metrics(tmp_path):
    log_path = tmp_path / "log.parquet"
    log_predictions(_artifact(), log_path)
    log = load_log(log_path)

    fixtures = _fixtures(
        [
            ("WC26-M001", "MEX", "RSA", 2, 0, True),  # outcome 0, called True
            ("WC26-M002", "KOR", "CZE", 1, 1, True),  # outcome 1 (draw), argmax team2 -> called False
        ]
    )
    tr = track_record(log, fixtures)

    ov = tr["overall"]
    assert ov["n_logged"] == 2
    assert ov["n_resolved"] == 2
    assert ov["called"]["count"] == 1
    assert ov["called"]["rate"] == pytest.approx(0.5)

    # multiclass Brier, hand-computed:
    # M001 wdl (.6,.25,.15) vs onehot 0: (.6-1)^2+.25^2+.15^2 = .16+.0625+.0225 = .245
    # M002 wdl (.2,.3,.5)  vs onehot 1: .2^2+(.3-1)^2+.5^2 = .04+.49+.25      = .78
    # mean = (.245+.78)/2 = .5125
    assert ov["brier"] == pytest.approx(0.5125)

    assert tr["by_model_source"]["live_full"]["brier"] == pytest.approx(0.5125)


def test_track_record_excludes_unresolved(tmp_path):
    log_path = tmp_path / "log.parquet"
    log_predictions(_artifact(), log_path)
    log = load_log(log_path)

    fixtures = _fixtures(
        [
            ("WC26-M001", "MEX", "RSA", 2, 0, True),  # resolved, called True
            ("WC26-M002", "KOR", "CZE", None, None, False),  # unplayed -> excluded from metrics
        ]
    )
    tr = track_record(log, fixtures)

    ov = tr["overall"]
    assert ov["n_logged"] == 2  # both logged
    assert ov["n_resolved"] == 1  # only the played one scored
    assert ov["called"]["count"] == 1
    assert ov["called"]["rate"] == pytest.approx(1.0)
    # Brier over the single resolved row: .245
    assert ov["brier"] == pytest.approx(0.245)


def test_track_record_artifact_is_receipts_only(tmp_path):
    log_path = tmp_path / "log.parquet"
    log_predictions(_artifact(), log_path)
    log = load_log(log_path)
    fixtures = _fixtures(
        [
            ("WC26-M001", "MEX", "RSA", 2, 0, True),          # played: team1 win, called, exact 2-0
            ("WC26-M002", "KOR", "CZE", None, None, False),   # unplayed -> not a receipt
        ]
    )
    art = track_record_artifact(log, fixtures)
    assert art["n_logged"] == 2 and art["n_resolved"] == 1
    # no scored aggregate is exposed while the sample is tiny (receipts only)
    assert "brier" not in art and "called" not in art
    g = art["resolved"][0]
    assert g["fixture_id"] == "WC26-M001"
    assert g["actual"] == "2-0" and g["outcome"] == 0
    assert g["called"] is True and g["exact_hit"] is True
    assert (g["p_team1"], g["p_draw"], g["p_team2"]) == (0.6, 0.25, 0.15)


def test_log_predictions_honors_explicit_logged_at(tmp_path):
    # the locked backfill: a match already played NOW but locked before its kickoff is a valid
    # pre-kickoff receipt only when logged at the lock instant, not now
    log_path = tmp_path / "log.parquet"
    art = {"model_version": "locked@v1", "predictions": [{
        "fixture_id": "WC26-M005", "stage": "group", "kickoff_utc": "2026-06-14T19:00:00Z",
        "team1": "MEX", "team2": "RSA", "model_source": "locked_minimal",
        "wdl": {"team1": 0.5, "draw": 0.3, "team2": 0.2}, "scorelines": [{"score": "1-0", "p": 0.2}]}]}
    assert log_predictions(art, log_path) == 0  # logged_at=now (post-kickoff) -> dropped
    assert log_predictions(art, log_path, logged_at="2026-06-13T15:12:11Z") == 1  # at lock -> kept
    row = load_log(log_path).iloc[0]
    assert row["logged_at"] == "2026-06-13T15:12:11Z" and row["model_source"] == "locked_minimal"


def test_import_locked_receipts_backfills_at_lock_time(tmp_path):
    locked = {
        "schema_version": "1.0", "kind": "locked", "model_version": "stage0@abc",
        "locked_at_utc": "2026-06-13T15:12:11Z",
        "predictions": [
            {"fixture_id": "WC26-M005", "stage": "group", "kickoff_utc": "2026-06-14T19:00:00Z",
             "team1": "MEX", "team2": "RSA", "model_source": "locked_minimal",
             "wdl": {"team1": 0.5, "draw": 0.3, "team2": 0.2}, "scorelines": [{"score": "1-0", "p": 0.2}]},
            {"fixture_id": "WC26-M006", "stage": "group", "kickoff_utc": "2026-06-14T22:00:00Z",
             "team1": "KOR", "team2": "CZE", "model_source": "locked_minimal",
             "wdl": {"team1": 0.3, "draw": 0.3, "team2": 0.4}, "scorelines": [{"score": "0-1", "p": 0.18}]},
        ]}
    (tmp_path / "predictions_locked_20260613.json").write_text(json.dumps(locked))
    log_path = tmp_path / "log.parquet"

    assert import_locked_receipts(log_path, tmp_path) == 2     # both locked pre-kickoff
    assert import_locked_receipts(log_path, tmp_path) == 0     # idempotent
    log = load_log(log_path)
    assert bool((log["logged_at"] == "2026-06-13T15:12:11Z").all())
    assert set(log["model_source"]) == {"locked_minimal"}


def test_track_record_prefers_live_and_attributes_locked():
    # M005: locked only. M013: locked + live -> the live call wins, the locked one is hidden.
    log = pd.DataFrame([
        {"logged_at": "2026-06-13T15:00:00Z", "kickoff_utc": "2026-06-14T19:00:00Z",
         "model_source": "locked_minimal", "model_version": "lk", "fixture_id": "WC26-M005",
         "team1": "MEX", "team2": "RSA", "p_team1": 0.5, "p_draw": 0.3, "p_team2": 0.2,
         "top_score": "1-0", "top_score_p": 0.2},
        {"logged_at": "2026-06-13T15:00:00Z", "kickoff_utc": "2026-06-15T19:00:00Z",
         "model_source": "locked_minimal", "model_version": "lk", "fixture_id": "WC26-M013",
         "team1": "KOR", "team2": "CZE", "p_team1": 0.4, "p_draw": 0.3, "p_team2": 0.3,
         "top_score": "1-1", "top_score_p": 0.15},
        {"logged_at": "2026-06-15T10:00:00Z", "kickoff_utc": "2026-06-15T19:00:00Z",
         "model_source": "live_full", "model_version": "lv", "fixture_id": "WC26-M013",
         "team1": "KOR", "team2": "CZE", "p_team1": 0.45, "p_draw": 0.3, "p_team2": 0.25,
         "top_score": "2-1", "top_score_p": 0.12},
    ])
    fixtures = _fixtures([
        ("WC26-M005", "MEX", "RSA", 0, 1, True),
        ("WC26-M013", "KOR", "CZE", 1, 1, True),
    ])
    art = track_record_artifact(log, fixtures)
    by = {r["fixture_id"]: r for r in art["resolved"]}
    assert art["n_resolved"] == 2                                  # one receipt per match
    assert by["WC26-M005"]["model"] == "pre-tournament (locked)"
    assert by["WC26-M013"]["model"] == "live"                      # live preferred when both exist
    assert by["WC26-M013"]["p_team1"] == 0.45                      # the live call's probs, not locked


def test_committed_live_artifact_is_logged_under_its_own_model_version():
    """The 'nothing goes live un-logged' guarantee as committed data, not just schema: every
    prediction in predictions_live.json must have a pre-kickoff receipt under the artifact's OWN
    model_version. Catches identity drift the schema check can't — an artifact re-pinned to a
    version with zero log rows still validates (the numbers may match an older version's
    receipts), but its identity no longer ties to the audit trail."""
    art_path = _REPO / "data" / "predictions" / "predictions_live.json"
    log_path = _REPO / "data" / "predictions" / "prediction_log.parquet"
    assert art_path.exists() and log_path.exists(), "committed live artifact + log expected"

    art = json.loads(art_path.read_text())
    mv = art["model_version"]
    log = load_log(log_path)
    pre = log[(log["model_version"] == mv) & (log["logged_at"] < log["kickoff_utc"])]
    logged = set(pre["fixture_id"])
    missing = sorted(p["fixture_id"] for p in art["predictions"] if p["fixture_id"] not in logged)
    assert not missing, (
        f"{len(missing)} live prediction(s) have no pre-kickoff log row under the artifact's "
        f"model_version {mv!r} — identity has drifted off the audit trail: {missing[:10]}"
    )

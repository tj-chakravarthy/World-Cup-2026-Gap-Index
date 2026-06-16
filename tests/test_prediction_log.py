"""Append-only prediction log (src/update/prediction_log.py).

Guards: idempotent append on (model_version, fixture_id); resolve() scores against
the realised result and leaves unplayed fixtures null; track_record's called rate and
multiclass Brier match a hand-computed small set, excluding unresolved rows.
"""

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("pyarrow")

from src.update.prediction_log import (  # noqa: E402
    LOG_COLUMNS,
    latest_per_fixture,
    load_log,
    log_predictions,
    resolve,
    track_record,
    track_record_artifact,
)


def test_latest_per_fixture_keeps_standing_prediction():
    # same fixture logged under two model versions before kickoff -> keep the later one
    log = pd.DataFrame({
        "logged_at": ["2026-06-14T10:00:00Z", "2026-06-14T12:00:00Z"],
        "model_source": ["live_full", "live_full"],
        "fixture_id": ["WC26-M050", "WC26-M050"],
        "model_version": ["live@aaa", "live@bbb"],
    })
    out = latest_per_fixture(log)
    assert len(out) == 1
    assert out.iloc[0]["model_version"] == "live@bbb"  # the later-logged version stands


def _artifact(model_version="m@v1", preds=None):
    if preds is None:
        preds = [
            {
                "fixture_id": "WC26-M001",
                "stage": "group",
                "kickoff_utc": "2026-06-11T19:00:00Z",
                "team1": "MEX",
                "team2": "RSA",
                "model_source": "live_full",
                "wdl": {"team1": 0.6, "draw": 0.25, "team2": 0.15},
                "scorelines": [{"score": "2-0", "p": 0.18}, {"score": "1-0", "p": 0.12}],
            },
            {
                "fixture_id": "WC26-M002",
                "stage": "group",
                "kickoff_utc": "2026-06-12T02:00:00Z",
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

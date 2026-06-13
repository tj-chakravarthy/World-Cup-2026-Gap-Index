"""Stage-0 lock builder (PLAN.md Build Order Stage 0). Tests the coverage
partition and that an assembled artifact clears the schema validator — the lock
can't be re-issued, so the builder must produce a valid file by construction."""

from datetime import datetime, timezone

import pytest

pytest.importorskip("scipy")

from src.models.dixon_coles import DCModel  # noqa: E402
from src.pipeline import build_lock as bl  # noqa: E402
from src.pipeline.write_predictions import validate  # noqa: E402

LOCK = datetime(2026, 6, 13, 15, 0, 0, tzinfo=timezone.utc)


def _fx(fid, kickoff, played="False", hc="BRA", ac="ARG"):
    return {
        "fixture_id": fid, "stage": "group", "group": "A", "matchday": "1",
        "kickoff_utc": kickoff, "venue_key": "X", "home_team": "a", "away_team": "b",
        "home_code": hc, "away_code": ac, "home_score": "", "away_score": "", "played": played,
    }


def test_partition_splits_covered_excluded_pending():
    fixtures = [
        _fx("WC26-M001", "2026-06-12T19:00:00Z", played="True"),    # played -> excluded
        _fx("WC26-M002", "2026-06-13T10:00:00Z"),                   # kicked off pre-lock -> excluded
        _fx("WC26-M003", "2026-06-13T19:00:00Z"),                   # future, teams known -> covered
        _fx("WC26-M073", "2026-06-28T19:00:00Z", hc="", ac=""),     # future, teams unknown -> pending
    ]
    cov, exc, pen = bl.partition(fixtures, LOCK)
    assert [r["fixture_id"] for r in cov] == ["WC26-M003"]
    assert {r["fixture_id"] for r in exc} == {"WC26-M001", "WC26-M002"}
    assert [r["fixture_id"] for r in pen] == ["WC26-M073"]


def test_assembled_artifact_validates():
    model = DCModel(
        intercept=0.0, home_adv=0.2,
        attack={"Brazil": 0.5, "Argentina": 0.4},
        defence={"Brazil": 0.3, "Argentina": 0.2}, rho=-0.05,
    )
    tc = bl.TeamCodes.load()
    fifa_to_elo = {v: k for k, v in tc.eloratings_to_fifa.items()}
    elo = {fifa_to_elo["BRA"]: 2000.0, fifa_to_elo["ARG"]: 1950.0}

    covered = [_fx("WC26-M050", "2026-06-20T19:00:00Z", hc="BRA", ac="ARG")]
    preds = bl.build_predictions(covered, model, elo, tc)
    assert preds[0]["model_source"] == "locked_minimal"
    assert set(preds[0]["members"]) == {"C", "E"}

    art = bl.build_artifact(LOCK, covered, [], [], preds, "2026-06-13T00:00:00Z")
    validate(art, fixture_universe={"WC26-M050"})  # raises if anything is off

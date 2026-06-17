"""The cron's cheap gate, run_all.check() (PLAN §6).

A fixture-refresh failure must never be silent: the first failure recomputes (so the run
republishes stale=True and the site banner fires), a second consecutive failure fails the cron,
and recovery from a stale state recomputes to clear the flag. Exit codes: 10 recompute, 0 idle,
1 fail. Pure logic — _refresh_fixtures and the committed-stale read are stubbed.
"""

import json

import pytest

pd = pytest.importorskip("pandas")

from src.pipeline import run_all  # noqa: E402


def _prep(tmp_path, monkeypatch, *, played_ids, marker_ids, artifacts=True):
    fx = tmp_path / "fixtures.csv"
    rows = [{"fixture_id": f, "played": True} for f in played_ids]
    rows.append({"fixture_id": "WC26-M099", "played": False})  # one unplayed, always present
    pd.DataFrame(rows).to_csv(fx, index=False)
    monkeypatch.setattr(run_all, "FIXTURES", fx)

    marker = tmp_path / ".last_played"
    if marker_ids is not None:
        marker.write_text(" ".join(marker_ids))
    monkeypatch.setattr(run_all, "MARKER", marker)

    live, sim = tmp_path / "live.json", tmp_path / "sim.json"
    if artifacts:
        live.write_text("{}")
        sim.write_text("{}")
    monkeypatch.setattr(run_all, "LIVE", live)
    monkeypatch.setattr(run_all, "SIM", sim)


def _stub(monkeypatch, *, fresh, was_stale):
    monkeypatch.setattr(run_all, "_refresh_fixtures", lambda: fresh)
    monkeypatch.setattr(run_all, "_committed_live_is_stale", lambda: was_stale)


def test_idle_when_fresh_and_no_new_result(tmp_path, monkeypatch):
    _prep(tmp_path, monkeypatch, played_ids=["WC26-M001"], marker_ids=["WC26-M001"])
    _stub(monkeypatch, fresh=True, was_stale=False)
    assert run_all.check() == 0


def test_recompute_on_new_result(tmp_path, monkeypatch):
    _prep(tmp_path, monkeypatch, played_ids=["WC26-M001"], marker_ids=[])
    _stub(monkeypatch, fresh=True, was_stale=False)
    assert run_all.check() == 10


def test_refresh_failure_first_time_recomputes_for_stale_heartbeat(tmp_path, monkeypatch):
    _prep(tmp_path, monkeypatch, played_ids=["WC26-M001"], marker_ids=["WC26-M001"])
    _stub(monkeypatch, fresh=False, was_stale=False)  # feed down, last run was fresh
    assert run_all.check() == 10  # recompute -> publishes stale=True (heartbeat)


def test_refresh_failure_when_already_stale_fails_the_cron(tmp_path, monkeypatch):
    _prep(tmp_path, monkeypatch, played_ids=["WC26-M001"], marker_ids=["WC26-M001"])
    _stub(monkeypatch, fresh=False, was_stale=True)  # second consecutive failure
    assert run_all.check() == 1


def test_recovery_from_stale_recomputes_to_clear_flag(tmp_path, monkeypatch):
    _prep(tmp_path, monkeypatch, played_ids=["WC26-M001"], marker_ids=["WC26-M001"])
    _stub(monkeypatch, fresh=True, was_stale=True)  # feed back, artifact still flagged stale
    assert run_all.check() == 10


def test_committed_live_is_stale_reads_sources(tmp_path, monkeypatch):
    live = tmp_path / "live.json"
    monkeypatch.setattr(run_all, "LIVE", live)
    live.write_text(json.dumps({"sources": [{"name": "fixtures", "stale": True}]}))
    assert run_all._committed_live_is_stale() is True
    live.write_text(json.dumps({"sources": [{"name": "fixtures", "stale": False}]}))
    assert run_all._committed_live_is_stale() is False
    monkeypatch.setattr(run_all, "LIVE", tmp_path / "absent.json")
    assert run_all._committed_live_is_stale() is False

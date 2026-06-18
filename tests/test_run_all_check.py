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


def _stub(monkeypatch, *, fresh, was_stale, cards_changed=False, fixtures_changed=False):
    monkeypatch.setattr(run_all, "_refresh_fixtures", lambda: fresh)
    monkeypatch.setattr(run_all, "_committed_live_is_stale", lambda: was_stale)
    monkeypatch.setattr(run_all, "_cards_changed", lambda: cards_changed)
    monkeypatch.setattr(run_all, "_fixtures_changed", lambda fx: fixtures_changed)


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


_BASE = dict(force=False, rebuild=False, artifacts_exist=True, played={"a"}, last={"a"},
             fresh=True, was_stale=False, live_covers_kicked_off=False, cards_changed=False,
             fixtures_changed=False)


@pytest.mark.parametrize("over,expected", [
    ({"force": True}, True),                          # --force
    ({"rebuild": True}, True),                         # --rebuild
    ({"artifacts_exist": False}, True),                # artifacts missing
    ({"played": {"a", "b"}}, True),                    # new result
    ({"fresh": False}, True),                          # feed failure -> publish stale heartbeat
    ({"was_stale": True}, True),                       # recovery -> clear stale banner
    ({"live_covers_kicked_off": True}, True),          # a covered fixture passed kickoff -> drop it
    ({"cards_changed": True}, True),                   # fair-play cards edited -> pick up conduct
    ({"fixtures_changed": True}, True),                # decided knockout / landed winner_code, same played set
    ({}, False),                                       # idle: nothing changed
    ({"fresh": False, "was_stale": True}, False),      # still down + already stale (check escalates)
])
def test_should_recompute_covers_all_signals(over, expected):
    # the follow-through to check()'s signals: main() must recompute on a stale flip OR a covered
    # fixture passing kickoff, even without --force, so those paths can't no-op
    assert run_all._should_recompute(**{**_BASE, **over}) is expected


def test_recompute_on_cards_change(tmp_path, monkeypatch):
    # no new result/kickoff change, but the manual fair-play cards were committed -> recompute so
    # load_conduct's new values reach the sim (the 'next cron run' the docs promise)
    _prep(tmp_path, monkeypatch, played_ids=["WC26-M001"], marker_ids=["WC26-M001"])
    _stub(monkeypatch, fresh=True, was_stale=False, cards_changed=True)
    assert run_all.check() == 10


def test_recompute_on_semantic_fixtures_change(tmp_path, monkeypatch):
    # no new played id, feed fine — but a knockout got its participants or a shootout winner_code
    # landed (the played set is unchanged), so the semantic hash flips -> recompute
    _prep(tmp_path, monkeypatch, played_ids=["WC26-M001"], marker_ids=["WC26-M001"])
    _stub(monkeypatch, fresh=True, was_stale=False, fixtures_changed=True)
    assert run_all.check() == 10


def test_fixtures_changed_catches_decided_bracket_and_winner_code(tmp_path, monkeypatch):
    marker = tmp_path / ".fixtures_hash"
    monkeypatch.setattr(run_all, "FIXHASH_MARKER", marker)

    def _fx(home="", away="", winner="", hs="", asc="", played=False):
        # build each scenario as a fresh frame — pandas 3.0 infers a strict str dtype, so mutating
        # one frame's string cell to an int (.loc) raises; a fresh frame per case sidesteps that
        return pd.DataFrame([{"fixture_id": "WC26-M073", "home_code": home, "away_code": away,
                              "winner_code": winner, "home_score": hs, "away_score": asc,
                              "played": played}])

    base = _fx()                                              # undecided R32 slot
    assert run_all._fixtures_changed(base) is True            # marker absent -> changed
    marker.write_text(run_all._fixtures_semantic_hash(base))
    assert run_all._fixtures_changed(base) is False           # stable feed -> idle

    decided = _fx(home="ESP", away="URU")                     # participants filled in (same played set)
    assert run_all._fixtures_changed(decided) is True         # caught

    shootout = _fx(home="ESP", away="URU", hs=1, asc=1, played=True)   # played, winner not named yet
    marker.write_text(run_all._fixtures_semantic_hash(shootout))
    landed = _fx(home="ESP", away="URU", winner="URU", hs=1, asc=1, played=True)  # winner_code lands
    assert run_all._fixtures_changed(landed) is True          # still played -> caught


def test_cards_changed_compares_hash_to_marker(tmp_path, monkeypatch):
    cards, marker = tmp_path / "cards.csv", tmp_path / ".cards_hash"
    monkeypatch.setattr(run_all, "CARDS", cards)
    monkeypatch.setattr(run_all, "CARDS_MARKER", marker)
    cards.write_text("fixture_id,team_code,yellow\n")
    assert run_all._cards_changed() is True                 # marker absent -> changed
    marker.write_text(run_all._cards_hash())
    assert run_all._cards_changed() is False                # marker matches -> idle
    cards.write_text("fixture_id,team_code,yellow\nWC26-M005,ESP,2\n")
    assert run_all._cards_changed() is True                 # cards edited -> changed


def test_recompute_when_live_still_covers_a_kicked_off_fixture(tmp_path, monkeypatch):
    # no new result, feed fine — but the published artifact still predicts a match past kickoff,
    # so the gate must recompute to drop it (deterministic, doesn't wait on the lagging result)
    _prep(tmp_path, monkeypatch, played_ids=["WC26-M001"], marker_ids=["WC26-M001"])
    (tmp_path / "live.json").write_text(json.dumps(
        {"predictions": [{"fixture_id": "WC26-M023", "kickoff_utc": "2020-01-01T00:00:00Z"}]}))
    _stub(monkeypatch, fresh=True, was_stale=False)
    assert run_all.check() == 10


def test_live_covers_kicked_off(tmp_path, monkeypatch):
    live = tmp_path / "live.json"
    monkeypatch.setattr(run_all, "LIVE", live)
    now = "2026-06-17T19:00:00Z"
    live.write_text(json.dumps({"predictions": [{"fixture_id": "X", "kickoff_utc": "2026-06-17T17:00:00Z"}]}))
    assert run_all._live_covers_kicked_off(now) is True            # 17:00 < 19:00
    live.write_text(json.dumps({"predictions": [{"fixture_id": "X", "kickoff_utc": "2026-06-18T17:00:00Z"}]}))
    assert run_all._live_covers_kicked_off(now) is False           # all future
    monkeypatch.setattr(run_all, "LIVE", tmp_path / "absent.json")
    assert run_all._live_covers_kicked_off(now) is False


def test_committed_live_is_stale_reads_sources(tmp_path, monkeypatch):
    live = tmp_path / "live.json"
    monkeypatch.setattr(run_all, "LIVE", live)
    live.write_text(json.dumps({"sources": [{"name": "fixtures", "stale": True}]}))
    assert run_all._committed_live_is_stale() is True
    live.write_text(json.dumps({"sources": [{"name": "fixtures", "stale": False}]}))
    assert run_all._committed_live_is_stale() is False
    monkeypatch.setattr(run_all, "LIVE", tmp_path / "absent.json")
    assert run_all._committed_live_is_stale() is False

"""Fixtures spine invariants (PLAN.md §1.5).

Guards the committed data/raw/fixtures_2026.csv: the lock is built against this
spine, so a silent feed-schema drift (wrong count, an unmapped team, a duplicate
id) must fail CI. Pure stdlib — reads the committed CSV, no network, no modelling stack.
"""

import csv
import re
from datetime import datetime
from pathlib import Path

from src.pipeline.fetch_fixtures_venues import _iso, _stage, build_fixtures

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "data" / "raw" / "fixtures_2026.csv"

_STAGE_COUNTS = {"group": 72, "R32": 16, "R16": 8, "QF": 4, "SF": 2,
                 "third_place": 1, "final": 1}


def _fixtures():
    return list(csv.DictReader(FIXTURES.open()))


def test_104_fixtures_unique_ids():
    fx = _fixtures()
    assert len(fx) == 104
    ids = [r["fixture_id"] for r in fx]
    assert len(set(ids)) == 104
    assert all(re.fullmatch(r"WC26-M\d{3}", i) for i in ids)
    # id is keyed on the official match number
    assert all(r["fixture_id"] == f"WC26-M{int(r['match_number']):03d}" for r in fx)


def test_stage_counts():
    fx = _fixtures()
    counts = {}
    for r in fx:
        counts[r["stage"]] = counts.get(r["stage"], 0) + 1
    assert counts == _STAGE_COUNTS


def test_all_16_host_venues_used():
    fx = _fixtures()
    assert len({r["venue_key"] for r in fx}) == 16  # every fixture maps to one of 16 venues


def test_48_group_teams_coded_knockout_blank_or_field():
    fx = _fixtures()
    field = set()
    for r in fx:
        if r["stage"] == "group":
            assert r["home_code"] and r["away_code"], f"{r['fixture_id']} uncoded group team"
            field |= {r["home_code"], r["away_code"]}
    assert len(field) == 48
    # knockout codes are blank until the bracket decides them, then a real field code
    for r in fx:
        if r["stage"] != "group":
            for c in (r["home_code"], r["away_code"]):
                assert c == "" or c in field, f"{r['fixture_id']} code {c!r} not blank/in field"


def test_played_flag_matches_scores():
    for r in _fixtures():
        played = r["played"] == "True"
        has_score = r["home_score"] != "" and r["away_score"] != ""
        assert played == has_score, f"{r['fixture_id']} played/score mismatch"
        if played:
            int(r["home_score"]); int(r["away_score"])  # parse, else raises


def test_kickoff_utc_parses():
    for r in _fixtures():
        datetime.fromisoformat(r["kickoff_utc"].replace("Z", "+00:00"))


def test_winner_code_consistent_with_result():
    # the sim pins knockout winners off winner_code, so it has to be one of the two participants on
    # a played match, and agree with the score on a decisive result (a level score may still name a
    # shootout winner — that's allowed, so only the decisive case is checked against the score)
    for r in _fixtures():
        wc = r["winner_code"]
        if not wc:
            continue
        assert r["played"] == "True", f"{r['fixture_id']} winner_code on unplayed"
        assert wc in (r["home_code"], r["away_code"]), f"{r['fixture_id']} winner_code not a participant"
        hs, as_ = r["home_score"], r["away_score"]
        if hs and as_ and int(hs) != int(as_):
            decisive = r["home_code"] if int(hs) > int(as_) else r["away_code"]
            assert wc == decisive, f"{r['fixture_id']} winner_code disagrees with the score"


def test_build_fixtures_maps_winner_code():
    # the feed's Winner -> winner_code: a named side maps to its FIFA code, "Draw"/"" stay blank
    feed = [
        {"MatchNumber": 1, "RoundNumber": 1, "Group": "Group A", "DateUtc": "2026-06-11 19:00:00Z",
         "Location": "X", "HomeTeam": "Mexico", "AwayTeam": "South Africa",
         "HomeTeamScore": 2, "AwayTeamScore": 0, "Winner": "Mexico"},
        {"MatchNumber": 3, "RoundNumber": 1, "Group": "Group A", "DateUtc": "2026-06-12 19:00:00Z",
         "Location": "X", "HomeTeam": "Canada", "AwayTeam": "Bosnia and Herzegovina",
         "HomeTeamScore": 1, "AwayTeamScore": 1, "Winner": "Draw"},
        {"MatchNumber": 73, "RoundNumber": 4, "Group": None, "DateUtc": "2026-06-28 19:00:00Z",
         "Location": "X", "HomeTeam": "2A", "AwayTeam": "2B",
         "HomeTeamScore": None, "AwayTeamScore": None, "Winner": ""},
    ]
    rows = {r["fixture_id"]: r for r in build_fixtures(feed)}
    assert rows["WC26-M001"]["winner_code"] == "MEX"
    assert rows["WC26-M003"]["winner_code"] == ""    # a draw names no winner
    assert rows["WC26-M073"]["winner_code"] == ""    # undecided slot


def test_stage_mapping_unit():
    assert _stage(1, 1) == "group"
    assert _stage(73, 4) == "R32"
    assert _stage(103, 8) == "third_place"
    assert _stage(104, 8) == "final"


def test_iso_normalises_separator():
    assert _iso("2026-06-11 19:00:00Z") == "2026-06-11T19:00:00Z"

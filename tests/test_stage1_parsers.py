"""Pure-function tests for the Stage-1 fetchers (no network, no browser).

The fetchers themselves hit the wire, but their parsing/cleaning logic is pure
and is where bugs would silently corrupt the data. bs4/selenium aren't in the CI
dev subset, so the tests that need them importorskip rather than break collection.
"""

import pytest

from src.pipeline.extract_qualifying import extract
from src.pipeline.fetch_club_elo import parse_snapshot


def test_club_elo_parse_snapshot_skips_blank_and_rounds():
    text = ("Rank,Club,Country,Level,Elo,From,To\n"
            "1,Arsenal,ENG,1,2063.758,2026-05-31,2026-07-03\n"
            "2,Bayern,GER,1,2000.870,2026-05-21,2026-07-03\n"
            ",,,,,,\n")  # trailing blank row must be dropped
    rows = parse_snapshot(text, "2026-06-13")
    assert len(rows) == 2
    assert rows[0] == {"club": "Arsenal", "country": "ENG", "level": "1",
                       "elo": 2063.76, "rank": "1", "as_of": "2026-06-13"}


def test_qualifying_extract_filters_and_tags_campaign():
    rows = [
        {"tournament": "FIFA World Cup qualification", "home_team": "A"},
        {"tournament": "Friendly", "home_team": "B"},
        {"tournament": "UEFA Euro qualification", "home_team": "C"},
    ]
    out = extract(rows)
    assert [r["home_team"] for r in out] == ["A", "C"]
    assert out[0]["campaign"] == "FIFA World Cup qualification"


def test_squad_parsers():
    pytest.importorskip("bs4")
    from src.pipeline.fetch_squad_rosters import _age, _int, _norm, parse_squads
    assert _norm("Matěj Kovář") == "matej kovar"
    assert _int("—") == 0 and _int("41[a]") == 41
    assert _age("2000-05-17") == 26  # tournament start 2026-06-11, birthday passed
    html = (
        '<h3>Brazil</h3><table class="wikitable">'
        '<tr><th>No.</th><th>Pos.</th><th>Player</th><th>Date of birth (age)</th>'
        '<th>Caps</th><th>Goals</th><th>Club</th></tr>'
        '<tr><th>1</th><td>1 GK</td><th>Alisson</th>'
        '<td><span class="bday">1992-10-02</span> (aged 33)</td>'
        '<td>70</td><td>0</td><td>Liverpool</td></tr></table>'
    )
    rows = parse_squads(html)
    assert len(rows) == 1
    r = rows[0]
    assert (r["team"], r["player_name"], r["position"]) == ("Brazil", "Alisson", "GK")
    assert r["dob"] == "1992-10-02" and r["caps"] == 70 and r["club"] == "Liverpool"


def test_club_stats_parse_by_datastat():
    pytest.importorskip("selenium")
    pytest.importorskip("pandas")
    from src.pipeline.fetch_club_stats import _parse_players
    html = (
        '<table><tbody>'
        '<tr class="thead"><th data-stat="player">Player</th>'
        '<td data-stat="goals">Gls</td></tr>'  # repeated header row -> skipped
        '<tr><th data-stat="ranker">1</th><td data-stat="player">Erling Haaland</td>'
        '<td data-stat="team">Manchester City</td><td data-stat="goals">27</td>'
        '<td data-stat="matches">Matches</td></tr>'
        '<tr><td data-stat="team">No Player</td><td data-stat="goals">0</td></tr>'  # no player -> skipped
        '</tbody></table>'
    )
    df = _parse_players(html)
    assert list(df["player"]) == ["Erling Haaland"]
    assert "ranker" not in df.columns and "matches" not in df.columns
    assert df.loc[0, "goals"] == "27" and df.loc[0, "team"] == "Manchester City"

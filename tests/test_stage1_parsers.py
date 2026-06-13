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


def test_club_stats_clean_drops_repeat_headers_and_matches_col():
    pytest.importorskip("selenium")
    pd = pytest.importorskip("pandas")
    from src.pipeline.fetch_club_stats import _clean
    df = pd.DataFrame(
        [["1", "Haaland", 2552, "m1"],
         ["Rk", "Player", "Min", "Matches"],   # FBref's mid-table repeated header
         ["2", "Saka", 3000, "m3"]],
        columns=[("Unnamed: 0_level_0", "Rk"), ("Unnamed: 1_level_0", "Player"),
                 ("Playing Time", "Min"), ("Unnamed: 3_level_0", "Matches")],
    )
    out = _clean(df)
    assert list(out["Player"]) == ["Haaland", "Saka"]
    assert "Matches" not in out.columns
    assert "Playing Time_Min" in out.columns

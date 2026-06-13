"""Unit tests for the Elo + results fetch transforms (PLAN.md §1.4, §1.8).

The fetch I/O needs the network; the parsing/normalisation is pure and is what
can silently corrupt the lock's inputs, so that is what is tested here — on
small in-memory fixtures, no network, no committed CSV.
"""

from src.pipeline.fetch_elo import build_elo, parse_teams
from src.pipeline.fetch_match_results import normalize_results


def test_normalize_results_blanks_na_scores():
    text = (
        "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n"
        "2022-12-18,Argentina,France,3,3,FIFA World Cup,Lusail,Qatar,TRUE\n"
        "2026-06-27,Panama,England,NA,NA,FIFA World Cup,East Rutherford,United States,TRUE\n"
    )
    fields, rows = normalize_results(text)
    assert "tournament" in fields
    assert rows[0]["home_score"] == "3" and rows[0]["away_score"] == "3"
    # NA -> "" so unplayed/future rows read like fixtures_2026.csv
    assert rows[1]["home_score"] == "" and rows[1]["away_score"] == ""
    # names kept verbatim (canonicalisation is name_matcher, not the fetch)
    assert rows[1]["home_team"] == "Panama"


def test_parse_teams_takes_primary_name_ignores_aliases():
    text = "ES\tSpain\nAG\tAntigua and Barbuda\tAntigua & Barbuda\nKR\tSouth Korea\n"
    teams = parse_teams(text)
    assert teams["ES"] == "Spain"
    assert teams["AG"] == "Antigua and Barbuda"  # first alias column only
    assert teams["KR"] == "South Korea"


def test_build_elo_joins_and_handles_missing_code():
    teams = {"ES": "Spain", "AR": "Argentina"}
    # World.tsv layout: col0 rank, col2 code, col3 elo (extra cols ignored)
    world = "1\t1\tES\t2157\tx\ty\n2\t2\tAR\t2115\tx\ty\n3\t3\tZZ\t1900\tx\ty\n"
    rows = build_elo(world, teams, as_of="2026-06-13")
    assert [r["elo_code"] for r in rows] == ["ES", "AR", "ZZ"]
    assert rows[0] == {"elo_code": "ES", "team_name": "Spain", "rank": 1,
                       "elo": 2157, "as_of": "2026-06-13"}
    # unknown code keeps the row (code is the join key) with a blank name
    assert rows[2]["team_name"] == "" and rows[2]["elo"] == 1900

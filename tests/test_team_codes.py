"""Team-code crosswalk invariants (PLAN.md name_matcher).

Two layers: the committed crosswalk must stay consistent with the fixtures spine
(both committed), and the build/validation logic must reject a bad mapping. The
source-membership check needs the gitignored elo/results CSVs, so it is unit-
tested on synthetic sets here, not against live data.
"""

import csv
from pathlib import Path

import pytest

from src.pipeline.team_codes import TeamCodes, build_rows

REPO = Path(__file__).resolve().parents[1]
TEAM_CODES = REPO / "data" / "raw" / "team_codes.csv"
FIXTURES = REPO / "data" / "raw" / "fixtures_2026.csv"


def _rows(path):
    return list(csv.DictReader(path.open()))


def test_crosswalk_covers_the_48_fixture_teams():
    cross = {r["fifa_code"] for r in _rows(TEAM_CODES)}
    fx = _rows(FIXTURES)
    fixture_codes = {r["home_code"] for r in fx if r["stage"] == "group"} | \
                    {r["away_code"] for r in fx if r["stage"] == "group"}
    assert len(cross) == 48
    assert cross == fixture_codes  # exact same 48 teams, no drift


def test_crosswalk_names_present_and_injective():
    rows = _rows(TEAM_CODES)
    for col in ("fifa_code", "name", "eloratings_name", "martj42_name"):
        vals = [r[col] for r in rows]
        assert all(vals), f"blank {col}"
        assert len(set(vals)) == len(vals), f"{col} not unique -> two teams collide"


def test_loader_lookups():
    tc = TeamCodes.load(TEAM_CODES)
    assert len(tc.fifa_to_name) == 48
    # the aliased cases are the ones worth asserting
    assert tc.eloratings_to_fifa["South Korea"] == "KOR"
    assert tc.martj42_to_fifa["Czech Republic"] == "CZE"
    assert tc.eloratings_to_fifa["United States"] == "USA"
    assert tc.fifa_to_name["CIV"] == "Côte d'Ivoire"


def test_build_rows_happy_path_applies_aliases():
    teams = [("KOR", "Korea Republic"), ("BRA", "Brazil"), ("CZE", "Czechia")]
    elo = {"South Korea", "Brazil", "Czechia"}
    m42 = {"South Korea", "Brazil", "Czech Republic"}
    rows = build_rows(teams, elo, m42)
    by = {r["fifa_code"]: r for r in rows}
    assert by["KOR"]["eloratings_name"] == "South Korea"
    assert by["CZE"]["eloratings_name"] == "Czechia"      # eloratings keeps it
    assert by["CZE"]["martj42_name"] == "Czech Republic"  # martj42 differs
    assert by["BRA"]["eloratings_name"] == "Brazil"       # verbatim


def test_build_rows_fails_loud_on_missing_source_name():
    # martj42 lacks the team entirely -> must raise, not silently drop
    with pytest.raises(ValueError, match="not in source"):
        build_rows([("KOR", "Korea Republic")], {"South Korea"}, {"Brazil"})


def test_build_rows_fails_on_collision():
    # two teams resolving to the same source name is a corrupt join
    with pytest.raises(ValueError, match="share a"):
        build_rows([("AAA", "Brazil"), ("BBB", "Brazil")], {"Brazil"}, {"Brazil"})

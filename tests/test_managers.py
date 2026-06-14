"""Manager-per-team extraction (PLAN.md §3). Stdlib only, CI-safe."""

from src.pipeline.fetch_managers import _team_managers, build_2026_skeleton


def test_team_managers_extracts_both_sides():
    match = {
        "home_team": {"home_team_name": "Brazil", "managers": [
            {"id": 1, "name": "Dorival Silvestre Júnior", "nickname": "Dorival Júnior",
             "dob": "1962-04-25", "country": {"name": "Brazil"}}]},
        "away_team": {"away_team_name": "Argentina", "managers": [
            {"id": 2, "name": "Lionel Scaloni", "nickname": None,
             "dob": "1978-05-16", "country": {"name": "Argentina"}}]},
    }
    rows = _team_managers(match)
    by = {r["team"]: r["manager_name"] for r in rows}
    assert by == {"Brazil": "Dorival Silvestre Júnior", "Argentina": "Lionel Scaloni"}


def test_team_managers_skips_missing():
    assert _team_managers({"home_team": {"home_team_name": "X"}, "away_team": {}}) == []
    # team present but no managers list -> nothing
    assert _team_managers({"home_team": {"home_team_name": "X", "managers": []}}) == []


def test_2026_skeleton_covers_all_squad_nations_with_blank_manager():
    skel = build_2026_skeleton()
    assert len(skel) == 48
    assert all(r["manager_name"] == "" for r in skel)
    assert all(r["country_code"] and r["country"] for r in skel)

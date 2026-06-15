"""Monte Carlo sim — knockout stage mapping + group tally (PLAN.md §5.2)."""

import pytest

pytest.importorskip("pandas")
pytest.importorskip("scipy")
pytest.importorskip("sklearn")

from src.models.monte_carlo import _stage_of, simulate_groups  # noqa: E402


def test_stage_of_maps_fixture_numbers():
    assert _stage_of("WC26-M089") == "R16"
    assert _stage_of("WC26-M096") == "R16"
    assert _stage_of("WC26-M097") == "QF"
    assert _stage_of("WC26-M101") == "SF"
    assert _stage_of("WC26-M104") == "final"
    assert _stage_of("WC26-M103") is None  # third-place playoff, skipped


def _played(fid, home, away, hs, as_):
    return {"fixture_id": fid, "home_code": home, "away_code": away,
            "played": True, "home_score": hs, "away_score": as_}


def test_simulate_groups_deterministic_when_all_played():
    # one group, all six fixtures played: A wins all, B wins two, C wins one, D none
    group_fix = {"A": [
        _played("1", "A", "B", 2, 0), _played("2", "A", "C", 1, 0),
        _played("3", "A", "D", 3, 0), _played("4", "B", "C", 1, 0),
        _played("5", "B", "D", 2, 0), _played("6", "C", "D", 1, 0),
    ]}
    fifa_rank = {"A": 1, "B": 2, "C": 3, "D": 4}
    place, first, second, thirds, ranks = simulate_groups(group_fix, {}, fifa_rank, 3)
    # fully determined -> same standings every sim: A 1st, B 2nd, C 3rd, D 4th
    assert place["A"][0] == 3 and place["B"][1] == 3
    assert place["C"][2] == 3 and place["D"][3] == 3
    assert first[0]["A"] == "A" and second[0]["A"] == "B"
    assert ranks[0]["A"] == ["A", "B", "C", "D"]

"""Monte Carlo sim — knockout stage mapping + group tally (PLAN.md §5.2)."""

from collections import defaultdict

import pytest

pd = pytest.importorskip("pandas")
np = pytest.importorskip("numpy")
pytest.importorskip("scipy")
pytest.importorskip("sklearn")

from src.models.monte_carlo import (  # noqa: E402
    _stage_of, _walk_knockout, fixture_wdl, knockout_results, simulate_groups)


def _ko_fx(rows):
    cols = ["fixture_id", "stage", "home_code", "away_code", "home_score", "away_score", "played"]
    return pd.DataFrame(rows, columns=cols)


def test_knockout_results_from_score():
    fx = _ko_fx([
        ("WC26-M073", "R32", "ESP", "URU", 2, 0, True),    # ESP win
        ("WC26-M074", "R32", "BRA", "GHA", 0, 1, True),    # GHA win
        ("WC26-M075", "R32", "ENG", "SCO", "", "", False),  # unplayed -> skip
        ("WC26-M076", "R32", "", "", "", "", False),        # teams undecided -> skip
    ])
    assert knockout_results(fx) == {"WC26-M073": "ESP", "WC26-M074": "GHA"}


def test_knockout_results_penalties_read_from_next_round():
    # a drawn R32 (penalties) — winner isn't in the score, so it's read off the R16 fixture it
    # feeds (M073 + M075 -> M090). The bracket has ESP in M090, so ESP won the shootout.
    fx = _ko_fx([
        ("WC26-M073", "R32", "ESP", "URU", 1, 1, True),     # draw -> penalties
        ("WC26-M075", "R32", "ENG", "SCO", 2, 0, True),     # ENG win
        ("WC26-M090", "R16", "ESP", "ENG", "", "", False),  # downstream: ESP advanced
    ])
    r = knockout_results(fx)
    assert r["WC26-M073"] == "ESP" and r["WC26-M075"] == "ENG"


def test_walk_knockout_pins_played_result():
    # tilted stub -> the home team (a) always wins; ko_results pins M089 to the OTHER team and the
    # change must propagate (the pinned winner advances to the QF, the default one doesn't)
    r32 = {f"WC26-M{73 + i:03d}": f"T{i}" for i in range(16)}     # M073..M088 -> T0..T15
    tilted = lambda a, b, m: np.array([[0.0, 0.0], [1.0, 0.0]])   # noqa: E731 - scores 1-0, a wins
    rng = np.random.default_rng(0)

    default = defaultdict(lambda: defaultdict(int))
    _walk_knockout(r32, 0, tilted, rng, default)                  # M089 = (M074=T1, M077=T4) -> T1
    assert default["T1"]["QF"] >= 1 and default["T4"]["QF"] == 0

    pinned = defaultdict(lambda: defaultdict(int))
    _walk_knockout(r32, 0, tilted, rng, pinned, {"WC26-M089": "T4"})
    assert pinned["T4"]["QF"] >= 1 and pinned["T1"]["QF"] == 0    # the pin flipped who advances


class _StubBundle:
    wdl = {("ESP", "URU"): np.array([0.55, 0.24, 0.21]),
           ("ESP", "CPV"): np.array([0.70, 0.20, 0.10])}


def test_fixture_wdl_includes_decided_knockout():
    fx = pd.DataFrame([
        {"fixture_id": "WC26-M005", "stage": "group", "group": "A", "home_team": "Spain",
         "away_team": "Cape Verde", "home_code": "ESP", "away_code": "CPV", "played": False,
         "home_score": "", "away_score": ""},
        {"fixture_id": "WC26-M073", "stage": "R32", "group": "", "home_team": "Spain",
         "away_team": "Uruguay", "home_code": "ESP", "away_code": "URU", "played": False,
         "home_score": "", "away_score": ""},
        {"fixture_id": "WC26-M074", "stage": "R32", "group": "", "home_team": "W74",
         "away_team": "W74", "home_code": "", "away_code": "", "played": False,
         "home_score": "", "away_score": ""},
    ])
    out = fixture_wdl(_StubBundle(), fx)
    assert set(out["fixture_id"]) == {"WC26-M005", "WC26-M073"}   # decided; M074 (blank) dropped
    r = out.set_index("fixture_id").loc["WC26-M073"]
    assert r["stage"] == "R32" and r["p_home"] == 0.55


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

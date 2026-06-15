"""Gap analysis (src/models/gap.py, PLAN.md §7 /gap)."""

import numpy as np
import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("sklearn")

from src.models.gap import (
    TALENT_WEIGHTS,
    compute_gaps,
    results_ppg,
    talent_score,
)


def _indices(rows):
    """Tiny squad_indices frame; only the talent columns + keys need to be present."""
    cols = list(TALENT_WEIGHTS) + ["COV"]
    df = pd.DataFrame(rows)
    for c in cols:
        if c not in df.columns:
            df[c] = 0.0
    return df


# ---- talent_score ----------------------------------------------------------

def test_talent_one_row_per_team_tournament_finite():
    idx = _indices([
        {"tournament": "t", "country_code": "AAA", "team": "A", "MKT": 1.0, "ELO": 1.0},
        {"tournament": "t", "country_code": "BBB", "team": "B", "MKT": -1.0, "ELO": -1.0},
        {"tournament": "t", "country_code": "CCC", "team": "C", "MKT": 0.0, "ELO": 0.0},
    ])
    out = talent_score(idx)
    assert len(out) == 3
    assert set(out.columns) >= {"tournament", "country_code", "team", "talent"}
    assert np.isfinite(out["talent"]).all()
    # higher raw signal -> higher talent z-score
    z = dict(zip(out["team"], out["talent"]))
    assert z["A"] > z["C"] > z["B"]


def test_talent_nan_index_treated_as_field_mean():
    # a NaN cell (e.g. missing GK column) must not drop the team
    idx = _indices([
        {"tournament": "t", "country_code": "AAA", "team": "A", "MKT": np.nan, "ELO": 1.0},
        {"tournament": "t", "country_code": "BBB", "team": "B", "MKT": 0.0, "ELO": -1.0},
    ])
    out = talent_score(idx)
    assert len(out) == 2
    assert np.isfinite(out["talent"]).all()


# ---- results_ppg -----------------------------------------------------------

def _results(rows):
    return pd.DataFrame(rows, columns=["date", "home_team", "away_team",
                                       "home_score", "away_score", "tournament"])


def test_ppg_points_are_3_1_0_and_correct():
    # use the world_cup_2018 window so we don't need to touch match_dataset windows
    idx = _indices([
        {"tournament": "world_cup_2018", "country_code": "AAA", "team": "A"},
        {"tournament": "world_cup_2018", "country_code": "BBB", "team": "B"},
        {"tournament": "world_cup_2018", "country_code": "CCC", "team": "C"},
    ])
    res = _results([
        # A: win, draw, win -> 7 pts / 3 = 2.333
        ("2018-06-15", "A", "B", 2, 0, "FIFA World Cup"),
        ("2018-06-20", "A", "C", 1, 1, "FIFA World Cup"),
        ("2018-06-25", "C", "A", 0, 3, "FIFA World Cup"),
        # B: loss then draw vs C -> 1 pt / 2 games (only 2 played for B/C beyond A)
        ("2018-06-21", "B", "C", 1, 1, "FIFA World Cup"),
    ])
    ppg = results_ppg(res, idx)
    by = ppg.set_index("team")
    # A: win(3) + draw(1) + win(3) = 7 over 3 games
    assert by.loc["A", "n_games"] == 3
    assert by.loc["A", "ppg"] == pytest.approx(7 / 3)
    # B: loss vs A (0) + draw vs C (1) = 1 pt over 2 games
    assert by.loc["B", "n_games"] == 2
    assert by.loc["B", "ppg"] == pytest.approx(0.5)


def test_ppg_team_with_no_games_is_skipped_not_crashed():
    idx = _indices([
        {"tournament": "world_cup_2018", "country_code": "AAA", "team": "A"},
        {"tournament": "world_cup_2018", "country_code": "BBB", "team": "B"},
        {"tournament": "world_cup_2018", "country_code": "ZZZ", "team": "Zeta"},  # plays nothing
    ])
    res = _results([
        ("2018-06-15", "A", "B", 1, 0, "FIFA World Cup"),
    ])
    ppg = results_ppg(res, idx)  # must not raise
    assert "Zeta" not in set(ppg["team"])
    assert set(ppg["team"]) == {"A", "B"}


def test_ppg_partial_edition_low_n():
    # one game played -> n_games 1, marked partial, no divide-by-zero
    idx = _indices([
        {"tournament": "world_cup_2018", "country_code": "AAA", "team": "A"},
        {"tournament": "world_cup_2018", "country_code": "BBB", "team": "B"},
    ])
    res = _results([("2018-06-15", "A", "B", 2, 1, "FIFA World Cup")])
    ppg = results_ppg(res, idx)
    assert (ppg["n_games"] == 1).all()
    assert ppg["partial"].all()
    assert dict(zip(ppg["team"], ppg["ppg"]))["A"] == 3.0


# ---- compute_gaps ----------------------------------------------------------

def _talent_ppg(pairs):
    """Build matching talent + results frames from (team, talent, ppg, n) tuples."""
    tal = pd.DataFrame([
        {"tournament": "t", "country_code": c, "team": c, "talent": z, "cov": 0.0}
        for c, z, _, _ in pairs])
    ppg = pd.DataFrame([
        {"tournament": "t", "country_code": c, "team": c, "ppg": p, "n_games": n}
        for c, _, p, n in pairs])
    return tal, ppg


def test_gap_is_ppg_minus_expected_and_on_line_is_zero():
    # points lie exactly on ppg = 1 + 1*talent ; gap must be ~0 for all
    pairs = [(f"T{i}", float(i), 1.0 + float(i), 3) for i in range(-2, 3)]
    tal, ppg = _talent_ppg(pairs)
    g = compute_gaps(tal, ppg, fit_tournaments=["t"], n_boot=200, seed=1)
    assert g["gap"].abs().max() < 1e-9
    # gap is exactly ppg - expected_ppg by construction
    assert np.allclose(g["gap"].to_numpy(), (g["ppg"] - g["expected_ppg"]).to_numpy())


def test_gap_signs_and_bands_bracket_point():
    # baseline on the line, plus one clear over- and one clear under-performer
    pairs = [(f"L{i}", float(i), 1.0 + float(i), 3) for i in range(-2, 3)]
    pairs.append(("OVER", 0.0, 3.0, 3))   # well above the line
    pairs.append(("UNDER", 0.0, 0.0, 3))  # well below
    tal, ppg = _talent_ppg(pairs)
    g = compute_gaps(tal, ppg, fit_tournaments=["t"], n_boot=400, seed=2)
    by = g.set_index("team")
    assert by.loc["OVER", "gap"] > 0
    assert by.loc["UNDER", "gap"] < 0
    # band brackets the point estimate everywhere
    assert (g["gap_lo"] <= g["gap"] + 1e-9).all()
    assert (g["gap"] <= g["gap_hi"] + 1e-9).all()
    # lo < hi (a real band, not a degenerate point)
    assert (g["gap_hi"] > g["gap_lo"]).all()


def test_gap_output_is_tidy():
    tal, ppg = _talent_ppg([(f"T{i}", float(i), 1.0 + 0.5 * i, 3) for i in range(-2, 3)])
    g = compute_gaps(tal, ppg, fit_tournaments=["t"], n_boot=100, seed=0)
    expected = {"tournament", "country_code", "team", "talent", "ppg",
                "expected_ppg", "gap", "gap_lo", "gap_hi", "n_games"}
    assert set(g.columns) == expected

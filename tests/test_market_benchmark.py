"""Market benchmark (PLAN.md §4.6) — devig, compare, alignment/orientation."""

import numpy as np
import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("sklearn")  # market_benchmark imports the indices chain (predicted_vaep -> sklearn)

from src.models.market_benchmark import align, compare, devig  # noqa: E402


def test_devig_normalises_and_removes_overround():
    h, d, a = devig(2.0, 3.4, 4.0)
    assert h + d + a == pytest.approx(1.0)
    # raw implied probs sum > 1 (the overround); devig must shrink each below 1/odds
    assert h < 0.5 and d < 1 / 3.4 and a < 0.25
    # ordering preserved: shorter odds -> higher prob
    assert h > d > a


def test_devig_fair_odds_unchanged():
    # already-fair odds (implied sum to 1) come back as the raw inverses
    h, d, a = devig(2.0, 4.0, 4.0)
    assert (h, d, a) == pytest.approx((0.5, 0.25, 0.25))


def test_compare_brier_on_synthetic_model_vs_market():
    # two fixtures; model perfectly certain & correct -> Brier 0; market diffuse
    matched = pd.DataFrame({
        "target": [0, 2],
        "m_p0": [1.0, 0.0], "m_p1": [0.0, 0.0], "m_p2": [0.0, 1.0],
        "k_p0": [0.5, 0.2], "k_p1": [0.3, 0.3], "k_p2": [0.2, 0.5],
    })
    tbl = compare(matched).set_index("source")
    assert tbl.loc["model", "brier"] == pytest.approx(0.0)
    # market row0 (target 0): (.5-1)^2+.3^2+.2^2 = .38 ; row1 (target 2): same .38
    assert tbl.loc["market", "brier"] == pytest.approx(0.38)
    assert int(tbl.loc["model", "n"]) == 2


def test_compare_extra_baseline():
    matched = pd.DataFrame({
        "target": [1],
        "m_p0": [0.2], "m_p1": [0.6], "m_p2": [0.2],
        "k_p0": [0.3], "k_p1": [0.4], "k_p2": [0.3],
        "e0": [0.33], "e1": [0.34], "e2": [0.33],
    })
    tbl = compare(matched, extra={"Elo only": "e"})
    assert set(tbl["source"]) == {"model", "market", "Elo only"}


def _model_preds():
    # one fixture per orientation case; p0=team1 win, p2=team2 win
    return pd.DataFrame({
        "tournament": ["world_cup_2022", "world_cup_2022"],
        "team1": ["Brazil", "France"],   # second row: model team1 != market home
        "team2": ["Switzerland", "Morocco"],
        "target": [0, 0],
        "p0": [0.6, 0.7], "p1": [0.25, 0.2], "p2": [0.15, 0.1],
    })


def test_align_same_orientation():
    # market home==model team1 -> market probs map straight through
    odds = pd.DataFrame({
        "tournament": ["world_cup_2022"],
        "date": ["2022-11-28"],
        "home": ["Brazil"], "away": ["Switzerland"],
        "odds_home": [1.5], "odds_draw": [4.0], "odds_away": [7.0],
    })
    m = align(_model_preds()[:1], odds)
    assert len(m) == 1
    exp = devig(1.5, 4.0, 7.0)
    assert (m.iloc[0]["k_p0"], m.iloc[0]["k_p1"], m.iloc[0]["k_p2"]) == pytest.approx(exp)


def test_align_flips_when_team_order_differs():
    # market home==model team2 (Morocco) -> home/away market probs must swap so k_p0
    # stays "team1 (France) win"
    odds = pd.DataFrame({
        "tournament": ["world_cup_2022"],
        "date": ["2022-12-14"],
        "home": ["Morocco"], "away": ["France"],
        "odds_home": [7.0], "odds_draw": [4.0], "odds_away": [1.5],
    })
    m = align(_model_preds()[1:], odds)
    assert len(m) == 1
    # devig of (Morocco home, France away); flipped: k_p0=France(away), k_p2=Morocco(home)
    p_home, p_draw, p_away = devig(7.0, 4.0, 1.5)
    assert m.iloc[0]["k_p0"] == pytest.approx(p_away)   # France win = market away
    assert m.iloc[0]["k_p1"] == pytest.approx(p_draw)
    assert m.iloc[0]["k_p2"] == pytest.approx(p_home)   # Morocco win = market home
    # and the higher-prob side is France (short odds 1.5) -> k_p0 largest
    assert m.iloc[0]["k_p0"] > m.iloc[0]["k_p2"]


def test_align_date_tiebreak_for_rematch():
    # same oriented pair twice (group + knockout) disambiguated positionally by date
    preds = pd.DataFrame({
        "tournament": ["copa_america_2024", "copa_america_2024"],
        "team1": ["Argentina", "Argentina"],
        "team2": ["Canada", "Canada"],
        "target": [0, 0],
        "p0": [0.6, 0.6], "p1": [0.25, 0.25], "p2": [0.15, 0.15],
    })
    odds = pd.DataFrame({
        "tournament": ["copa_america_2024", "copa_america_2024"],
        "date": ["2024-07-09", "2024-06-20"],   # out of order on purpose
        "home": ["Argentina", "Argentina"], "away": ["Canada", "Canada"],
        "odds_home": [1.4, 1.6], "odds_draw": [4.5, 4.0], "odds_away": [9.0, 6.0],
    })
    m = align(preds, odds)
    assert len(m) == 2  # both rematches matched, not collapsed
    earliest = devig(1.6, 4.0, 6.0)  # the 06-20 opener (sorted first)
    assert (m.iloc[0]["k_p0"], m.iloc[0]["k_p1"], m.iloc[0]["k_p2"]) == pytest.approx(earliest)

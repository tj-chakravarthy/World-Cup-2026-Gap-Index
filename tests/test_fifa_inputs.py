"""Real FIFA ranking + conduct loaders for the Art. 13 group tiebreakers (monte_carlo).

The simulator loads these at run time and falls back to the Elo-order proxy (ranking) or
zero (conduct) when the data isn't present — these guard that contract.
"""

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("scipy")
pytest.importorskip("sklearn")  # monte_carlo's import chain pulls in sklearn (CI dev subset lacks it)

from src.models.monte_carlo import load_conduct, load_fifa_rankings  # noqa: E402


def test_load_fifa_rankings_full_coverage(tmp_path):
    p = tmp_path / "fifa.csv"
    pd.DataFrame({"fifa_code": ["ESP", "FRA", "ARG"], "rank": [1, 2, 3],
                  "points": [1875.4, 1870.9, 1870.3]}).to_csv(p, index=False)
    assert load_fifa_rankings(["ESP", "FRA", "ARG"], p) == {"ESP": 1, "FRA": 2, "ARG": 3}


def test_load_fifa_rankings_partial_returns_none(tmp_path):
    # a requested code missing from the file -> None, so the caller uses the Elo proxy
    # rather than a half-real ranking
    p = tmp_path / "fifa.csv"
    pd.DataFrame({"fifa_code": ["ESP", "FRA"], "rank": [1, 2],
                  "points": [1.0, 2.0]}).to_csv(p, index=False)
    assert load_fifa_rankings(["ESP", "FRA", "ARG"], p) is None


def test_load_fifa_rankings_missing_file(tmp_path):
    assert load_fifa_rankings(["ESP"], tmp_path / "nope.csv") is None


def test_load_conduct_sums_card_deductions(tmp_path):
    p = tmp_path / "cards.csv"
    pd.DataFrame([
        {"fixture_id": "WC26-M001", "team_code": "ESP", "yellow": 2,
         "indirect_red": 0, "direct_red": 0, "yellow_and_direct_red": 0},
        {"fixture_id": "WC26-M050", "team_code": "ESP", "yellow": 1,
         "indirect_red": 0, "direct_red": 1, "yellow_and_direct_red": 0},
        {"fixture_id": "WC26-M001", "team_code": "CRO", "yellow": 0,
         "indirect_red": 0, "direct_red": 0, "yellow_and_direct_red": 0},
    ]).to_csv(p, index=False)
    out = load_conduct(p)
    assert out["ESP"] == -7   # 3 yellows (-3) + 1 direct red (-4)
    assert out["CRO"] == 0


def test_load_conduct_missing_file_is_empty(tmp_path):
    assert load_conduct(tmp_path / "nope.csv") == {}

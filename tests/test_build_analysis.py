"""Static site analysis builder (src/pipeline/build_analysis.py).

Drives the bottom tabs (Gap Index, Players, Calibration, Model). Build from stub CSVs so the
transforms are covered without the gitignored scrapes: completed-tournament filter, gap sort,
R², market-value scaling.
"""

import pytest

pd = pytest.importorskip("pandas")

from src.pipeline import build_analysis  # noqa: E402


def _seed(proc, monkeypatch):
    monkeypatch.setattr(build_analysis, "PROC", proc)
    pd.DataFrame([
        # completed tournaments — kept; one over, one under
        {"tournament": "world_cup_2018", "country_code": "CRO", "team": "Croatia", "talent": 0.6,
         "ppg": 2.0, "expected_ppg": 0.7, "gap": 1.3, "gap_lo": 0.5, "gap_hi": 1.45, "n_games": 3},
        {"tournament": "euro_2020", "country_code": "TUR", "team": "Turkey", "talent": -0.2,
         "ppg": 0.0, "expected_ppg": 1.29, "gap": -1.29, "gap_lo": -1.38, "gap_hi": -0.28, "n_games": 3},
        # 2026 is partial -> excluded from the historical gap
        {"tournament": "world_cup_2026", "country_code": "ESP", "team": "Spain", "talent": 1.2,
         "ppg": 2.0, "expected_ppg": 1.8, "gap": 0.2, "gap_lo": -0.5, "gap_hi": 0.9, "n_games": 3},
    ]).to_csv(proc / "gap.csv", index=False)
    pd.DataFrame([
        {"country_code": "GER", "player_name": "Musiala", "position": "AM", "pos_group": "MF",
         "data_tier": 1, "market_value_eur": 140_000_000.0, "predicted_vaep": 0.4, "observed_pct": 0.9,
         "market_pct": 0.99, "predicted_pct": 0.95, "player_score": 99.4},
        {"country_code": "ESP", "player_name": "Pedri", "position": "CM", "pos_group": "MF",
         "data_tier": 1, "market_value_eur": 100_000_000.0, "predicted_vaep": 0.3, "observed_pct": 0.8,
         "market_pct": 0.95, "predicted_pct": 0.9, "player_score": 98.0},
    ]).to_csv(proc / "player_scores.csv", index=False)
    pd.DataFrame([
        {"feature_set": "Elo only", "n": 198, "brier": 0.594, "ci_lo": 0.562, "ci_hi": 0.617},
        {"feature_set": "+ market value", "n": 198, "brier": 0.5893, "ci_lo": 0.559, "ci_hi": 0.611},
    ]).to_csv(proc / "ablation.csv", index=False)
    pd.DataFrame([
        {"outcome": "team1 win", "bin_lo": 0.4, "n": 68, "pred_mean": 0.503, "obs_rate": 0.574},
        {"outcome": "draw", "bin_lo": 0.2, "n": 156, "pred_mean": 0.223, "obs_rate": 0.282},
    ]).to_csv(proc / "calibration_reliability.csv", index=False)


def test_build_shapes_and_transforms(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    out = build_analysis.build()

    gap = out["gap"]
    assert gap["n_teams"] == 2                                  # world_cup_2026 excluded
    assert [t["code"] for t in gap["teams"]] == ["CRO", "TUR"]  # sorted gap desc (over -> under)
    assert isinstance(gap["r2"], float)

    assert [p["name"] for p in out["players"]] == ["Musiala", "Pedri"]  # score desc
    assert out["players"][0]["mv"] == 140.0                     # eur -> millions

    assert out["ablation"]["n"] == 198
    assert any(r["set"] == "+ market value" for r in out["ablation"]["rows"])
    assert len(out["calibration"]) == 2


def test_missing_market_value_is_null(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    pd.DataFrame([
        {"country_code": "BRA", "player_name": "X", "position": "FW", "pos_group": "FW",
         "data_tier": 3, "market_value_eur": None, "predicted_vaep": 0.1, "observed_pct": None,
         "market_pct": None, "predicted_pct": 0.5, "player_score": 50.0},
    ]).to_csv(tmp_path / "player_scores.csv", index=False)
    assert build_analysis.build()["players"][0]["mv"] is None

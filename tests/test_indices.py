"""Squad composite indices (PLAN.md §3). Pure-function coverage."""

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("sklearn")

from src.features.indices import (  # noqa: E402
    INDEX_COLS, team_raw_indices, zscore_within)


def _squad():
    # 1 GK, 4 DF, 4 MF, 3 FW; vaep present for most, market value for all
    return pd.DataFrame({
        "pos_group": ["GK"] + ["DF"] * 4 + ["MF"] * 4 + ["FW"] * 3,
        "vaep_per90_pred": [0.05, 0.1, 0.12, 0.08, None, 0.2, 0.25, 0.22, 0.18,
                            0.3, 0.35, 0.28],
        "market_value_eur": [5e6, 10e6, 20e6, 8e6, 6e6, 40e6, 50e6, 30e6, 25e6,
                             80e6, 90e6, 60e6],
        "caps": [20, 30, 40, 10, 5, 50, 60, 25, 15, 70, 80, 35],
        "age": [30, 28, 27, 24, 22, 29, 26, 25, 23, 27, 28, 24],
        "club": ["A", "A", "B", "C", "D", "A", "E", "F", "G", "H", "I", "J"],
        "minutes_90s": [30, 32, 28, 20, 5, 34, 30, 25, 18, 33, 31, 22],
    })


def test_team_raw_indices_position_aggregates():
    out = team_raw_indices(_squad(), elo=1800.0)
    assert set(INDEX_COLS).issubset(out)
    # ATK = mean of the top-3 FW predicted VAEP (0.30, 0.35, 0.28)
    assert out["ATK"] == pytest.approx((0.30 + 0.35 + 0.28) / 3)
    # GK index = the single keeper's value
    assert out["GK"] == pytest.approx(0.05)
    assert out["ELO"] == 1800.0
    # COV = share of squad with predicted VAEP (11 of 12)
    assert out["COV"] == pytest.approx(11 / 12)
    # COH = 1 - unique_clubs/n (club A appears 3x; 10 unique of 12)
    assert out["COH"] == pytest.approx(1 - 10 / 12)


def test_zscore_within_standardises():
    df = pd.DataFrame({"ATK": [1.0, 2.0, 3.0], "MKT": [10.0, 10.0, 10.0]})
    z = zscore_within(df, ["ATK", "MKT"])
    assert z["ATK"].mean() == pytest.approx(0.0)
    assert z["ATK"].std(ddof=0) == pytest.approx(1.0)
    # constant column -> centered to 0, not divided by zero
    assert (z["MKT"] == 0.0).all()


def test_zscore_within_handles_all_nan_column():
    df = pd.DataFrame({"MKT": [float("nan")] * 3, "ELO": [1.0, 2.0, 3.0]})
    z = zscore_within(df, ["MKT", "ELO"])
    assert z["MKT"].isna().all()  # no value to standardise, left NaN

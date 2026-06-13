"""Player feature/percentile layer (PLAN.md §2.3 / §3). In-memory, no files."""

import pytest

pd = pytest.importorskip("pandas")

from src.features.player_features import available_features, build_features, position_group  # noqa: E402


def test_position_group_takes_primary():
    assert position_group("FW,MF") == "FW"
    assert position_group("DF") == "DF"
    assert position_group("") == "NA" and position_group(None) == "NA"


def test_available_features_skips_empty_advanced():
    df = pd.DataFrame({
        "goals_per90": [0.5, 0.1],
        "defense_blocks": [None, None],   # present but withheld -> empty
    })
    assert available_features(df) == ["goals_per90"]


def test_percentile_within_season_and_position_respects_minutes():
    df = pd.DataFrame({
        "season": ["2023-2024"] * 4,
        "position": ["FW", "FW", "FW", "DF"],
        "minutes_90s": [20, 20, 1, 20],          # third FW below the 5x90 cutoff
        "goals_per90": [0.9, 0.3, 5.0, 0.2],
    })
    out = build_features(df, min_90s=5.0)
    fw = out[out.position == "FW"].set_index("goals_per90")
    # among eligible FWs (0.9, 0.3) the higher rate ranks top; low-minutes FW gets no pct
    assert fw.loc[0.9, "goals_per90_pct"] == 1.0
    assert fw.loc[0.3, "goals_per90_pct"] == 0.5
    assert pd.isna(fw.loc[5.0, "goals_per90_pct"])
    # the lone DF is normalised within its own group
    assert out[out.position == "DF"]["goals_per90_pct"].iloc[0] == 1.0

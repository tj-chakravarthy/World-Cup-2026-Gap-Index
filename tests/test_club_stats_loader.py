"""FBref club-stats merge (Stage 2 input contract). In-memory, no files.
Columns are FBref data-stat keys (player, team, minutes, shots, …)."""

import pytest

pd = pytest.importorskip("pandas")

from src.features.club_stats import merge_stats, merge_understat_xg  # noqa: E402


def _frame(stat, **extra):
    base = {
        "player": ["Erling Haaland", "Bukayo Saka"],
        "team": ["Manchester City", "Arsenal"],
        "nationality": ["no NOR", "eng ENG"], "position": ["FW", "FW"],
        "age": ["23", "22"], "birth_year": ["2000", "2001"],
        "minutes_90s": ["28.4", "33.0"],
        "stat_type": [stat, stat], "league": ["ENG", "ENG"],
        "season": ["2023-2024", "2023-2024"],
    }
    base.update(extra)
    return pd.DataFrame(base)


def test_merge_joins_prefixes_and_drops_shared():
    standard = _frame("standard", minutes=["2552", "3000"], goals=["27", "16"])
    shooting = _frame("shooting", shots=["120", "90"], xg=["29.1", "12.0"])
    out = merge_stats({"standard": standard, "shooting": shooting})

    assert len(out) == 2
    # standard metrics stay unprefixed; identity carried once
    assert out.loc[out.player == "Erling Haaland", "goals"].iloc[0] == "27"
    # shooting metrics prefixed and joined to the right player
    assert "shooting_shots" in out.columns and "shooting_xg" in out.columns
    assert out.loc[out.player == "Erling Haaland", "shooting_shots"].iloc[0] == "120"
    # shared minutes_90s dropped (standard owns it), identity not re-prefixed
    assert "shooting_minutes_90s" not in out.columns
    assert "shooting_nationality" not in out.columns
    # folded join name added next to player
    assert out.loc[out.player == "Erling Haaland", "player_name_norm"].iloc[0] == "erling haaland"


def test_merge_requires_standard_base():
    with pytest.raises(ValueError, match="standard"):
        merge_stats({"shooting": _frame("shooting", shots=["1", "2"])})


def test_merge_understat_xg_sums_per_season_and_per90(tmp_path):
    # two rows for one player (a mid-season transfer) in season-start-year 2023 ->
    # 2023-2024; summed then per-90. 1800 min = 20 nineties; xG 15 -> 0.75/90.
    us = pd.DataFrame({
        "player_name": ["Erling Haaland", "Erling Haaland"], "time": [900, 900],
        "xG": [10.0, 5.0], "npxG": [9, 4], "xA": [2, 1], "shots": [40, 20],
        "key_passes": [10, 5], "xGChain": [12, 6], "xGBuildup": [3, 1],
    })
    (tmp_path / "understat_EPL_2023.csv").write_text(us.to_csv(index=False))
    # a season not in the map must be ignored
    (tmp_path / "understat_EPL_2099.csv").write_text(us.to_csv(index=False))

    fbref = pd.DataFrame({"player": ["Erling Haaland", "Unmatched Guy"],
                          "player_name_norm": ["erling haaland", "unmatched guy"],
                          "season": ["2023-2024", "2023-2024"]})
    out = merge_understat_xg(fbref, raw_dir=tmp_path)
    h = out.set_index("player_name_norm")
    assert h.loc["erling haaland", "us_xg_per90"] == pytest.approx(15 / (1800 / 90))
    assert h.loc["erling haaland", "us_xa_per90"] == pytest.approx(3 / (1800 / 90))
    assert pd.isna(h.loc["unmatched guy", "us_xg_per90"])  # no Understat row -> NaN

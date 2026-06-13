"""FBref club-stats merge (Stage 2 input contract). In-memory, no files.
Columns are FBref data-stat keys (player, team, minutes, shots, …)."""

import pytest

pd = pytest.importorskip("pandas")

from src.features.club_stats import merge_stats  # noqa: E402


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

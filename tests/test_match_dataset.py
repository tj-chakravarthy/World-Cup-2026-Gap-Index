"""Match training-set assembly (PLAN.md §4.1). Pure-function coverage."""

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("sklearn")

from src.features.indices import INDEX_COLS  # noqa: E402
from src.models.match_dataset import (  # noqa: E402
    build_match_dataset, feature_columns, outcome)


def test_outcome_three_class():
    assert outcome(2, 1) == 0  # team1 win
    assert outcome(1, 1) == 1  # draw
    assert outcome(0, 3) == 2  # team1 loss


def test_feature_columns_cover_levels_and_diffs():
    cols = feature_columns()
    for c in INDEX_COLS:
        assert f"{c}1" in cols and f"{c}2" in cols and f"{c}_diff" in cols
    assert len(cols) == 3 * len(INDEX_COLS)


def _indices():
    base = {c: 0.0 for c in INDEX_COLS}
    rows = []
    for team, atk in [("Alpha", 1.0), ("Beta", -1.0)]:
        rows.append({"tournament": "world_cup_2018", "team": team, **{**base, "ATK": atk}})
    return pd.DataFrame(rows)


def _results():
    return pd.DataFrame({
        "date": ["2018-06-20"], "home_team": ["Alpha"], "away_team": ["Beta"],
        "home_score": [2.0], "away_score": [0.0], "tournament": ["FIFA World Cup"],
    })


def test_build_dataset_swap_augments_and_flips_target():
    ds = build_match_dataset(_indices(), _results(), tournaments=["world_cup_2018"])
    assert len(ds) == 2  # one fixture, both orderings
    # original: Alpha (team1) beat Beta -> target 0; ATK_diff = 1 - (-1) = 2
    orig = ds[ds.team1 == "Alpha"].iloc[0]
    assert orig["target"] == 0 and orig["ATK_diff"] == pytest.approx(2.0)
    # swapped: Beta as team1 lost -> target 2; ATK_diff flips sign
    swap = ds[ds.team1 == "Beta"].iloc[0]
    assert swap["target"] == 2 and swap["ATK_diff"] == pytest.approx(-2.0)


def test_build_dataset_skips_non_participants():
    res = _results()
    res.loc[0, "away_team"] = "Gamma"  # not in the index set -> fixture skipped
    ds = build_match_dataset(_indices(), res, tournaments=["world_cup_2018"])
    assert len(ds) == 0

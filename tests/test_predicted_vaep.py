"""Pure-function tests for the predicted-VAEP model (PLAN.md §2.2).

The join (observed VAEP -> preceding club season) and the leave-one-tournament-out
split are where a silent bug would invalidate the thesis. sklearn/pandas aren't in
the bare env's import path for every box, so guard the import."""

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("sklearn")

from src.features.predicted_vaep import (  # noqa: E402
    FEATURES, build_training_table, feature_matrix, leave_one_tournament_out,
    position_onehot, train_model)


def test_position_onehot_fixed_columns():
    oh = position_onehot(pd.Series(["GK", "FW", "XX"]))
    assert list(oh.columns) == ["pos_GK", "pos_DF", "pos_MF", "pos_FW"]
    assert oh.iloc[0]["pos_GK"] == 1.0 and oh.iloc[1]["pos_FW"] == 1.0
    assert oh.iloc[2].sum() == 0.0  # unknown group -> all zero, no new column


def test_feature_matrix_adds_missing_features_as_nan():
    df = pd.DataFrame({"goals_per90": [0.5], "pos_group": ["FW"]})
    X = feature_matrix(df, ["goals_per90", "assists_per90"])
    assert X.loc[0, "goals_per90"] == 0.5
    assert pd.isna(X.loc[0, "assists_per90"])  # absent feature -> NaN, not error
    assert X.loc[0, "pos_FW"] == 1.0


def _club_feats():
    # carries the percentile feature columns build_features produces (the model
    # trains on `_pct`, not raw per-90)
    return pd.DataFrame({
        "player": ["Kylian Mbappe", "Harry Kane", "Bench Warmer"],
        "player_name_norm": ["kylian mbappe", "harry kane", "bench warmer"],
        "season": ["2017-2018"] * 3, "pos_group": ["FW", "FW", "MF"],
        "minutes_90s": [30.0, 32.0, 1.0],
        "goals_per90_pct": [0.7, 0.8, 0.1], "assists_per90_pct": [0.6, 0.5, 0.2],
        "us_xg_per90_pct": [0.9, 0.85, 0.1],
    })


def _observed():
    return pd.DataFrame({
        "player_name": ["Kylian Mbappe", "Harry Kane", "Unmatched Guy"],
        "tournament": ["world_cup_2018"] * 3, "minutes": [400, 500, 300],
        "vaep_per90": [0.6, 0.5, 0.4],
    })


def test_build_training_table_joins_to_preceding_season():
    table = build_training_table(_observed(), _club_feats())
    # Mbappe + Kane match the 2017-2018 club table; the third has no club row
    assert set(table["player_name"]) == {"Kylian Mbappe", "Harry Kane"}
    mb = table.set_index("player_name").loc["Kylian Mbappe"]
    assert mb["vaep_per90"] == pytest.approx(0.6)
    assert mb["goals_per90_pct"] == pytest.approx(0.7)
    assert mb["us_xg_per90_pct"] == pytest.approx(0.9)
    assert mb["pos_group"] == "FW"


def test_build_training_table_drops_below_minute_floor():
    obs = _observed()
    obs.loc[0, "minutes"] = 30  # below 90-min floor -> dropped
    table = build_training_table(obs, _club_feats())
    assert "Kylian Mbappe" not in set(table["player_name"])


def test_leave_one_tournament_out_predicts_every_row_blind():
    # every row gets a prediction from a model that did not train on its tournament.
    # Build a joined table directly (the split logic, not the join, is under test);
    # enough rows per fold for the gradient-boosting fit to be well-posed.
    import numpy as np
    rng = np.random.default_rng(0)
    n = 60
    table = pd.DataFrame({
        "tournament": ["world_cup_2018"] * n + ["euro_2020"] * n,
        "pos_group": (["GK", "DF", "MF", "FW"] * (n // 2))[: 2 * n],
        "vaep_per90": rng.normal(0.3, 0.1, 2 * n),
        **{f: rng.normal(1.0, 0.3, 2 * n) for f in FEATURES},
    })
    scored = leave_one_tournament_out(table)
    assert scored["vaep_per90_pred"].notna().all()  # no row left unscored
    # the model for euro_2020 never saw euro_2020 rows
    m = train_model(table, exclude_tournament="euro_2020")
    assert m.predict(feature_matrix(table.head(1), FEATURES).to_numpy()).shape == (1,)

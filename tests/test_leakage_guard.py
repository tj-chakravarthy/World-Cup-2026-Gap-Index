"""Nested-CV leakage guard — MANDATORY (PLAN.md §4.5 / §2.2).

The fitted rating stack (predicted-VAEP model -> indices) must be refit on
`train_only` data inside each fold: the held-out tournament may not inform the
features used to predict it. A single un-nested step silently inflates every
headline number. src/models/evaluate.py now exists, so this guard is live: it
asserts the per-fold predicted-VAEP training table excludes the held-out tournament.
"""

import os

import pytest

# MANDATORY test (pyproject markers: "skipped == not enforced"). In CI a missing dep is a
# hard failure, never a silent skip — otherwise "leakage guard enforced in CI" is false;
# locally it skips for devs without the modelling stack.
if os.environ.get("CI"):
    import pandas as pd
    import sklearn  # noqa: F401  (evaluate.py imports it; ImportError here fails CI loudly)
else:
    pd = pytest.importorskip("pandas")
    pytest.importorskip("sklearn")

from src.models.evaluate import FOLDS, fold_training_table  # noqa: E402


def _observed():
    # observed VAEP rows for two tournaments; same two players in each
    rows = []
    for t in ("world_cup_2018", "euro_2020"):
        for name, v in [("Harry Kane", 0.5), ("Raheem Sterling", 0.4)]:
            rows.append({"player_name": name, "tournament": t, "minutes": 400,
                         "vaep_per90": v})
    return pd.DataFrame(rows)


def _club_feats():
    # the players' club rows in BOTH preceding seasons, so a match is possible
    rows = []
    for season in ("2017-2018", "2020-2021"):
        for name, norm in [("Harry Kane", "harry kane"),
                           ("Raheem Sterling", "raheem sterling")]:
            rows.append({"player": name, "player_name_norm": norm, "season": season,
                         "pos_group": "FW", "minutes_90s": 30.0,
                         "goals_per90_pct": 0.9, "us_xg_per90_pct": 0.9})
    return pd.DataFrame(rows)


@pytest.mark.mandatory
def test_fold_training_table_excludes_held_out_tournament():
    observed, club = _observed(), _club_feats()
    # holding out euro_2020, no euro_2020 row may reach the predicted-VAEP refit
    table = fold_training_table(observed, club, exclude=["euro_2020"])
    assert "euro_2020" not in set(table["tournament"])
    assert "world_cup_2018" in set(table["tournament"])  # the train tournament stays


@pytest.mark.mandatory
def test_every_fold_holds_out_its_test_tournaments():
    # each fold's train set and test set are disjoint (forward-chaining, no overlap)
    for train_t, test_t in FOLDS:
        assert not (set(train_t) & set(test_t))

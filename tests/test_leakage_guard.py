"""Nested-CV leakage guard — MANDATORY (PLAN.md §4.5 / §2.2).

Assert the entire rating pipeline (predicted VAEP -> composite scores ->
index z-scoring) is a function of `train_only` data inside each fold. A single
un-nested step silently inflates every headline number.

Tripwire: the guard can't be implemented until the fold loop exists, so it is
skipped until then — but the moment `src/models/evaluate.py` lands (the temporal
CV / backtest home, PLAN.md repo map) this test turns live and FAILS until the
guard is written. That way a mandatory contract can't sit silently skipped once
the code it guards is in the tree.
"""

import importlib.util

import pytest

_FOLD_LOOP_BUILT = importlib.util.find_spec("src.models.evaluate") is not None


@pytest.mark.mandatory
@pytest.mark.skipif(not _FOLD_LOOP_BUILT,
                    reason="MANDATORY, not yet enforceable — fold loop (src/models/evaluate.py) not built (PLAN.md §4.5)")
def test_rating_pipeline_is_train_only_per_fold():
    pytest.fail("src.models.evaluate exists — implement the nested-CV leakage "
                "guard now (rating pipeline must be train_only per fold, PLAN.md §4.5)")

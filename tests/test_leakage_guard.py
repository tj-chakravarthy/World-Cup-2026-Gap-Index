"""Nested-CV leakage guard — MANDATORY (PLAN.md §4.5 / §2.2).

Assert the entire rating pipeline (predicted VAEP -> composite scores ->
index z-scoring) is a function of `train_only` data inside each fold. A single
un-nested step silently inflates every headline number.
"""

import pytest


@pytest.mark.mandatory
@pytest.mark.skip(reason="MANDATORY contract NOT YET ENFORCED — implement once the fold loop exists (PLAN.md §4.5)")
def test_rating_pipeline_is_train_only_per_fold():
    raise NotImplementedError

"""Scoreline coherence — MANDATORY (PLAN.md §5.2).

After the Dixon-Coles lambda-tilt, simulated W/D/L frequencies must match the
stacked W/D/L marginals within Monte Carlo error. Coherence is achieved by
tilting C's lambdas, never by ad-hoc reweighting of scoreline cells.
"""

import pytest


@pytest.mark.skip(reason="TODO: implement with src/models/monte_carlo.py (PLAN.md §5.2)")
def test_simulated_marginals_match_stacked():
    raise NotImplementedError

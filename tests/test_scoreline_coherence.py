"""Scoreline coherence — MANDATORY (PLAN.md §5.2).

After the Dixon-Coles lambda-tilt, simulated W/D/L frequencies must match the
stacked W/D/L marginals within Monte Carlo error. Coherence is achieved by
tilting C's lambdas, never by ad-hoc reweighting of scoreline cells.

Tripwire: skipped until the simulator exists, then turns live and FAILS the
moment `src/models/monte_carlo.py` lands — so this mandatory contract can't stay
silently skipped once the code it guards is in the tree.
"""

import importlib.util

import pytest

_SIM_BUILT = importlib.util.find_spec("src.models.monte_carlo") is not None


@pytest.mark.mandatory
@pytest.mark.skipif(not _SIM_BUILT,
                    reason="MANDATORY, not yet enforceable — simulator (src/models/monte_carlo.py) not built (PLAN.md §5.2)")
def test_simulated_marginals_match_stacked():
    pytest.fail("src.models.monte_carlo exists — implement the scoreline-coherence "
                "guard now (sim W/D/L must match stacked marginals via lambda-tilt, PLAN.md §5.2)")

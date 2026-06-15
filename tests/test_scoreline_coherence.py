"""Scoreline coherence — MANDATORY (PLAN.md §5.2).

After the Dixon-Coles lambda-tilt, the scoreline joint must imply the target W/D/L
marginals, and scorelines sampled from it must reproduce those marginals within Monte
Carlo error. Coherence is achieved by tilting the lambdas (a proper Dixon-Coles joint),
never by ad-hoc reweighting of scoreline cells. scoreline.py is the mechanism; this is
its guard (live, not a tripwire).
"""

import numpy as np
import pytest

pytest.importorskip("scipy")

from src.models.scoreline import (  # noqa: E402
    matrix_wdl, sample_scorelines, score_matrix, tilt_rates, tilted_matrix)

RHO = -0.05  # a typical fitted Dixon-Coles low-score correction


@pytest.mark.mandatory
@pytest.mark.parametrize("target", [(0.55, 0.25, 0.20), (0.40, 0.30, 0.30),
                                    (0.75, 0.17, 0.08), (0.20, 0.26, 0.54)])
def test_tilt_hits_target_marginals(target):
    # base rates of a roughly even fixture, tilted to the (possibly lopsided) target
    l1, l2 = tilt_rates(1.3, 1.2, RHO, target)
    h, d, a = matrix_wdl(score_matrix(l1, l2, RHO))
    assert h == pytest.approx(target[0], abs=0.015)
    assert a == pytest.approx(target[2], abs=0.015)
    assert (h + d + a) == pytest.approx(1.0, abs=1e-6)


@pytest.mark.mandatory
def test_sampled_scorelines_match_marginals_within_mc_error():
    target = (0.55, 0.25, 0.20)
    m = tilted_matrix(1.3, 1.2, RHO, target)
    rng = np.random.default_rng(0)
    hg, ag = sample_scorelines(m, rng, 40000)
    win = float((hg > ag).mean())
    draw = float((hg == ag).mean())
    loss = float((hg < ag).mean())
    # within Monte Carlo error of the tilted joint's marginals
    assert win == pytest.approx(target[0], abs=0.02)
    assert draw == pytest.approx(target[1], abs=0.02)
    assert loss == pytest.approx(target[2], abs=0.02)


def test_tilt_preserves_a_proper_joint():
    # the tilted matrix is a normalised probability joint (no negative cells)
    m = tilted_matrix(1.6, 0.9, RHO, (0.5, 0.25, 0.25))
    assert (m >= 0).all()
    assert m.sum() == pytest.approx(1.0, abs=1e-9)

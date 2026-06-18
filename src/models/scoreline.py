"""Scoreline model + coherence tilt (PLAN.md §5.2).

Dixon-Coles owns the scoreline joint; the calibrated match model (match_model.py) owns
the W/D/L marginals. To make simulated scorelines agree with those marginals we TILT
Dixon-Coles' expected goals (the lambdas) until its implied P(W/D/L) matches the target
— a 2-parameter solve per fixture (a total-goals scale and a home/away balance) — then
sample scorelines from the tilted joint. We tilt the lambdas, never ad-hoc-reweight the
scoreline cells: reweighting cells to hit marginals produces an incoherent joint; tilting
lambdas keeps a proper Dixon-Coles distribution (the low-score rho correction rides
along unchanged). scipy + numpy.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson


def score_matrix(lam1: float, lam2: float, rho: float, max_goals: int = 10) -> np.ndarray:
    """M[i, j] = P(team1 i, team2 j) over 0..max_goals, Dixon-Coles tau-corrected and
    renormalised. Same form as DCModel.scoreline_matrix, but on raw rates so the tilt
    can drive it."""
    k = np.arange(max_goals + 1)
    m = np.outer(poisson.pmf(k, lam1), poisson.pmf(k, lam2))
    m[0, 0] *= 1.0 - lam1 * lam2 * rho
    m[0, 1] *= 1.0 + lam1 * rho
    m[1, 0] *= 1.0 + lam2 * rho
    m[1, 1] *= 1.0 - rho
    m = np.clip(m, 0.0, None)
    return m / m.sum()


def matrix_wdl(m: np.ndarray) -> tuple[float, float, float]:
    """(team1 win, draw, team2 win) from a scoreline matrix."""
    return float(np.tril(m, -1).sum()), float(np.trace(m)), float(np.triu(m, 1).sum())


def tilt_rates(lam1: float, lam2: float, rho: float, target_wdl,
               max_goals: int = 10) -> tuple[float, float]:
    """Tilted (lam1', lam2') whose scoreline matrix implies `target_wdl` (home, draw,
    away). Parameterise lam1' = lam1*exp(s+d), lam2' = lam2*exp(s-d): s scales total
    goals (trades draws for decisiveness), d shifts the home/away balance. Solve the
    2 free targets (home, away); draw follows by normalisation."""
    th, _, ta = target_wdl

    def loss(x):
        s, d = x
        m = score_matrix(lam1 * np.exp(s + d), lam2 * np.exp(s - d), rho, max_goals)
        h, _, a = matrix_wdl(m)
        return (h - th) ** 2 + (a - ta) ** 2

    res = minimize(loss, [0.0, 0.0], method="Nelder-Mead",
                   options={"xatol": 1e-5, "fatol": 1e-10, "maxiter": 1000})
    if not res.success:
        return lam1, lam2   # no reliable tilt -> the untilted DC rates (still a proper joint)
    s, d = res.x
    return lam1 * np.exp(s + d), lam2 * np.exp(s - d)


def sample_scorelines(m: np.ndarray, rng: np.random.Generator, n: int):
    """Vectorised draw of n scorelines from a scoreline matrix. Returns (home, away)
    integer goal arrays."""
    side = m.shape[0]
    idx = rng.choice(side * side, size=n, p=m.ravel())
    return idx // side, idx % side


def tilted_matrix(lam1: float, lam2: float, rho: float, target_wdl,
                  max_goals: int = 10) -> np.ndarray:
    """Convenience: the scoreline matrix after tilting to `target_wdl` (what the sim
    precomputes per fixture, then samples many times)."""
    l1, l2 = tilt_rates(lam1, lam2, rho, target_wdl, max_goals)
    return score_matrix(l1, l2, rho, max_goals)

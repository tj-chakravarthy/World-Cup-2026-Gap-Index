"""Dixon-Coles bivariate-Poisson goals model — thin Stage-0 version (member C).

Dixon & Coles (1997): two independent Poissons for the two scorelines plus a
low-score dependence correction (the tau adjustment on the 0-0/0-1/1-0/1-1
cells). The full model in PLAN.md §4.2 drives attack/defence off the squad
indices; the thin lock has no indices yet, so this is the classic per-team
version — attack/defence are free parameters fit from goals alone.

Fit is two-step (standard, fast, numpy/scipy only so it runs in plain CI):
  1. weighted double-Poisson GLM — intercept, home advantage, per-team attack
     and defence — by L-BFGS-B with an analytic gradient. Convex; a small ridge
     on attack/defence pins the redundant shift directions and shrinks
     thin-data teams toward the field average.
  2. rho (low-score correction) by a 1-D solve on the four low cells, holding
     the rates from step 1 fixed.

Sample weights are exponential time decay (PLAN.md §1.4); home advantage is
learned only from non-neutral matches and applied as 0 on neutral venues, so
World Cup fixtures are predicted neutral. Importance weighting is left to the
full model — the thin lock weights by recency only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
from scipy.optimize import minimize, minimize_scalar
from scipy.stats import poisson


def _tau(hg: np.ndarray, ag: np.ndarray, lam: np.ndarray, mu: np.ndarray,
         rho: float) -> np.ndarray:
    """Dixon-Coles low-score correction for arrays of (home, away) goals."""
    t = np.ones_like(lam, dtype=float)
    t = np.where((hg == 0) & (ag == 0), 1.0 - lam * mu * rho, t)
    t = np.where((hg == 0) & (ag == 1), 1.0 + lam * rho, t)
    t = np.where((hg == 1) & (ag == 0), 1.0 + mu * rho, t)
    t = np.where((hg == 1) & (ag == 1), 1.0 - rho, t)
    return t


@dataclass(frozen=True)
class DCModel:
    intercept: float
    home_adv: float
    attack: dict[str, float]
    defence: dict[str, float]
    rho: float
    max_goals: int = 10

    def rates(self, team1: str, team2: str, neutral: bool = True) -> tuple[float, float]:
        """Expected goals (lambda1, lambda2). team1 carries the home term, applied
        only off-neutral; World Cup fixtures are neutral so it drops out."""
        h = self.home_adv if not neutral else 0.0
        lam1 = np.exp(self.intercept + self.attack[team1] - self.defence[team2] + h)
        lam2 = np.exp(self.intercept + self.attack[team2] - self.defence[team1])
        return float(lam1), float(lam2)

    def scoreline_matrix(self, team1: str, team2: str, neutral: bool = True) -> np.ndarray:
        """M[i, j] = P(team1 scores i, team2 scores j), tau-corrected and
        renormalised over the 0..max_goals grid."""
        lam1, lam2 = self.rates(team1, team2, neutral)
        k = np.arange(self.max_goals + 1)
        m = np.outer(poisson.pmf(k, lam1), poisson.pmf(k, lam2))
        m[0, 0] *= 1.0 - lam1 * lam2 * self.rho
        m[0, 1] *= 1.0 + lam1 * self.rho
        m[1, 0] *= 1.0 + lam2 * self.rho
        m[1, 1] *= 1.0 - self.rho
        m = np.clip(m, 0.0, None)
        return m / m.sum()

    def predict(self, team1: str, team2: str, neutral: bool = True,
                top_n: int = 5) -> dict:
        """W/D/L marginals (order-invariant) + the top_n most likely scorelines."""
        m = self.scoreline_matrix(team1, team2, neutral)
        wdl = {
            "team1": float(np.tril(m, -1).sum()),  # team1 scores more
            "draw": float(np.trace(m)),
            "team2": float(np.triu(m, 1).sum()),
        }
        idx = np.dstack(np.unravel_index(np.argsort(m, axis=None)[::-1], m.shape))[0]
        scorelines = [
            {"score": f"{int(i)}-{int(j)}", "p": round(float(m[i, j]), 4)}
            for i, j in idx[:top_n]
        ]
        return {"wdl": wdl, "scorelines": scorelines}


def fit(matches, *, ref_date: str | None = None, half_life_days: float = 730.0,
        min_date: str = "2018-01-01", reg: float = 1e-2, max_goals: int = 10) -> DCModel:
    """Fit from `matches` = iterable of (date 'YYYY-MM-DD', home, away, home_goals,
    away_goals, neutral_bool). Rows before `min_date` are dropped; the rest are
    exponentially recency-weighted to `ref_date` (default: latest date present)."""
    rows = [m for m in matches if m[0] >= min_date]
    if not rows:
        raise ValueError("no matches after min_date")

    dates = [date.fromisoformat(m[0]) for m in rows]
    ref = date.fromisoformat(ref_date) if ref_date else max(dates)
    days_ago = np.array([max((ref - d).days, 0) for d in dates], dtype=float)
    w = 0.5 ** (days_ago / half_life_days)

    teams = sorted({t for m in rows for t in (m[1], m[2])})
    ix = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    hi = np.array([ix[m[1]] for m in rows])
    ai = np.array([ix[m[2]] for m in rows])
    hg = np.array([int(m[3]) for m in rows], dtype=float)
    ag = np.array([int(m[4]) for m in rows], dtype=float)
    home_on = np.array([0.0 if m[5] else 1.0 for m in rows])  # 1 = home adv applies

    # theta = [intercept, home_adv, attack(n), defence(n)]
    def unpack(theta):
        return theta[0], theta[1], theta[2:2 + n], theta[2 + n:]

    def nll_and_grad(theta):
        intercept, home_adv, att, dfn = unpack(theta)
        loglam_h = intercept + att[hi] - dfn[ai] + home_adv * home_on
        loglam_a = intercept + att[ai] - dfn[hi]
        lam_h, lam_a = np.exp(loglam_h), np.exp(loglam_a)
        nll = np.sum(w * (lam_h - hg * loglam_h)) + np.sum(w * (lam_a - ag * loglam_a))
        nll += 0.5 * reg * (att @ att + dfn @ dfn)

        rh = w * (lam_h - hg)
        ra = w * (lam_a - ag)
        g_int = rh.sum() + ra.sum()
        g_home = (rh * home_on).sum()
        g_att = np.bincount(hi, rh, n) + np.bincount(ai, ra, n) + reg * att
        g_dfn = -(np.bincount(ai, rh, n) + np.bincount(hi, ra, n)) + reg * dfn
        return nll, np.concatenate([[g_int, g_home], g_att, g_dfn])

    theta0 = np.zeros(2 + 2 * n)
    res = minimize(nll_and_grad, theta0, jac=True, method="L-BFGS-B")
    intercept, home_adv, att, dfn = unpack(res.x)

    # step 2: rho on the low-score cells, rates held fixed
    loglam_h = intercept + att[hi] - dfn[ai] + home_adv * home_on
    loglam_a = intercept + att[ai] - dfn[hi]
    lam_h, lam_a = np.exp(loglam_h), np.exp(loglam_a)
    low = (hg <= 1) & (ag <= 1)
    hgl, agl, lh, la, wl = hg[low], ag[low], lam_h[low], lam_a[low], w[low]

    def rho_nll(rho):
        t = _tau(hgl, agl, lh, la, rho)
        if np.any(t <= 1e-12):
            return np.inf
        return -np.sum(wl * np.log(t))

    rho = float(minimize_scalar(rho_nll, bounds=(-0.2, 0.2), method="bounded").x)

    return DCModel(
        intercept=float(intercept),
        home_adv=float(home_adv),
        attack={t: float(att[i]) for t, i in ix.items()},
        defence={t: float(dfn[i]) for t, i in ix.items()},
        rho=rho,
        max_goals=max_goals,
    )

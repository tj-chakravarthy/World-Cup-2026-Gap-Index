"""Elo-sigmoid baseline — member E (PLAN.md §4.2). Benchmark only, never in the
ensemble, so the "model vs Elo" comparison stays clean.

P(team1 beats team2) is the standard Elo sigmoid on the rating gap; the W/D/L
split needs a draw model. PLAN names one but specifies none, and we carry only
current Elo (no historical year-end ratings — see fetch_elo.py), so there is
nothing to fit a draw model against. We use a base draw rate measured from
results, damped toward zero as the gap widens (mismatches draw less). Crude and
documented: this is the benchmark, not the product.
"""

from __future__ import annotations


def win_prob(elo1: float, elo2: float) -> float:
    """P(team1 wins | decisive) from the rating gap — the standard Elo sigmoid."""
    return 1.0 / (1.0 + 10.0 ** (-(elo1 - elo2) / 400.0))


def elo_wdl(elo1: float, elo2: float, base_draw: float = 0.231) -> dict:
    """W/D/L for team1 vs team2. `base_draw` is the field draw rate; the draw
    share peaks at an even gap and shrinks to 0 in a blowout."""
    p = win_prob(elo1, elo2)
    draw = base_draw * (1.0 - (2.0 * p - 1.0) ** 2)
    rest = 1.0 - draw
    return {"team1": rest * p, "draw": draw, "team2": rest * (1.0 - p)}

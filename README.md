# World Cup 2026 — Gap Index

My calibrated machine-learning forecast of the 2026 World Cup, built to test: a
national team is just its club players, so does it perform as well as their club form
predicts? Rate every player from his club season, add them into a squad, compare to how the team actually plays — difference is the gap.

Each team carries two pre-tournament signals — national Elo (from 150 years of results) and
squad market value — and an L2 multinomial logistic (C=0.03), scored in both orderings and
averaged, turns each rating gap into a calibrated W/D/L (held-out ECE 0.054). Scorelines come
from a Dixon-Coles double-Poisson (L-BFGS-B, time-decayed, τ low-score correction), then a
2-parameter λ-tilt rescales total goals and balance until the matrix's implied W/D/L matches
the logistic — a CI-enforced coherence check. I Monte-Carlo the bracket 100,000 times — group
games drawn from the tilted matrix, the FIFA Article 13 tiebreaker order (real FIFA ranking; fair-play conduct still zero — no cards loaded — so it breaks no ties yet), the eight best thirds
into the round of 32, level knockouts to a ~50/50 shootout — for each team's odds of reaching
every stage. Every run draws one of 25 bootstrap refits, so the odds are distributions, not
point estimates; the model is cached and re-runs when new results are pulled.

Open-source, updating live during the tournament.

## The result

Two things pre-registered:

**1. A calibrated model — met.** On held-out tournaments the expected calibration error is 0.054: when it says 60%, it happens about 60% of the time.

**2. Does translated club talent beat the obvious baselines? — no.** That was the
hypothesis, and it is not supported. A leakage-guarded backtest (four held-out
tournaments, 2020–2024; the whole rating pipeline refit inside each forward-chaining fold,
WC 2018 only ever training) shows the player-talent indices add nothing over Elo + market
value:

| features | held-out Brier (lower is better) |
|---|---|
| Elo only | 0.594 |
| + market value | 0.589 |
| + player-talent indices | 0.596 |
| + everything else | 0.599 |

National Elo is already built from results, so it is a hard baseline to beat with squad composition.

For scale, the model's Brier (0.589) lands within 0.017 of the bookmaker closing line
(0.573) and ahead of Elo. The market prices lineup news and money the model excludes by rule, so beating it was never the goal.

The gap analysis still works as a description: talent explains about a third of results (R²≈0.30), and the residual is the story — Morocco 2022 over, Germany 2018 under, each with an uncertainty band (three group games is a tiny sample).

## The forecast

My model plays the whole tournament out in the 2026 format — 12 groups, 8 best third-placed
teams, the FIFA Article 13 group-tiebreaker order, the official knockout bracket. The order
— head-to-head, then goal difference, goals, team conduct, and the real FIFA/Coca-Cola ranking —
is implemented in full sequence, and the third-placed teams slot into the round of 32 by FIFA's
exact Annex C table. **Caveat, not buried:** one input isn't live yet — the team-conduct
(fair-play) score runs at **zero until match-card data is hand-loaded**, so fair-play currently
breaks no ties. Everything else in the order is active; conduct updates when new results are
pulled, once cards are entered.

<!-- TOPBOARD:START -->
Top of the board to win it: **France 15%, Argentina 14%, Spain 12%, England 12%.** _(updated 2026-07-02 02:08 UTC)_
<!-- TOPBOARD:END -->

## How it's built

All public data: 150 years of international results, national and club Elo, the 48 squads
(Wikipedia), club stats (FBref) and expected goals (Understat), past-tournament event data
for player VAEP (StatsBomb), 2026 fixtures, plus the FIFA/Coca-Cola world
ranking for the Article 13 final group tiebreaker. Betting odds I use only to score the model,
never as an input; the FIFA ranking enters only that tiebreaker (an Elo-based rank as fallback
when it isn't loaded), not the model either. Full source + license breakdown (committed vs
regenerated): [DATA_SOURCES.md](DATA_SOURCES.md).

The integrity:

- Predictions are committed to git and timestamped; scored predictions are all pre-kickoff. The
  append-only log keeps one historical post-kickoff row (WC26-M013, a lagging-feed re-log),
  excluded from scoring. The history is the record.
- Nested cross-validation: the rating pipeline is refit inside every backtest fold, so a
  held-out tournament never trains its own prediction.
- Three correctness tests are enforced in CI: the Article 13 tiebreaker order, the
  leakage guard, and scoreline coherence (simulated scorelines match the model's W/D/L).
- Every gap is reported with an uncertainty band, never as a point verdict.

## Status

| Stage | State |
|---|---|
| Data pipeline · player ratings · match model + validation · tournament simulation | done |
| Live updates · scored predictions committed to git before kickoff | done |
| Public track record | live (the receipts); scored once the sample is meaningful |
| Website | [live](https://tj-chakravarthy.github.io/World-Cup-2026-Gap-Index/) |

Python. Static output, committed as plain files.

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
games drawn from the tilted matrix, the full FIFA Article 13 tiebreaker order (real FIFA ranking; fair-play zero until card data loads), the eight best thirds
into the round of 32, level knockouts to a ~50/50 shootout — for each team's odds of reaching
every stage. Every run draws one of 25 bootstrap refits, so the odds are distributions, not
point estimates; the model is cached and re-runs on each new result, within half an hour of
full-time.

Open-source, updating live during the tournament.

## The result

Two things pre-registered:

**1. A calibrated model — met.** On held-out tournaments the expected calibration error is 0.054: when it says 60%, it happens about 60% of the time.

**2. Does translated club talent beat the obvious baselines? — no.** That was the
hypothesis, and it is not supported. A leakage-guarded backtest (five recent tournaments,
the whole rating pipeline refit inside each fold) shows the player-talent indices add
nothing over Elo + market value:

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
teams, the full FIFA Article 13 group-tiebreaker order, the official knockout bracket. The order
— head-to-head, then goal difference, goals, team conduct, and the real FIFA/Coca-Cola ranking —
is implemented, and the third-placed teams slot into the round of 32 by FIFA's exact Annex C
table. The one input still softer than the letter of the rules is the team-conduct score, which
runs at zero until match-card data is loaded. It updates within half an hour of each full-time.

<!-- TOPBOARD:START -->
Top of the board to win it: **Spain 12%, France 10%, Argentina 10%, England 8%.** _(updated 2026-06-17 03:20 UTC)_
<!-- TOPBOARD:END -->

## How it's built

All public data: 150 years of international results, national and club Elo, the 48 squads
(Wikipedia), club stats (FBref) and expected goals (Understat), past-tournament event data
for player VAEP (StatsBomb), 2026 fixtures, venues and heat. Betting odds I use only to score the model, never as an input; the
last-resort group tiebreaker leans on an Elo-based ranking as a FIFA-rank proxy, not a model
input either. Full source + license breakdown (committed vs regenerated): [DATA_SOURCES.md](DATA_SOURCES.md).

The integrity:

- Predictions are committed to git, timestamped, before kickoff. The history is the record.
- Nested cross-validation: the rating pipeline is refit inside every backtest fold, so a
  held-out tournament never trains its own prediction.
- Three correctness tests are enforced in CI: the Article 13 tiebreaker order, the
  leakage guard, and scoreline coherence (simulated scorelines match the model's W/D/L).
- Every gap is reported with an uncertainty band, never as a point verdict.

## Status

| Stage | State |
|---|---|
| Data pipeline · player ratings · match model + validation · tournament simulation | done |
| Live updates · every prediction committed to git before kickoff | done |
| Public track record | live (the receipts); scored once the sample is meaningful |
| Website | [live](https://tj-chakravarthy.github.io/World-Cup-2026-Gap-Index/) |

Python. Static output, committed as plain files.

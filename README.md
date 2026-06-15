# World Cup 2026 — Gap Index

A calibrated machine-learning forecast of the 2026 World Cup, built to test one idea: a
national team is just its club players, so does it perform as well as their club form
predicts? Rate every player from his club season, add them into a squad, compare to how
the team actually plays — the difference is the gap.

Built in the open, updating live during the tournament.

## The result

The project was designed so that either answer is honest. Two things were pre-registered:

**1. A calibrated model — met.** On held-out tournaments the expected calibration error is
0.054: when it says 60%, it happens about 60% of the time.

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

National Elo is already built from results, so it is a hard baseline to beat with squad
composition. The negative *is* the finding — reported plainly, not buried.

For scale, the model's Brier (0.589) lands within 0.017 of the bookmaker closing line
(0.573) and ahead of Elo. The market prices lineup news and money the model excludes by
rule, so beating it was never the goal.

The gap analysis still works as a description: talent explains about a third of results
(R²≈0.30), and the residual is the story — Morocco 2022 over, Germany 2018 under, each
with an uncertainty band (three group games is a tiny sample).

## The forecast

The calibrated model drives a Monte-Carlo run of the whole tournament under the real 2026
rules — 12 groups, 8 best third-placed teams, FIFA Article 13 tiebreakers. Top of the
board to win it: **Spain 13%, France 9%, Argentina 9%, England 8%.** It updates within
half an hour of each full-time.

## How it's built

All public data: 150 years of international results, national and club Elo, the 48 squads
(Wikipedia), club stats (FBref) and expected goals (Understat), past-tournament event data
for player VAEP (StatsBomb), 2026 fixtures, venues and heat. Bookmaker odds and the FIFA
ranking are used only for scoring and tiebreakers — never as model inputs.

The integrity is the point:

- Predictions are committed to git, timestamped, before kickoff. The history is the record.
- Nested cross-validation: the rating pipeline is refit inside every backtest fold, so a
  held-out tournament never trains its own prediction.
- Three correctness tests are enforced in CI: the exact Article 13 tiebreakers, the
  leakage guard, and scoreline coherence (simulated scorelines match the model's W/D/L).
- Every gap is reported with an uncertainty band, never as a point verdict.

## Status

| Stage | State |
|---|---|
| Data pipeline · player ratings · match model + validation · tournament simulation | done |
| Live daily updates + public track record | done |
| Website | planned |

Python. Static output, committed as plain files — no backend to go dark mid-tournament.

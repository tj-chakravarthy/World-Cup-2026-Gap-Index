# World Cup 2026 — Gap Index

I'm building a machine-learning model to forecast the 2026 World Cup, and to test
one idea: a national team is just a set of club players, so does it perform as well
as their club form says it should?

The method is to rate every player from his club season, add the players up into a
team, and compare that to how the team actually plays. The difference is the gap.
Some nations do better than their players suggest, some do worse. Measuring that gap
is the main point of the project.

Some of that gap comes from things around the players, and the clearest one is the
manager. Most national-team coaches couldn't get a top club job; a few now can
(Thomas Tuchel at England, Carlo Ancelotti at Brazil), so the model includes
coaching quality as one of the things that can explain why a squad over- or
under-performs.

It also does the ordinary things you'd want from a forecast: a win/draw/loss
probability and a likely scoreline for each match, and a full simulation of the
tournament under the real 2026 rules (12 groups, the 8 best third-placed teams, the
FIFA tiebreakers).

Work in progress, built in the open during the tournament. Current state is in the
table below.

## What the model uses

All public data. The inputs and where they come from:

- International match results, about 150 years of them — [martj42](https://github.com/martj42/international_results) (GitHub)
- National-team Elo ratings — [eloratings.net](https://www.eloratings.net/)
- 2026 fixtures and the 16 venues — [fixturedownload.com](https://fixturedownload.com/)
- The 48 squads, 1,248 players (plus the 2018 and 2022 squads for backtesting) — Wikipedia
- Each team's manager, for coaching quality — StatsBomb match data (past tournaments), Wikipedia (2026)
- Club strength, as club Elo — [clubelo.com](http://clubelo.com/)
- Club-season player stats (appearances, minutes, goals, assists, shots) — [FBref](https://fbref.com/)
- Club-season expected goals and assists (xG, npxG, xA, buildup) — [Understat](https://understat.com/)
- Match event data from past tournaments, used to value player actions (VAEP) — [StatsBomb open data](https://github.com/statsbomb/open-data)
- Venue temperature forecasts — [Open-Meteo](https://open-meteo.com/)

Two things are deliberately not model inputs. Bookmaker odds are used only to score
the model against the market, never to make a prediction. The FIFA world ranking is
used only for the tiebreakers, not as a feature.

## Method notes

- Predictions are committed to git with a timestamp before the matches are played.
  The git history is the record; nothing is predicted after kickoff.
- The locked file is the simple baseline model and is labelled as such. The full
  model comes later and does not inherit the early timestamp.
- Every gap is reported with an uncertainty band. With only a few tournaments per
  nation, a single run can swing the picture, so a point estimate on its own would
  mislead.
- The headline test is a feature-group ablation: do the player-talent indices beat a
  plain Elo-plus-market-value baseline at predicting matches? Backtested on five recent
  tournaments (World Cups 2018/2022, Euros 2020/2024, Copa América 2024), with the whole
  rating pipeline refit inside each fold so the held-out tournament never trains its own
  prediction. Result below, reported either way.

## Results so far

Two things were pre-registered as the deliverable: a calibrated match model, and an
honest gap analysis. The first is met. The headline hypothesis is not — and that is
itself the finding.

**The match model is well calibrated.** On held-out tournaments the expected calibration
error is 0.054: when it says 60%, it happens about 60% of the time. That was the stated
success criterion, deliberately separated from beating any baseline.

**The talent indices do not beat Elo + market value.** Pooled held-out Brier as the
feature set grows (lower is better; a 3-way coin guess is 0.667):

| features | Brier | 90% CI |
|---|---|---|
| Elo only | 0.594 | [0.562, 0.617] |
| + market value | 0.589 | [0.559, 0.611] |
| + player-talent indices | 0.596 | [0.564, 0.622] |
| + everything else | 0.599 | [0.562, 0.623] |

Market value nudges it (within the intervals); the club-to-country talent indices add
nothing on top. So the project's own thesis — that translated club talent beats the
obvious baselines — is not supported. National Elo is already built from results, so it
is a hard baseline to beat with squad composition. I'd rather report that plainly than
bury it.

**The forecast still works.** The calibrated model drives a Monte-Carlo run of the whole
tournament under the real 2026 rules (12 groups, 8 best thirds, Article 13). Current top
of the board to win it: Spain 12%, Argentina 9%, France 9%, England 8%.

## Status

| Stage | What | State |
|---|---|---|
| 0 | Lock the predictions (verifiable timestamp) | done |
| 1 | Data pipeline (results, squads, club stats, xG, market values, Elo) | done |
| 2 | Player ratings (the club-to-country translation) | done |
| 3 | Match model + nested-CV validation + the ablation above | done |
| 4 | Tournament simulation (Article 13 tiebreakers, Monte Carlo) | done |
| 5 | Website | planned |

All three correctness-critical test suites are green: the Article 13 tiebreakers (the
exact 2026 order — head-to-head before goal difference, world ranking as the final
decider, no drawing of lots), the leakage guard (the rating pipeline is refit inside
every backtest fold), and scoreline coherence (simulated scorelines agree with the
model's win/draw/loss probabilities).

## Stack

Python. The pipeline runs headless and writes predictions as plain files. The site
will be static, so there is no backend to go dark mid-tournament.

# World Cup 2026 — GAP Index

**Does talent translate?**

Every World Cup squad is a pile of club footballers. GAP Index rates those players
from their club seasons, adds them up into a team, and asks one question: **does a
nation perform like the sum of its players, or better, or worse?**

The teams that beat their talent are the overperformers. The ones that fall short
are the underperformers. That gap, between what a squad's club form says it should
do and what it actually does on the pitch, is the whole point of the project.

Along the way it does the things a fan actually wants: a **win/draw/loss and a
most-likely scoreline for every match**, and a **full simulation of the tournament**
under the real 2026 rules (12 groups, the 8 best third-placed teams, the exact FIFA
tiebreakers).

> 🚧 Work in progress, built in the open during the tournament. See [Status](#status).

---

## The honesty rules

Football is full of people who turn into experts the moment the final whistle goes.
This project is built so it can't do that:

- **Predictions are locked with a timestamp, in public.** The file
  [`data/predictions/predictions_locked_20260613.json`](data/predictions/predictions_locked_20260613.json)
  holds a prediction for every remaining group game, committed to git on 13 June 2026,
  before those matches kicked off. Git history is the receipt. A match that has already
  been played is never predicted after the fact.
- **The locked file is the simple model, and says so.** It buys an honest timestamp,
  not peak accuracy. The full model lands a few days later and is labelled "live"; the
  early timestamp is never quietly re-credited to it.
- **Bookmaker odds are never an input.** They are used only to keep score, model
  against market, every day. The market is expected to win: it prices in lineup leaks
  and money the model deliberately ignores. The point is to measure how close an honest,
  independent model gets, not to pretend to beat Vegas.
- **Gaps come with uncertainty.** With only two to four modern tournaments per nation,
  one run can dominate the picture, so over- and underperformance is always shown with
  a confidence band, never as a flat verdict.

---

## What's working now

- **Locked predictions** for the remaining 2026 group matches: win/draw/loss plus the
  likeliest scorelines, timestamped in git.
- **The model behind them:** a Dixon-Coles goals model (the standard in football
  forecasting) fit on ~150 years of international results, alongside an Elo rating
  baseline to measure against.
- **FIFA Article 13 tiebreakers** in the exact 2026 order: head-to-head *before* goal
  difference, the world ranking as the final decider, no drawing of lots. Implemented
  and unit-tested against hand-built tie scenarios, because fans check advancement maths
  within days and it has to be right.
- **The data spine:** all 104 fixtures and 16 venues, ~150 years of results, current
  national Elo, all **48 squads (1,248 players)**, club Elo, the StatsBomb match index
  for five past tournaments, and club-level player stats from FBref now being pulled.

## What's being built

- **The signature method:** a model that predicts each player's *tournament* impact from
  his *club-season* numbers, then rolls 1,248 players up into a dozen squad indices a fan
  would recognise: attack, midfield, defence, goalkeeping, cohesion, experience, age
  profile, fatigue. These become the radar shown for each team.
- **The full match model:** an ensemble on top of the indices, properly calibrated, with
  honest uncertainty on every prediction.
- **Tournament simulation:** a hundred thousand Monte Carlo runs of the bracket, carrying
  the model's own uncertainty, giving each nation its odds of reaching each round.
- **Live and benchmarked:** daily updates through the tournament, scored against both Elo
  and the betting market.
- **The website:** the gap chart, squad pages, match pages, a bracket simulator.

## On the numbers

There are no accuracy figures here yet, on purpose. The project commits up front to one
test: **do the player-talent indices add real, measurable signal over a plain
Elo-plus-market-value baseline?** If they do, the central idea holds. If they don't, that
gets reported just as plainly. The numbers go in once the full model is validated, with
confidence intervals, not before.

## Status

| Stage | What | State |
|---|---|---|
| 0 | Lock the predictions (verifiable timestamp) | ✅ done |
| 1 | Full data pipeline (squads, club stats, events) | 🔧 in progress |
| 2 | Player ratings (the club-to-country translation) | next |
| 3 | Match model + validation | next |
| 4 | Tournament simulation | next |
| 5 | Website | next |

---

*Built in Python. A headless data pipeline now, a static site later: predictions are
computed, committed as plain files, and served static, with no live backend to go dark
mid-tournament.*

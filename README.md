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
- No accuracy numbers yet, on purpose. The model is validated by backtesting against
  recent tournaments (World Cups 2018 and 2022, Euros 2020 and 2024, Copa América
  2024): the test is whether the player indices beat a plain Elo-plus-market-value
  baseline. I'll report that result either way, with intervals.

## Status

| Stage | What | State |
|---|---|---|
| 0 | Lock the predictions (verifiable timestamp) | done |
| 1 | Data pipeline (results, squads, club stats, events, managers) | in progress |
| 2 | Player ratings (the club-to-country translation) | in progress |
| 3 | Match model + validation | planned |
| 4 | Tournament simulation | planned |
| 5 | Website | planned |

The locked predictions and the FIFA Article 13 tiebreakers are done and tested. The
tiebreakers run in the exact 2026 order: head-to-head before goal difference, the
world ranking as the final decider, no drawing of lots.

## Stack

Python. The pipeline runs headless and writes predictions as plain files. The site
will be static, so there is no backend to go dark mid-tournament.

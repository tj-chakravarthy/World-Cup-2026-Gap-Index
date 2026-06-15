# Implementation deviations from PLAN.md

PLAN.md is gitignored (local-only design doc). This file is the canonical in-git
record of where the implementation diverges from it, and why.

---

## Data sources

**Keyless feeds over credentialed datasets.** PLAN §1.8 named the eloratings.net
Kaggle dataset for national Elo history, §1.4 named the Kaggle `martj42` mirror
for international results, and §1.5 named Wikipedia + API-Football for fixtures.
We use keyless public feeds instead: `eloratings.net/World.tsv` + `en.teams.tsv`
(`src/pipeline/fetch_elo.py`), `raw.githubusercontent.com/martj42/international_results`
(`src/pipeline/fetch_match_results.py`), and `fixturedownload.com`'s structured
WC2026 feed (`src/pipeline/fetch_fixtures_venues.py`). Same underlying data; no
credentials means CI and the daily cron run without secrets.

Note: `fetch_elo.py` delivers current eloratings.net Elo only (kept as the
member-E live baseline). The historical pre-tournament snapshots the nested-CV
folds (§4.5) and the per-tournament ELO index need are **computed ourselves** from
match_results (`src/features/elo_history.py`, World Football Elo conventions: K by
importance, goal-difference multiplier, 100 home advantage) rather than pulled from
the Kaggle eloratings history — keyless and reproducible. Snapshots for the 6
tournaments land in data/processed/elo_pretournament.csv; sanity-checked, the 2026
top is Spain/Argentina/France/England/Brazil.

---

## Dependencies and tooling

**apt-first split instead of one requirements.txt.** PLAN §"Dependencies" ships
a single `requirements.txt` containing the full stack (pandas, numpy, scipy,
scikit-learn, xgboost, matplotlib, seaborn, rapidfuzz, unidecode, haversine,
requests, beautifulsoup4, dotenv, pytest, jupyter, plus the football/ML gap).
We split into two files: `apt-packages.txt` carries the scientific and scraping
base as Debian 13 (trixie) packages; `requirements.txt` carries only what
Debian does not package (soccerdata, statsbombpy, socceraction, pyarrow,
`mapie==0.8.6`, pymc, lifelines, shap). The Dockerfile installs the apt base
then overlays pip with `--break-system-packages` (PEP 668). This is a user
preference — distro-pinned reproducibility without lockfiles.

---

## Frontend / npm

**npm parked pending stack decision.** PLAN §7 / "Full Stack" specifies Next.js 14
+ Tailwind on Vercel. We keep the repo npm-free until the frontend stack is
chosen (a pre-Stage-5 decision): the CI web job was removed
(`.github/workflows/ci.yml`), and the docker-compose web service was removed
(`docker-compose.yml`). `web/` remains a scaffold but is not built.

This is an open plan-level fork, not just a deferral: Next.js fundamentally
requires the npm ecosystem, so any stack choice that avoids npm means revisiting
the §7 architecture, not just switching a flag.

---

## CI dependency install

**requirements-dev.txt instead of full requirements.txt in CI.** The `python`
job in `.github/workflows/ci.yml` installs only `requirements-dev.txt` (pytest,
numpy<2, scipy, pandas, pyarrow) — the light subset that runs the stdlib and
numeric tests. The heavy modelling stack (pymc, xgboost, soccerdata, …) runs
inside the Docker image, not bare on `ubuntu-latest`.

Reason: `requirements.txt` no longer carries the scientific base (apt owns it),
and `ubuntu-latest` is not trixie, so a bare `pip install -r requirements.txt`
on the CI runner would install against an incompatible base. The Docker image
(`update_predictions.yml`) is the only faithful parity with the dev environment.

---

## Modelling and lock scope

**THIN lock: member E + member C, no indices.** PLAN Build-Order Stage 0 task 3
lists "minimal indices (ELO, EXP, AGE + raw squad ratings via market value)" and
task 4 lists "train minimal A+C." We lock a THIN model instead — Elo-sigmoid
(member E) and a goals-only Dixon-Coles (member C) — dropping squad rosters
(task 1), minimal index construction (task 3), and rest/travel/injuries-as-features
from the critical path of the lock. The locked file is the PLAN §"Honesty
framing" minimal artifact: a verifiable timestamp, not peak accuracy. Squad
indices and context features are inputs to the full model (Stages 2–3), not to
the thin lock.

**Dixon-Coles thin fit (src/models/dixon_coles.py).** PLAN §4.2 C envisaged
index-driven covariates. The thin version has no indices yet: fit is two-step —
weighted double-Poisson GLM (intercept, home advantage, per-team attack/defence)
then the classic ρ low-score correction on the four DC cells. Fit on
pre-tournament international results only (date < 2026-06-11, the WC2026 kick-off),
time-decay weighted (half-life ~2 years per PLAN §1.4). The 4 already-played
WC2026 group games are excluded from the fit. Home advantage is estimated on
non-neutral history and set to zero for neutral WC venues — `is_host` is a
Stage-3 context feature, not part of the thin lock.

**Elo member E draw model (src/models/elo_baseline.py).** PLAN §4.2 E says
"splits P(win) into W/D/L via a draw model" but specifies none. We use a crude
documented split: base draw rate (~0.231, measured from `data/raw/match_results.csv`)
modulated by Elo closeness, because we carry only the current Elo snapshot and
cannot fit a draw model against historical rating differences. Member E is
benchmark-only and lives in the artifact's per-prediction `members` field, never
as the headline.

---

## Tests

**Two of three mandatory suites are tripwires.** PLAN §"Known Challenges" /
Handoff requires three mandatory test suites. `tests/test_tiebreakers.py` is
implemented and green. `tests/test_leakage_guard.py` and
`tests/test_scoreline_coherence.py` are self-activating tripwires: they skip
while the guarded module is absent (`src/models/evaluate.py` and
`src/models/monte_carlo.py` respectively) and fail loudly the moment the module
lands, forcing the guard to be written then. The guarded modules don't exist yet
(Stages 3/5); a tripwire keeps the mandatory contract honest without a false green.

---

## Tiebreakers

**Art. 13(h) multi-edition lookup not wired; fails loud instead.** PLAN §5.1
step 3 specifies "g) most recent FIFA ranking → h) successively older editions
until resolved." `src/models/tiebreakers.py` carries one ranking edition and
raises if two teams reach the FIFA-ranking criterion equal and sharing a rank,
rather than falling back to older editions. A single real ranking edition has
unique integer positions, so (h) can only matter under duplicate ranks (bad
data). Failing loud is preferable to fabricating an order; full multi-edition
support is unwarranted until older editions are actually loaded.

---

## Schema and infrastructure

**Artifact schema hardened beyond PLAN.** `docs/artifact_schema.md` adds two
invariants beyond what PLAN §6 defined: invariant 6 (coverage completeness — the
three coverage sets must together account for all 104 fixtures, no omissions, no
unknown IDs) and per-component wdl ∈ [0,1] bounds enforced by the writer
(`src/pipeline/write_predictions.py`). The locked file can't be re-issued, so
the validator refuses malformed artifacts up front.

**Pulled-forward infrastructure.** Three pieces of Stage 4–6 work were built
during Stage 0 to unblock the lock:

- `src/pipeline/write_predictions.py` — the artifact writer and validator, PLAN
  Phase 6 work. Built first because the locked file's shape must be fixed before
  the writer is built (PLAN §6 states this explicitly).
- `src/pipeline/team_codes.py` — FIFA-trigram crosswalk across the three naming
  schemes (eloratings, martj42, fixturedownload/FIFA). Not an explicit PLAN task,
  but the real blocker that lets Elo, martj42 results, and fixtures join on one key.
- `src/models/tiebreakers.py` — PLAN Stage 4 work, pulled forward. PLAN
  Build-Order Stage 4 already notes this: "tiebreakers.py + test suite done
  (pulled forward to Art. 13)."

---

## Stage 1 data layer (environment constraints + deferrals)

PLAN Build-Order Stage 1 assumes all sources fetch overnight on one box. This
environment is Cloudflare-blocked on FBref (403), has no pandas / pip stack (only
numpy/scipy/pytest), and has no API keys, so Stage 1 was split by what runs here.

**Built and run (keyless, stdlib/bs4):**
- `fetch_squad_rosters.py` → `squads_2026.csv` (committed). 2026 only; the 2018/2022
  squads PLAN §1.1 also wants are Stage-2 backtest inputs, built when needed.
- `fetch_club_elo.py` (clubelo snapshot), `extract_qualifying.py` (derived),
  `fetch_statsbomb.py` (match index for the 5 backtest tournaments). Outputs are
  regenerable → gitignored.
- `name_matcher.py` + `name_overrides.csv` — fuzzy match with difflib fallback
  (rapidfuzz when present).

**Built but not run (key-gated, no keys here):** `fetch_injuries.py` (API-Football),
`fetch_odds.py` (The Odds API). Cron-ready; loud exit without the key.

**FBref Tier-1 club stats — resolved via headless Chromium (`fetch_club_stats.py`).**
The Stage-1 spine and predicted-VAEP input. FBref sits behind a Cloudflare JS
challenge that no plain HTTP client clears (curl / requests / soccerdata 403
everywhere, residential or not — confirmed). A real browser executes it: the
fetcher drives headless Chromium via Selenium, all from apt (chromium,
chromium-driver, python3-selenium — no pip), and clears CF locally on the dev box
(helsinki). soccerdata is not used (requests can't clear CF, and it isn't
apt-packaged). bedford (residential) is a fallback only if the dev IP is flagged.
Player tables (often comment-wrapped, multi-level over-headers) are parsed by
each cell's FBref `data-stat` key — `pandas.read_html` silently drops the grouped
stat columns to NaN on these tables. Output: one CSV per (league, season,
stat_type) under data/raw/ (gitignored). League ids/slugs were taken from FBref's
competitions index (152 comps), not guessed. `src/features/club_stats.py` merges
the six per-stat CSVs into one tidy player-club row (the Stage-2 input contract).

**Resolved issue — FBref serves only basic box-score stats; the Opta-derived
advanced columns are not in the delivered HTML at all.** The `standard` table comes
back with just games/minutes/goals/assists/pens/cards/per90. `data-stat="xg"` (and
`npxg`, `xg_assist`, `progressive_carries`, `progressive_passes`) appear **zero
times** in the page source. The columns are absent, not blank. This is structural,
not an access barrier, and the earlier "xvfb headed fetch" lever is **falsified**
(tested 2026-06-14):
- Not rate/volume: a fresh, never-hit league (Turkey) returns the same stripped table.
- Not headless detection: a HEADED Chromium under xvfb returns the same stripped table.
- Not IP/Cloudflare: bedford (a different residential IP) clears CF cleanly under
  headed-xvfb and still gets no advanced columns. So bedford CAN clear CF — the
  earlier "bedford IP can't clear CF" note above was a headless-only artifact.

FBref appears to gate Opta advanced stats from automated extraction since the 2024
StatsBomb→Opta switch. Conclusion: FBref via Selenium = basic box-score only, full
stop; no headless/headed/IP trick recovers xG. The replacement source for club-level
xG / advanced metrics is **Understat** (keyless, xG embedded as a JSON blob in the
page, no Cloudflare; Big-5 + RPL) — to be wired as the advanced-club feed. StatsBomb
open-data covers the tournament events (VAEP input), not club seasons. The basic
FBref set still feeds `player_features.py`; the advanced rate features stay dormant
there until the Understat feed lands.

**FBref Tier-1 = 18 first-tier European leagues** (Big 5 + NED/POR/BEL, the
English Championship, and TUR/SCO/SUI/AUT/GRE/DEN/CRO/POL/CZE). They share an
Aug–May calendar, so one `{YYYY}-{YYYY}` season format covers them. The
calendar-year / non-European leagues PLAN §1.2 also implies (MLS, Brazil,
Argentina, Liga MX, J1, K-League, Saudi, Scandinavia, …) use single-year season
strings and patchier advanced-stat coverage; they need per-league season handling
and are a follow-up, not part of the first matrix run.

**Transfermarkt market values — built + run (`fetch_transfermarkt.py`).** Same
Cloudflare situation as FBref, same fix (headed Chromium/Selenium), but unlike FBref
Transfermarkt serves the full squad table to a real browser — the
`kader/.../plus/1` page carries per-player market value. Two cached steps: discover
each nation's verein id by quick-search (senior team picked by fuzzy match of the
result's anchor text to the country name; youth/Olympic variants lose the match),
then scrape the squad and verify the page title names the team. 54/58 nations
resolved automatically; 4 alias cases (Türkiye, Czechia, Bosnia-Herzegowina,
Democratic Republic of the Congo) added by hand to `transfermarkt_team_ids.csv` (the
committed crosswalk; per-squad value CSVs are bulk → gitignored). Season maps to the
pre-tournament squad year (2018->2017, 2022->2021, 2026->2025), so backtest squads
get their own season's values, not today's.

**Deferred — bulk downloads to Stage 2:** StatsBomb full event JSON (VAEP
training) and Wyscout Figshare events. Only the StatsBomb index is fetched now.

**Built since:** Open-Meteo heat-forecast wiring (`fetch_weather.py`, keyless) —
the live half of the heat feature on top of the climate normals already in
`venues_2026.csv`. Transfermarkt market values and the 2018/2022 squads are now done
(above / commit history). Still open: the non-European FBref leagues (basic
box-score only there too, so lower priority).

---

## Stage 2 — player ratings (predicted VAEP)

**Observed VAEP regained its tournament grain (`src/features/vaep.py`).** The first
build aggregated VAEP per (player, team) only, so a player in several tournaments
collapsed to one summed row — unusable for §2.2 (the predicted-VAEP target is
*per tournament*) and §4.5 (the nested CV holds one tournament out). Fixed by
threading the tournament label through the build and keying the aggregation on it
when present (backward-compatible: no label -> old behaviour). `vaep_observed.csv`
is now one row per (player, team, tournament): 1008 player-tournaments >= 270 min.

**Predicted-VAEP signal is weak — the thesis, measured (`src/features/predicted_vaep.py`).**
PLAN §2.2 expected R^2 ~0.3-0.5 from club stats -> tournament VAEP-per-90. The honest
leave-one-tournament-out number is **R^2 ~= +0.01** (MAE 0.125), barely above a
position-mean baseline (R^2 -0.02). A regularization sweep showed anything deeper
than depth-1 stumps overfits to a *negative* held-out R^2; the shipped model is a
heavily-regularized stump ensemble that lands the slightly-positive number. Feature
correlations with the target are all weak (best ~0.17), and splitting to
offensive-only VAEP does not recover signal. This is the PLAN-anticipated finding
("club form genuinely doesn't fully translate, which IS the thesis"), reported
plainly rather than tuned around. Consequences: (a) predicted VAEP is a *weak
standalone* rating — the §2.3 composite should lean on market value; (b) the real
thesis test is the §4.5 *team-level* ablation (does the predicted-VAEP index beat
Elo + market value), where a weak player prior can still aggregate; (c) the §2.4
eyeball review will show the per-90 ranking under-separates stars (e.g. Mbappé below
some defenders) — expected from R^2~=0, documented not hidden.

**Feature surface vs PLAN §2.2.** Club features today are basic FBref box-score rates
+ Understat xG rates (`us_*_per90`), all percentile-normalized within (season,
position) per the §3 contract. FBref's withheld passing/defense/possession detail is
absent (see Stage-1 note), so the model predicts VAEP — which includes defensive
value — largely from offensive club stats; defensive translation is essentially
unmodelled. Understat covers Big-5 only, so non-Big-5 players carry NaN xG (HGB
takes NaN natively). Market-value percentile (now scraped) is not yet a feature:
given the ~0 ceiling it is better spent in the §2.3 composite and the §4.5 baseline
than chasing player-level R^2. Coverage: predicted VAEP is produced for 736 of the
1248 2026 squad players (those with 2025/26 Tier-1 club stats); the rest fall to the
§2.3 market-value/percentile branches.

**Composite player score is market-anchored, not PLAN's tiers
(`src/features/player_scores.py`).** PLAN §2.3 weighted predicted VAEP up to 0.6 in
discrete tiers, and its observed branch (0.5 obs + 0.5 pred) dropped market value
entirely. With predicted-VAEP R^2~=0 that mis-rated stars: Bellingham (top market
value) fell to 65 on one average tournament, and a back-up keeper with no market match
scored ~95 from predicted-VAEP noise alone within the thin GK pool. Reworked
market-anchored: market value is the backbone (0.60), recent observed VAEP a moderate
tilt (0.25), predicted VAEP a small one (0.15), renormalised over present components;
a player with neither market value nor observed VAEP is left unrated, not scored from
predicted noise. Predicted VAEP still enters the §3 indices / §4.5 ablation on its
own — that, not this display rating, is where it earns weight. Coverage: 1084/1248
rated (market value 1077, recent observed 122); 156 market-value unmatched seed
name_overrides.csv.

**Stale squads_2026.csv fixed (data correction).** 48 captain names carried the
literal "( captain )" annotation — squads_2026 was generated before the squad parser's
captain-stripper (`_CAPTAIN`, fetch_squad_rosters.py) landed (the 2018/2022 files,
added later, are clean). It broke every name join for those players (Mbappé scored
nothing). Cleaned in place with the parser's own `_clean`/`_norm`; market-value
coverage rose ~40 players and Mbappé/Marquinhos rate correctly.

---

## Stage 3 — indices, match model, and the thesis test

**Squad indices (`src/features/indices.py`).** Per (tournament, team), z-scored within
each tournament's field (§3 leakage-safe contract). 12 indices over 6 tournaments (176
team-tournaments): predicted-VAEP ATK/MID/DEF/GK, plus MKT, ELO, EXP, AGE, DEPTH, COH,
COV, FAT. Deviation from §3's list: TAC (PPDA) and QUAL are dropped for now — PPDA is
in the FBref tables Opta withholds, and per-tournament qualifying form isn't assembled
yet. Predicted-VAEP indices are kept SEPARATE from MKT and ELO (not pre-blended like
the §2.3 display score) precisely so the §4.5 ablation can isolate the thesis signal.
The predicted-VAEP model is passed into `build_indices`, so the nested CV refits it per
fold (the leakage guard). Market value is now scraped for every backtest season (TM
2020 for Euro2020, TM 2023 for Euro2024/Copa2024), so the MKT index is real for all six
tournaments and the ablation's "+market" step is fair across folds.

**Match training set (`src/models/match_dataset.py`).** One row per fixture (§4.1):
both teams' index levels + differentials, 3-class target {team1/draw/team2},
swap-augmented. Built from the 5 backtest tournaments' matches (match_results.csv joined
to that tournament's indices) → 262 fixtures. WC2026 is the prediction target, not
training. This is the realistic sample: ~262 fixtures, autocorrelated within
team-tournament, so the effective independent N is small and CIs are wide by design.

**The thesis test — feature-group ablation (`src/models/evaluate.py`), result: NOT
supported.** Nested forward-chaining temporal CV (predicted-VAEP refit + index rebuild
per fold, leakage guard live in `tests/test_leakage_guard.py`). Pooled held-out
multiclass Brier, tournament-clustered bootstrap 90% CI, multinomial logistic on the
index differentials, strong L2 (the per-fold train set is tiny). Headline:

|feature set|Brier|90% CI|
|---|---|---|
|Elo only|0.594|[0.562, 0.617]|
|+ market value|0.589|[0.559, 0.611]|
|+ predicted-VAEP|0.596|[0.564, 0.622]|
|full (+ structure)|0.599|[0.562, 0.623]|

(uniform-guess Brier 0.667; Transfermarkt market values now scraped for every backtest
season 2017/2020/2021/2023/2025, so "+market" is fair across all folds.) **Market value
adds a small gain over Elo (0.594 -> 0.589); the predicted-VAEP indices do NOT improve on
Elo+market (0.589 -> 0.596) — the thesis is not supported.** The "+market" step now
behaves as it should (market is informative), which validates the pipeline — the earlier
run had market degrading the Brier purely because it was NaN for three folds. Against this
clean baseline predicted VAEP still earns nothing. All CIs overlap (≈0.56-0.62), so the
honest statement is "predicted VAEP is indistinguishable from Elo+market — no measurable
signal"; even the market gain is within noise. The verdict is robust across regularization
C∈[1.0, 0.015] (a sweep). Why it lands this way: national Elo is itself computed from
results and already encodes squad strength; predicted VAEP is weak at player level
(R²≈0); and 262 autocorrelated fixtures give little power. The §4.5 pre-registered
negative outcome, reported as a finding not a failure. Per PLAN §7.1a the fan product
stands without the thesis — the gap analysis, scorelines and simulation are unaffected;
/method reports this ablation as the honest headline.

---

## Stage 4 — calibration + tournament simulation

**Calibration (`src/models/calibration.py`) — the pre-registered success metric is met.**
Top-label ECE 0.054 on the leave-one-tournament-out held-out predictions for the
production model (Elo+market), reliability near the diagonal. PLAN's success criterion is
a calibrated model decoupled from beating Elo/market, so the project succeeds on its own
terms even though the §4.5 thesis is unsupported. Raw held-out ECE (no recalibration on
the same data); isotonic recalibration (PLAN §4.4) is a later production refinement.

**Scoreline coherence (`src/models/scoreline.py`) — lambda-tilt, not cell reweighting.**
Per PLAN §5.2: tilt Dixon-Coles' lambdas (2 params: total-goals scale + home/away
balance) until the joint's implied W/D/L matches the calibrated marginals, then sample.
The mandatory test_scoreline_coherence is now live (tilt hits target marginals incl
lopsided; sampled scorelines reproduce them within MC error). Third mandatory suite green.

**Monte Carlo (`src/models/monte_carlo.py`).** 20k draws (PLAN §5.2 says 100k; 20k keeps
it tractable and the probabilities stable to ~0.3pp — raise for the final artifact). Group
stage is exact (Art. 13 via tiebreakers); knockout via bracket.py. Keyed by FIFA code
throughout. Deviations from PLAN §5:
- **FIFA-ranking final tiebreaker proxied by Elo order.** Art. 13's last criterion is the
  FIFA ranking, a fixed pre-tournament input; we don't have it loaded, so the deterministic
  residual-tie break uses Elo order instead (unique ints, always resolves). Swap in the
  real ranking when loaded — it only matters for exact ties through every prior criterion.
- **Third-place allocation is a constraint-matching approximation** (bracket.py): FIFA's
  495-row Annex C wasn't obtainable; we assign each qualifying third to a slot whose
  group-set contains it (bijective). The bracket TREE (R16->final) is verified exact
  (Wikipedia/NBC); only which third meets which seed in R32 is approximate.
- **Knockout draws: 90' draw -> a near-50/50 nudge**, folding extra time into the penalty
  coin flip rather than PLAN §5.2's explicit reduced-rate ET goals then penalties. A
  simplification; the §5.3 capped-near-50/50 penalty spirit holds.
- Parameter-uncertainty Monte Carlo — now done (see Stage 6 below): the pre-tournament
  model is bootstrapped into a 25-member bag (logistic refit on resampled fixtures,
  Dixon-Coles on resampled results) and each draw samples a member, so the exit-stage odds
  are distributions over model uncertainty, not point estimates (PLAN §5.2).

Sanity: Spain 12.4% / Argentina 9.5% / France 9.4% / England 8.0% to win, P(reach R32)
decaying sensibly from ~0.97 — consistent with the bookmaker board and the calibration.

---

## Stage 6 — live ops, market benchmark, sim polish

**Live update layer (`src/pipeline/run_all.py`, `.github/workflows/update_predictions.yml`,
`src/update/prediction_log.py`).** Idempotent orchestrator: refresh results, and only on a
NEW played result recompute forecast+sim, rewrite the JSON artifacts, append the
append-only track-record log, stamp freshness; loud non-zero exit on any step. The cron
polls every 15 min in the NA full-time window (00-07 & 17-23 UTC) with a cheap `--check`
gate, heavy Docker recompute + commit only on a new result. Validated end-to-end on live
data (the feed advanced to 12 played; the pipeline moved them to evidence, logged 60
predictions, refreshed the odds). Goes live on merge to main.

**Model bundle caching (`monte_carlo.py`).** The pre-tournament pieces (indices, the
production logistic, Dixon-Coles, and the bootstrap bags) are fixed for the whole
tournament, so they're built once into a pickled `Bundle` and reused every update; only
the played results change per matchday. Cuts a per-update recompute from ~8 min (rebuild)
to the draws alone, and 25-member parameter uncertainty rides along (PLAN §5.2 — odds as
distributions over model uncertainty). Draw count: the live cron uses 20k (~0.3pp MC
noise, far below the between-match odds shift; ~6 min), while monte_carlo.main runs 100k
for a one-off published snapshot (~30 min — too slow per-match, and invisibly better).

**Market benchmark (§4.6, `src/models/market_benchmark.py`) — done, real backtest.**
football-data.co.uk is club-leagues-only (PLAN's worry confirmed). Usable free source:
`eatpizzanot/soccer-dataset` (CC-BY-4.0), Pinnacle closing 1X2 odds covering Euro2020,
WC2022, Euro2024, Copa2024 — exactly the held-out CV fixtures (198/198; WC2018 has no free
odds and is never a test fold, so no gap). Pooled held-out multiclass Brier: **model 0.589,
market 0.573, Elo 0.594** — the model is ~0.017 behind the market (expected; the closing
line prices lineup news + money the model excludes by the odds-never-an-input rule) and
ahead of Elo. The honest "within a hair of the market, beats Elo" stat. Odds are never a
model feature — benchmark only. Live WC2026 benchmark runs via `fetch_odds.py` once an
odds key + snapshot exist. Odds slices committed (112K) with attribution for reproducibility.

**Model bundle committed (`data/processed/model_bundle.pkl`).** PLAN/gitignore treats
`data/processed/**` as regenerable cache, not committed. The bundle is the exception: it's
the frozen pre-tournament model (indices + production logistic + Dixon-Coles + 25 bootstrap
bags), and building it needs the raw scrape (FBref/Understat/match_results) which stays
ignored. The cron checkout has none of that, so a rebuild-from-raw can't run in CI — it died
at `load_club_stats` (FileNotFoundError) on the first dispatch that got past the Docker fix.
Committing the 3.9M pickle and loading it as-is is the fix: matches "fixed for the whole
tournament", keeps the cron self-contained, no raw data in the public repo. The actions/cache
step stays as an optimisation but is no longer load-bearing. Rebuild + recommit on a
BUNDLE_VERSION bump (a stale-version load would try to rebuild and fail the same way).
Verified end-to-end against a clean git-tracked-only tree (zero FBref) in the cron image.

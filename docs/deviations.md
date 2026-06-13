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

Note: `fetch_elo.py` delivers current Elo only. Year-end snapshots needed for
the nested-CV folds (§4.5) aren't yet wired — flagged as a TODO in that file
since it doesn't block the Stage-0 lock.

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
Player tables FBref wraps in HTML comments are read from the live DOM or
comment-stripped. Output: one CSV per (league, season, stat_type) under data/raw/
(gitignored, regenerable). The ~30-league Tier-1 list (PLAN §1.2) is finalised
before the full overnight matrix; the five top European leagues (verified ids)
run first.

**Transfermarkt market values** — same Cloudflare situation; the same
Chromium/Selenium approach applies, not built yet.

**Deferred — bulk downloads to Stage 2:** StatsBomb full event JSON (VAEP
training) and Wyscout Figshare events. Only the StatsBomb index is fetched now.

**Not yet built (small, keyless, next):** Open-Meteo heat-forecast wiring (climate
normals are already in `venues_2026.csv` from Stage 0).

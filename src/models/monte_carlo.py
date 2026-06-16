"""Monte Carlo tournament simulation (PLAN.md §5.2).

Samples the rest of the tournament many times and records how far each team goes.
Everything is keyed by FIFA code (fixtures, calibrated W/D/L, Dixon-Coles rates via the
team_codes martj42 crosswalk, the Elo-proxy ranking) — that sidesteps the nations whose
name differs across feeds.

The pre-tournament pieces — squad indices, the production W/D/L model, Dixon-Coles, and
bootstrap bags of both for parameter uncertainty — are FIXED for the whole tournament, so
they are built once into a `Bundle` and cached to disk; only the played-results change
per matchday, so a live update just reloads the bundle and re-samples (fast). Build the
bundle once (~5 min); every cron update after is just the draws.

Per draw: pick a bootstrap member (parameter uncertainty — PLAN §5.2: odds are
distributions over model uncertainty, not point estimates), sample scorelines for the
unplayed group fixtures (Dixon-Coles tilted to that member's calibrated W/D/L marginals,
§5.2 coherence), apply played results as fixed evidence, rank each group by Art. 13
(tiebreakers, with real group-stage conduct when loaded), top-2 + 8 best thirds, fill the
R32 via bracket.py, play out the knockout (90' draw -> near-50/50 nudge). Aggregate ->
P(win group / reach R32/R16/QF/SF/Final/Win). The final group tiebreaker is the real FIFA
ranking (load_fifa_rankings; Elo-order proxy as fallback), so residual ties break
deterministically, not by a random draw (§5.1). pandas + scipy.
"""

from __future__ import annotations

import pickle
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from src.features.indices import build_indices
from src.features.player_features import load_player_features
from src.features.predicted_vaep import build_training_table, train_model
from src.models.dixon_coles import DCModel
from src.models.dixon_coles import fit as dc_fit
from src.models.match_dataset import build_match_dataset
from src.models.match_model import PRODUCTION_COLS, predict_wdl, train_production
from src.models.scoreline import sample_scorelines, tilted_matrix
from src.models.tiebreakers import (CARD_POINTS, Match, conduct_score, group_table,
                                     rank_third_placed)

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"
PROC = REPO / "data" / "predictions"
PROC_DATA = REPO / "data" / "processed"
BUNDLE_PATH = PROC_DATA / "model_bundle.pkl"
BUNDLE_VERSION = 1   # bump when the Bundle shape or how it's built changes -> auto-rebuild

GROUPS = list("ABCDEFGHIJKL")
WC_START = "2026-06-11"
N_SIMS = 100_000
N_BOOT = 25          # bootstrap members for parameter uncertainty (PLAN §5.2 ~25)
STAGES = ["R32", "R16", "QF", "SF", "final", "winner"]


@dataclass
class Bundle:
    """The fixed pre-tournament model: squad indices, the point W/D/L + Dixon-Coles, and
    bootstrap bags of each for parameter uncertainty. Cached; rebuilt only between
    tournaments (or with --rebuild)."""
    indices: pd.DataFrame
    codes: list[str]
    code2m: dict[str, str]
    fifa_rank: dict[str, int]
    wdl: dict[tuple[str, str], np.ndarray]            # point pairwise W/D/L
    dc: DCModel                                       # point Dixon-Coles
    wdl_bag: list[dict[tuple[str, str], np.ndarray]]  # bootstrap pairwise W/D/L
    dc_bag: list[DCModel]                             # bootstrap Dixon-Coles
    n_boot: int
    version: int                                      # BUNDLE_VERSION it was built under


def code_to_martj42() -> dict[str, str]:
    tc = pd.read_csv(RAW / "team_codes.csv")
    return dict(zip(tc["fifa_code"], tc["martj42_name"]))


def elo_rank_by_code(indices: pd.DataFrame) -> dict[str, int]:
    """Elo-proxy for the official FIFA ranking (the Art. 13 final tiebreaker): the 2026
    teams ranked by their ELO index, 1 = best. Unique ints, so ties always resolve. The
    documented fallback used only when the real FIFA ranking (below) isn't loaded."""
    wc = indices[indices["tournament"] == "world_cup_2026"].sort_values("ELO",
                                                                        ascending=False)
    return {c: i + 1 for i, c in enumerate(wc["country_code"])}


RANKINGS_PATH = RAW / "fifa_rankings_2026.csv"
CARDS_PATH = RAW / "cards_2026.csv"


def load_fifa_rankings(codes, path: Path = RANKINGS_PATH) -> dict[str, int] | None:
    """Real FIFA/Coca-Cola ranking (1 = best) for `codes` — Art. 13 §1 g), from
    fetch_fifa_rankings. Returns None if the file is absent or doesn't cover every code, so
    the caller falls back to the Elo-order proxy rather than a partial real ranking."""
    if not path.exists():
        return None
    df = pd.read_csv(path)
    rank = dict(zip(df["fifa_code"], df["rank"].astype(int)))
    have = {c: rank[c] for c in codes if c in rank}
    return have if len(have) == len(set(codes)) else None


def load_conduct(path: Path = CARDS_PATH) -> dict[str, int]:
    """Team conduct score (Art. 13 §1 f) from group-stage cards. cards_2026.csv carries one
    row per (fixture_id, team_code) with CARD_POINTS-keyed counts; sum the deductions per
    team. Empty (all zero) when no card data is loaded — the documented fallback."""
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    kinds = [k for k in CARD_POINTS if k in df.columns]
    out: dict[str, int] = {}
    for r in df.itertuples(index=False):
        cards = {k: int(getattr(r, k) or 0) for k in kinds}
        out[r.team_code] = out.get(r.team_code, 0) + conduct_score(cards)
    return out


def pairwise_wdl(clf, indices: pd.DataFrame, codes: list[str],
                 cols=PRODUCTION_COLS) -> dict[tuple[str, str], np.ndarray]:
    """Calibrated [team1 win, draw, team2 win] for every ordered pair of 2026 teams,
    order-invariant — the lookup for both group fixtures and random knockout pairings."""
    idx = indices[indices["tournament"] == "world_cup_2026"].set_index("country_code")
    pairs = [(a, b) for a in codes for b in codes if a != b]
    diffs = np.array([[idx.loc[a, c] - idx.loc[b, c] for c in cols] for a, b in pairs])
    probs = predict_wdl(clf, diffs)
    return {pair: probs[i] for i, pair in enumerate(pairs)}


def _dc_matches(results: pd.DataFrame) -> list[tuple]:
    pre = results[results["date"].astype(str) < WC_START].dropna(
        subset=["home_score", "away_score"])
    return [(str(r.date), r.home_team, r.away_team, int(r.home_score),
             int(r.away_score), bool(r.neutral)) for r in pre.itertuples()]


def build_bundle(n_boot: int = N_BOOT, seed: int = 0) -> Bundle:
    """Build the fixed pre-tournament model + bootstrap bags (the slow, once-per-
    tournament step). The bag refits the production logistic on resampled fixtures and
    Dixon-Coles on resampled results — drawing one member per simulation propagates
    parameter uncertainty into the exit-stage odds."""
    club_feats = load_player_features()
    observed = pd.read_csv(PROC_DATA / "vaep_observed.csv")
    indices = build_indices(model=train_model(build_training_table(observed, club_feats)),
                            club_feats=club_feats)
    results = pd.read_csv(RAW / "match_results.csv")
    codes = sorted(indices[indices.tournament == "world_cup_2026"]["country_code"])

    dataset = build_match_dataset(indices, results)
    clf = train_production(dataset, PRODUCTION_COLS)
    wdl = pairwise_wdl(clf, indices, codes)
    dcm = _dc_matches(results)
    dc = dc_fit(dcm, ref_date=WC_START)

    rng = np.random.default_rng(seed)
    wdl_bag, dc_bag = [], []
    for b in range(n_boot):
        clf_b = train_production(dataset.sample(frac=1.0, replace=True,
                                                random_state=seed + b), PRODUCTION_COLS)
        wdl_bag.append(pairwise_wdl(clf_b, indices, codes))
        boot = [dcm[i] for i in rng.integers(len(dcm), size=len(dcm))]
        dc_bag.append(dc_fit(boot, ref_date=WC_START))

    return Bundle(indices, codes, code_to_martj42(), elo_rank_by_code(indices),
                  wdl, dc, wdl_bag, dc_bag, n_boot, BUNDLE_VERSION)


def save_bundle(bundle: Bundle, path: Path = BUNDLE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(bundle, f)


def load_or_build_bundle(path: Path = BUNDLE_PATH, rebuild: bool = False) -> Bundle:
    """Load the cached bundle (fixed pre-tournament -> reuse every update) or build+cache
    it. Self-healing: a corrupt, unpicklable (e.g. a sklearn version change), or
    stale-version cache is rebuilt rather than crashing the run. rebuild=True forces it."""
    if path.exists() and not rebuild:
        try:
            with open(path, "rb") as f:
                bundle = pickle.load(f)
            if getattr(bundle, "version", None) == BUNDLE_VERSION:
                return bundle
            print(f"bundle version {getattr(bundle, 'version', None)} != {BUNDLE_VERSION}; "
                  "rebuilding", file=sys.stderr)
        except Exception as e:  # noqa: BLE001 - any load failure -> rebuild, never crash
            print(f"bundle load failed ({e}); rebuilding", file=sys.stderr)
    bundle = build_bundle()
    save_bundle(bundle, path)
    return bundle


def _make_tilted(bundle: Bundle, param_uncertainty: bool):
    """Lazy cache: (codeA, codeB, member) -> tilted Dixon-Coles scoreline matrix coherent
    with that member's calibrated W/D/L. member<0 (or no uncertainty) => the point model."""
    base = float(np.exp(bundle.dc.intercept))
    cache: dict[tuple[str, str, int], np.ndarray] = {}

    def get(a: str, b: str, m: int) -> np.ndarray:
        key = (a, b, m if param_uncertainty else -1)
        if key not in cache:
            dc = bundle.dc_bag[m] if param_uncertainty else bundle.dc
            wdl = bundle.wdl_bag[m] if param_uncertainty else bundle.wdl
            na, nb = bundle.code2m.get(a), bundle.code2m.get(b)
            if na in dc.attack and nb in dc.attack:
                lam1, lam2 = dc.rates(na, nb, neutral=True)
            else:
                lam1 = lam2 = base
            cache[key] = tilted_matrix(lam1, lam2, dc.rho, tuple(wdl[(a, b)]))
        return cache[key]
    return get


def simulate_groups(group_fix, sampled, fifa_rank, n_sims, conduct=None):
    """Per sim, rank each group by Art. 13 and pull standings (1st/2nd counts, the 12
    third Standings for best-8 selection, and the full per-sim group order). `conduct` (team
    conduct scores from real group-stage cards) is the §1 f) tiebreaker; None -> all zero."""
    place = defaultdict(lambda: np.zeros(4, dtype=int))
    sim_first, sim_second, sim_thirds, sim_rank = [], [], [], []
    for s in range(n_sims):
        firsts, seconds, thirds, ranks = {}, {}, [], {}
        for g, fixtures in group_fix.items():
            matches = []
            for fx in fixtures:
                if fx["played"]:
                    hg, ag = fx["home_score"], fx["away_score"]
                else:
                    hg, ag = sampled[fx["fixture_id"]][0][s], sampled[fx["fixture_id"]][1][s]
                matches.append(Match(fx["home_code"], fx["away_code"], int(hg), int(ag)))
            standings = group_table(matches, fifa_rank, conduct)
            for pos, st in enumerate(standings):
                place[st.team][pos] += 1
            firsts[g], seconds[g] = standings[0].team, standings[1].team
            thirds.append(standings[2])
            ranks[g] = [st.team for st in standings]
        sim_first.append(firsts)
        sim_second.append(seconds)
        sim_thirds.append(thirds)
        sim_rank.append(ranks)
    return place, sim_first, sim_second, sim_thirds, sim_rank


def _ko_winner(a: str, b: str, m: int, tilted, rng) -> str:
    """One knockout match for bootstrap member m: sample a scoreline; a 90' draw goes to a
    near-50/50 nudge (penalties, PLAN §5.3)."""
    hg, ag = sample_scorelines(tilted(a, b, m), rng, 1)
    if hg[0] > ag[0]:
        return a
    if hg[0] < ag[0]:
        return b
    return a if rng.random() < 0.5 else b


def _stage_of(match_id: str) -> str | None:
    """Knockout stage from the fixture number. M89-96 R16, 97-100 QF, 101-102 SF,
    104 final; 103 is the third-place playoff (SF losers) — None, skipped here."""
    n = int(match_id.rsplit("M", 1)[-1])
    if 89 <= n <= 96:
        return "R16"
    if 97 <= n <= 100:
        return "QF"
    if 101 <= n <= 102:
        return "SF"
    return "final" if n == 104 else None


def _walk_knockout(r32_winners: dict[str, str], m: int, tilted, rng, reach):
    """Walk the bracket from the R32 winners to the champion (bootstrap member m),
    tallying the stage each team reaches."""
    from src.models import bracket
    won = dict(r32_winners)
    for match_id, f1, f2 in bracket.bracket_tree():
        stage = _stage_of(match_id)
        if stage is None or f1 not in won or f2 not in won:
            continue
        a, b = won[f1], won[f2]
        reach[a][stage] += 1
        reach[b][stage] += 1
        w = _ko_winner(a, b, m, tilted, rng)
        won[match_id] = w
        if stage == "final":
            reach[w]["winner"] += 1


def simulate(bundle: Bundle, fixtures: pd.DataFrame, n_sims: int = N_SIMS,
             seed: int = 0, param_uncertainty: bool = True) -> pd.DataFrame:
    """Simulate the tournament from the cached bundle and the current played results.
    Each draw uses a bootstrap member (parameter uncertainty) unless disabled."""
    rng = np.random.default_rng(seed)
    members = (rng.integers(bundle.n_boot, size=n_sims) if param_uncertainty
               else np.zeros(n_sims, dtype=int))
    tilted = _make_tilted(bundle, param_uncertainty)

    grp = fixtures[fixtures.stage == "group"]
    group_fix: dict[str, list[dict]] = {g: [] for g in GROUPS}
    sampled = {}
    for _, fx in grp.iterrows():
        rec = {"fixture_id": fx.fixture_id, "home_code": fx.home_code,
               "away_code": fx.away_code, "played": bool(fx.played),
               "home_score": fx.home_score, "away_score": fx.away_score}
        group_fix[fx.group].append(rec)
        if not rec["played"]:
            hg = np.empty(n_sims, dtype=int)
            ag = np.empty(n_sims, dtype=int)
            for m in np.unique(members):       # vectorised per bootstrap member
                idx = np.where(members == m)[0]
                h, a = sample_scorelines(tilted(fx.home_code, fx.away_code, int(m)),
                                         rng, len(idx))
                hg[idx], ag[idx] = h, a
            sampled[fx.fixture_id] = (hg, ag)

    # real FIFA ranking + group-stage conduct for the Art. 13 tiebreakers (loaded at run
    # time, not baked into the cached bundle); fall back to the Elo-order proxy if absent.
    fifa_rank = load_fifa_rankings(bundle.codes) or bundle.fifa_rank
    conduct = load_conduct()
    place, sim_first, sim_second, sim_thirds, sim_rank = simulate_groups(
        group_fix, sampled, fifa_rank, n_sims, conduct)

    from src.models import bracket
    reach = defaultdict(lambda: defaultdict(int))
    for s in range(n_sims):
        m = int(members[s])
        thirds_ranked = rank_third_placed(sim_thirds[s])
        best8 = [st.team for st in thirds_ranked[:8]]
        for st in thirds_ranked[:8]:
            reach[st.team]["R32"] += 1
        for g in GROUPS:
            reach[sim_first[s][g]]["R32"] += 1
            reach[sim_second[s][g]]["R32"] += 1
        third_groups = [g for g in GROUPS if sim_rank[s][g][2] in best8]
        r32 = bracket.resolve_r32(sim_rank[s], third_groups)
        winners = {fid: _ko_winner(t1, t2, m, tilted, rng) for fid, (t1, t2) in r32.items()}
        _walk_knockout(winners, m, tilted, rng, reach)

    rows = []
    for c in bundle.codes:
        row = {"country_code": c, "win_group": place[c][0] / n_sims,
               "runner_up": place[c][1] / n_sims}
        for st in STAGES:
            row[f"p_{st}"] = reach[c][st] / n_sims
        rows.append(row)
    return pd.DataFrame(rows).sort_values("p_winner", ascending=False)


def group_fixture_wdl(bundle: Bundle, fixtures: pd.DataFrame) -> pd.DataFrame:
    """The 72 group fixtures' point W/D/L from the bundle (predictions_2026_wdl shape) —
    lets run_all build the live match artifact off the cached bundle, no rebuild."""
    rows = []
    for _, fx in fixtures[fixtures.stage == "group"].iterrows():
        p = bundle.wdl.get((fx.home_code, fx.away_code))
        if p is None:
            continue
        rows.append({"fixture_id": fx.fixture_id, "group": fx.group,
                     "home_team": fx.home_team, "away_team": fx.away_team,
                     "home_code": fx.home_code, "away_code": fx.away_code,
                     "played": bool(fx.played), "home_score": fx.home_score,
                     "away_score": fx.away_score, "p_home": float(p[0]),
                     "p_draw": float(p[1]), "p_away": float(p[2])})
    return pd.DataFrame(rows)


def write_simulation_json(df: pd.DataFrame, n_sims: int) -> Path:
    """Emit the committed sim artifact (advancement + winner odds) + web mirror."""
    import json
    from datetime import datetime, timezone
    cols = [c for c in ["country_code", "win_group", "runner_up", "p_R32", "p_R16",
                        "p_QF", "p_SF", "p_final", "p_winner"] if c in df.columns]
    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tournament": "FIFA World Cup 26", "n_sims": n_sims,
        "param_uncertainty": True, "teams": df[cols].round(5).to_dict("records"),
    }
    out = PROC / "simulation.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n")
    mirror = REPO / "web" / "public" / "data" / "simulation.json"
    mirror.parent.mkdir(parents=True, exist_ok=True)
    mirror.write_text(out.read_text())
    return out


def main() -> None:
    bundle = load_or_build_bundle()
    fixtures = pd.read_csv(RAW / "fixtures_2026.csv")
    df = simulate(bundle, fixtures)
    PROC_DATA.mkdir(parents=True, exist_ok=True)
    df.to_csv(PROC_DATA / "tournament_sim.csv", index=False)
    sim_json = write_simulation_json(df, N_SIMS)
    cols = [c for c in ["country_code", "win_group", "p_R32", "p_R16", "p_QF", "p_SF",
                        "p_final", "p_winner"] if c in df.columns]
    print(f"tournament sim ({N_SIMS} draws, {bundle.n_boot}-member param uncertainty) "
          f"-> {sim_json.name}")
    print(df[cols].head(12).to_string(index=False))


if __name__ == "__main__":
    main()

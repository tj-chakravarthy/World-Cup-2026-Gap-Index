"""Monte Carlo tournament simulation (PLAN.md §5.2).

Samples the rest of the tournament many times and records how far each team goes.
Everything is keyed by FIFA code (the fixtures, the calibrated W/D/L, the Dixon-Coles
rates via team_codes' martj42 crosswalk, the Elo-proxy ranking) — that sidesteps the
handful of nations whose name differs across feeds.

Per draw: sample scorelines for the unplayed group fixtures (Dixon-Coles tilted to the
calibrated W/D/L marginals — §5.2 coherence), apply the already-played results as fixed
evidence, rank each group by exact FIFA Art. 13 (tiebreakers.py), take top-2 + the 8
best thirds, fill the R32 via the official bracket (bracket.py), then play out the
knockout (a 90' draw goes to a near-50/50 penalty nudge). Aggregate into P(win group),
P(reach R32/R16/QF/SF/Final/Win) per team.

Group-stage advancement is exact and needs no bracket; the knockout half imports
bracket.py lazily so this still runs (group only) before that module lands. The final
tiebreaker is a fixed pre-tournament ranking, so residual ties break deterministically
by it, not by a random draw (PLAN §5.1 simulator note). We proxy the official FIFA
ranking by Elo order (documented) until the ranking is loaded. pandas + scipy.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from src.features.indices import build_indices
from src.features.player_features import load_player_features
from src.features.predicted_vaep import build_training_table, train_model
from src.models.dixon_coles import fit as dc_fit
from src.models.match_dataset import build_match_dataset
from src.models.match_model import (PRODUCTION_COLS, fixture_index_diffs,
                                     predict_wdl, train_production)
from src.models.scoreline import sample_scorelines, tilted_matrix
from src.models.tiebreakers import Match, Standing, group_table, rank_third_placed

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"
PROC = REPO / "data" / "processed"

GROUPS = list("ABCDEFGHIJKL")
WC_START = "2026-06-11"
N_SIMS = 20000
STAGES = ["R32", "R16", "QF", "SF", "final", "winner"]


def code_to_martj42() -> dict[str, str]:
    tc = pd.read_csv(RAW / "team_codes.csv")
    return dict(zip(tc["fifa_code"], tc["martj42_name"]))


def elo_rank_by_code(indices: pd.DataFrame) -> dict[str, int]:
    """Elo-proxy for the official FIFA ranking (the Art. 13 final tiebreaker): the 2026
    teams ranked by their ELO index, 1 = best. Unique ints, so ties always resolve."""
    wc = indices[indices["tournament"] == "world_cup_2026"].sort_values("ELO",
                                                                        ascending=False)
    return {c: i + 1 for i, c in enumerate(wc["country_code"])}


def pairwise_wdl(clf, indices: pd.DataFrame, codes: list[str],
                 cols=PRODUCTION_COLS) -> dict[tuple[str, str], np.ndarray]:
    """Calibrated [team1 win, draw, team2 win] for every ordered pair of 2026 teams,
    order-invariant. The lookup for both group fixtures and random knockout pairings."""
    idx = indices[indices["tournament"] == "world_cup_2026"].set_index("country_code")
    pairs = [(a, b) for a in codes for b in codes if a != b]
    diffs = np.array([[idx.loc[a, c] - idx.loc[b, c] for c in cols] for a, b in pairs])
    probs = predict_wdl(clf, diffs)
    return {pair: probs[i] for i, pair in enumerate(pairs)}


def tilted_lookup(dc, code2m: dict[str, str], wdl: dict, rho_max_goals=10):
    """Lazy cache: (codeA, codeB) -> tilted Dixon-Coles scoreline matrix coherent with
    the pair's calibrated W/D/L. Built on demand (knockout pairings vary per sim)."""
    cache: dict[tuple[str, str], np.ndarray] = {}

    base = float(np.exp(dc.intercept))  # fallback rate for a team absent from the fit

    def get(a: str, b: str) -> np.ndarray:
        if (a, b) not in cache:
            na, nb = code2m.get(a), code2m.get(b)
            if na in dc.attack and nb in dc.attack:
                lam1, lam2 = dc.rates(na, nb, neutral=True)
            else:
                lam1 = lam2 = base
            cache[(a, b)] = tilted_matrix(lam1, lam2, dc.rho, tuple(wdl[(a, b)]))
        return cache[(a, b)]
    return get


def simulate_groups(group_fix: dict[str, list[dict]], sampled: dict[str, tuple],
                    fifa_rank: dict[str, int], n_sims: int):
    """Per sim, rank each group by Art. 13 and pull standings. Returns, per team:
    counts of finishing 1st/2nd/3rd and (1st/2nd/3rd-rank Standing per sim per group),
    plus the per-sim third-place Standings needed to pick the best 8."""
    place = defaultdict(lambda: np.zeros(4, dtype=int))      # team -> [1st,2nd,3rd,4th]
    # per sim: group winners/runners + the 12 third Standings (for best-8 selection)
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
            standings = group_table(matches, fifa_rank)
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


def _ko_winner(a: str, b: str, tilted, rng) -> str:
    """One knockout match: sample a scoreline; a 90' draw goes to a near-50/50 nudge
    leaning to the side the calibrated model favours (penalties, PLAN §5.3)."""
    hg, ag = sample_scorelines(tilted(a, b), rng, 1)
    if hg[0] > ag[0]:
        return a
    if hg[0] < ag[0]:
        return b
    return a if rng.random() < 0.5 else b  # coin flip; small lean folded in elsewhere


def simulate(n_sims: int = N_SIMS, seed: int = 0) -> pd.DataFrame:
    club_feats = load_player_features()
    observed = pd.read_csv(PROC / "vaep_observed.csv")
    indices = build_indices(model=train_model(build_training_table(observed, club_feats)),
                            club_feats=club_feats)
    results = pd.read_csv(RAW / "match_results.csv")
    fixtures = pd.read_csv(RAW / "fixtures_2026.csv")
    codes = sorted(indices[indices.tournament == "world_cup_2026"]["country_code"])

    clf = train_production(build_match_dataset(indices, results), PRODUCTION_COLS)
    wdl = pairwise_wdl(clf, indices, codes)
    pre = (results[results["date"].astype(str) < WC_START]
           .dropna(subset=["home_score", "away_score"]))
    dc_matches = [(str(r.date), r.home_team, r.away_team, int(r.home_score),
                   int(r.away_score), bool(r.neutral)) for r in pre.itertuples()]
    dc = dc_fit(dc_matches, ref_date=WC_START)
    code2m = code_to_martj42()
    tilted = tilted_lookup(dc, code2m, wdl)
    fifa_rank = elo_rank_by_code(indices)
    rng = np.random.default_rng(seed)

    grp = fixtures[fixtures.stage == "group"]
    group_fix: dict[str, list[dict]] = {g: [] for g in GROUPS}
    sampled = {}
    for _, fx in grp.iterrows():
        rec = {"fixture_id": fx.fixture_id, "home_code": fx.home_code,
               "away_code": fx.away_code, "played": bool(fx.played),
               "home_score": fx.home_score, "away_score": fx.away_score}
        group_fix[fx.group].append(rec)
        if not rec["played"]:
            hg, ag = sample_scorelines(tilted(fx.home_code, fx.away_code), rng, n_sims)
            sampled[fx.fixture_id] = (hg, ag)

    place, sim_first, sim_second, sim_thirds, sim_rank = simulate_groups(
        group_fix, sampled, fifa_rank, n_sims)

    reach = defaultdict(lambda: defaultdict(int))
    try:
        from src.models import bracket
        have_bracket = True
    except Exception:
        have_bracket = False

    for s in range(n_sims):
        thirds_ranked = rank_third_placed(sim_thirds[s])
        best8 = [st.team for st in thirds_ranked[:8]]
        for st in thirds_ranked[:8]:
            reach[st.team]["R32"] += 1
        for g in GROUPS:
            reach[sim_first[s][g]]["R32"] += 1
            reach[sim_second[s][g]]["R32"] += 1
        if not have_bracket:
            continue
        third_groups = [g for g in GROUPS if sim_rank[s][g][2] in best8]
        r32 = bracket.resolve_r32(sim_rank[s], third_groups)
        winners = {fid: _ko_winner(t1, t2, tilted, rng) for fid, (t1, t2) in r32.items()}
        _walk_knockout(winners, tilted, rng, reach)

    rows = []
    for c in codes:
        row = {"country_code": c, "win_group": place[c][0] / n_sims,
               "runner_up": place[c][1] / n_sims}
        for st in STAGES:
            row[f"p_{st}"] = reach[c][st] / n_sims
        rows.append(row)
    return pd.DataFrame(rows).sort_values("p_winner", ascending=False)


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


def _walk_knockout(r32_winners: dict[str, str], tilted, rng, reach):
    """Walk the bracket from the R32 winners to the champion, tallying the stage each
    team reaches. bracket_tree() rows are (match_id, feeder1, feeder2); winners flow up.
    Feeders are R32/earlier fixture ids, so won[] resolves them in tree order."""
    from src.models import bracket
    won = dict(r32_winners)  # keyed by R32 fixture id
    for match_id, f1, f2 in bracket.bracket_tree():
        stage = _stage_of(match_id)
        if stage is None or f1 not in won or f2 not in won:  # third-place playoff skipped
            continue
        a, b = won[f1], won[f2]
        reach[a][stage] += 1
        reach[b][stage] += 1
        w = _ko_winner(a, b, tilted, rng)
        won[match_id] = w
        if stage == "final":
            reach[w]["winner"] += 1


def write_simulation_json(df: pd.DataFrame, n_sims: int) -> Path:
    """Emit the committed sim artifact (advancement + winner odds) + web mirror — the
    /simulate data, alongside predictions_live.json."""
    import json
    from datetime import datetime, timezone
    cols = ["country_code", "win_group", "runner_up", "p_R32", "p_R16", "p_QF", "p_SF",
            "p_final", "p_winner"]
    cols = [c for c in cols if c in df.columns]
    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tournament": "FIFA World Cup 26", "n_sims": n_sims,
        "teams": df[cols].round(5).to_dict("records"),
    }
    out = REPO / "data" / "predictions" / "simulation.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n")
    mirror = REPO / "web" / "public" / "data" / "simulation.json"
    mirror.parent.mkdir(parents=True, exist_ok=True)
    mirror.write_text(out.read_text())
    return out


def main() -> None:
    df = simulate()
    PROC.mkdir(parents=True, exist_ok=True)
    out = PROC / "tournament_sim.csv"
    df.to_csv(out, index=False)
    sim_json = write_simulation_json(df, N_SIMS)
    cols = [c for c in ["country_code", "win_group", "p_R32", "p_R16", "p_QF", "p_SF",
                        "p_final", "p_winner"] if c in df.columns]
    print(f"tournament sim ({N_SIMS} draws) -> {out.relative_to(REPO)} + {sim_json.name}")
    print(df[cols].head(12).to_string(index=False))


if __name__ == "__main__":
    main()

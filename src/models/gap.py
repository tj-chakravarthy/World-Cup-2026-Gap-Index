"""Over/underperformance gap — the project namesake, /gap (PLAN.md §7 /gap, §1).

A national team is a bag of club talent. Does it perform as well as that talent
predicts? Plot talent (x) against actual results (y); the diagonal is "performs as
expected"; above it overperforms, below underperforms. The GAP is the vertical
residual of `results ~ talent`, reported with a band — never a point verdict, since
with only ~2-4 tournaments per nation a single run dominates the estimate (PLAN §1).

HONEST CAVEAT — the talent axis is weak. The §4.5 feature-group ablation
(src/models/evaluate.py, docs/deviations.md) found the predicted-VAEP indices do NOT
beat Elo + market value at predicting match outcomes on held-out Brier; even market's
gain over Elo is within noise. So we build TALENT from the signals that DO carry
information — market value (MKT) and Elo (ELO) — with only a light predicted-VAEP
ATK/MID/DEF contribution, and we report the talent->results correlation honestly (it
is modest). The gap is still a real, shareable finding: "who beat their market/Elo-
implied level" (an overperforming tournament run) does not require a strong talent
axis — it only requires that talent explain *some* of results and that the residual
be read with its uncertainty.

Talent and results are both per (tournament, country_code). Talent is a single
z-score from squad_indices; results is group-stage points-per-game (3/1/0) from
match_results, joined to the index team set by name (src/pipeline/name_matcher,
same path as match_dataset.py — robust 100% coverage on the backtests; the
team_codes crosswalk is incomplete for pre-2026 squads so we don't route through it).

pandas + numpy + sklearn.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

from src.models.match_dataset import TOURNAMENT_WINDOW
from src.pipeline.name_matcher import Matcher

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"
PROC = REPO / "data" / "processed"

# Talent weights over the z-scored squad_indices. Lead on the signals the §4.5
# ablation showed carry information (MKT, ELO); a light predicted-VAEP ATK/MID/DEF
# tilt for transparency, not because it adds measurable Brier signal. Weights are
# the documented design choice, not fitted — the fit happens in results ~ talent.
TALENT_WEIGHTS = {
    "MKT": 0.40,  # market value — the strongest single squad-strength signal we have
    "ELO": 0.40,  # national Elo, computed from results (pre-tournament snapshot)
    "ATK": 0.10,  # predicted-VAEP attack — weak prior, kept for interpretability
    "MID": 0.05,
    "DEF": 0.05,
}

GROUP_GAMES = 3  # group stage = each team's first 3 distinct-opponent matches

# match_dataset.TOURNAMENT_WINDOW stops at the 5 backtests (WC2026 is the prediction
# target there, not training). The gap table needs the WC2026 partial too, so we
# carry the one extra window locally. ~4 matches played as of the build date.
WC2026_WINDOW = ("FIFA World Cup", "2026-06-01", "2026-07-31")
WINDOWS = {**TOURNAMENT_WINDOW, "world_cup_2026": WC2026_WINDOW}


def talent_score(indices: pd.DataFrame) -> pd.DataFrame:
    """Per (tournament, country_code, team) a single talent z-score: the documented
    TALENT_WEIGHTS combination of the (already z-scored) squad indices, re-z-scored
    *within tournament* so talent is read against that edition's field. NaN index
    cells (e.g. GK missing) are treated as 0 = the tournament mean, so a team is not
    dropped for one absent column."""
    cols = list(TALENT_WEIGHTS)
    w = np.array([TALENT_WEIGHTS[c] for c in cols])
    x = indices[cols].to_numpy(dtype=float)
    x = np.where(np.isnan(x), 0.0, x)  # missing index -> field mean (0 in z-space)
    raw = x @ w
    out = indices[["tournament", "country_code", "team"]].copy()
    out["talent"] = raw
    # re-z within tournament: comparable spread per edition, robust to field size
    g = out.groupby("tournament")["talent"]
    mu, sd = g.transform("mean"), g.transform("std", ddof=0)
    out["talent"] = np.where(sd > 0, (out["talent"] - mu) / sd, 0.0)
    return out.reset_index(drop=True)


def _matches_in_window(results: pd.DataFrame, tournament: str) -> pd.DataFrame:
    """Played matches of one edition (label + date window). Mirrors match_dataset.
    tournament_matches but reads WINDOWS, so it also covers the WC2026 partial."""
    label, d0, d1 = WINDOWS[tournament]
    d = results["date"].astype(str)
    m = results[(results["tournament"] == label) & (d >= d0) & (d <= d1)]
    return m.dropna(subset=["home_score", "away_score"])


def _group_stage(matches: pd.DataFrame) -> pd.DataFrame:
    """Isolate group-stage fixtures from a tournament edition's played matches. The
    date window holds the *whole* tournament (knockouts included); the group stage is
    each team's first GROUP_GAMES chronological matches. A match counts only while
    BOTH teams are still under the cap, which by chronology (all group games precede
    knockouts) selects exactly the group stage. Partial editions (WC2026, ~4 played)
    fall out naturally — teams simply have <3 games."""
    df = matches.sort_values("date")
    seen: dict[str, int] = defaultdict(int)
    keep = []
    for _, r in df.iterrows():
        h, a = r["home_team"], r["away_team"]
        if seen[h] < GROUP_GAMES and seen[a] < GROUP_GAMES:
            keep.append(r)
            seen[h] += 1
            seen[a] += 1
    return pd.DataFrame(keep, columns=matches.columns) if keep else matches.iloc[:0]


def results_ppg(results: pd.DataFrame, indices: pd.DataFrame,
                tournaments: list[str] | None = None) -> pd.DataFrame:
    """Per (tournament, country_code, team) group-stage points-per-game (win 3, draw
    1, loss 0). Result team names are matched to that tournament's index team set
    (Matcher, same path as match_dataset.py), so country_code rides along from the
    index row. A participant with zero games (none played yet) is skipped, not
    crashed; partial editions get a partial==True flag and small n_games."""
    names = tournaments or [t for t in WINDOWS if (indices["tournament"] == t).any()]
    rows = []
    for t in names:
        idx = indices[indices["tournament"] == t]
        if idx.empty or t not in WINDOWS:
            continue
        code_of = dict(zip(idx["team"], idx["country_code"]))
        matcher = Matcher(choices=list(idx["team"]))
        pts: dict[str, int] = defaultdict(int)
        games: dict[str, int] = defaultdict(int)
        for _, m in _group_stage(_matches_in_window(results, t)).iterrows():
            h = matcher.match(m["home_team"])[0]
            a = matcher.match(m["away_team"])[0]
            if h is None or a is None:  # a non-participant slipped the window — skip
                continue
            hs, as_ = m["home_score"], m["away_score"]
            ph, pa = (3, 0) if hs > as_ else (0, 3) if hs < as_ else (1, 1)
            pts[h] += ph
            games[h] += 1
            pts[a] += pa
            games[a] += 1
        full_n = idx["team"].map(games).fillna(0).max()  # expected full group = 3
        for team, code in code_of.items():
            n = games[team]
            if n == 0:
                continue  # no games yet (partial edition) — skip rather than NaN-divide
            rows.append({
                "tournament": t, "country_code": code, "team": team,
                "ppg": pts[team] / n, "n_games": n,
                "partial": n < GROUP_GAMES or full_n < GROUP_GAMES,
            })
    return pd.DataFrame(rows)


def compute_gaps(talent: pd.DataFrame, results: pd.DataFrame,
                 fit_tournaments: list[str] | None = None,
                 n_boot: int = 2000, seed: int = 0) -> pd.DataFrame:
    """Merge talent & results per team-tournament, fit `ppg ~ talent` (OLS pooled
    across all team-tournaments), and report each team's gap = ppg - expected_ppg.

    The fit is deliberately one pooled line — "expected results given talent" across
    the whole sample — so the gap is read on a common diagonal. WC2026 (partial) is
    excluded from the fit by default (fit_tournaments) but still gets a gap against
    the fitted line.

    Uncertainty band (gap_lo/gap_hi, 90%): a bootstrap that reflects BOTH sources of
    the few-games-per-team noise. Per draw we (a) resample the team's group results
    to a fresh ppg — a 3-game ppg is a noisy estimate, so a team with 3 games gets a
    wide band, and (b) refit the line on a team-tournament bootstrap so the diagonal
    itself wobbles. The team ppg resample is modelled as binomial-ish per-game point
    draws around the observed rate; coverage (COV) widens it — low-COV squads carry
    explicitly wider bands (PLAN §3 measurement-error guard). Returns a tidy frame:
    tournament, country_code, team, talent, ppg, expected_ppg, gap, gap_lo, gap_hi,
    n_games."""
    df = talent.merge(results, on=["tournament", "country_code", "team"], how="inner")
    if df.empty:
        return df.assign(expected_ppg=[], gap=[], gap_lo=[], gap_hi=[])

    fit_names = fit_tournaments if fit_tournaments is not None else \
        [t for t in df["tournament"].unique() if t != "world_cup_2026"]
    fit = df[df["tournament"].isin(fit_names)]
    if len(fit) < 2:  # nothing to fit a line against — fall back to the full sample
        fit = df

    def _fit(frame):
        lr = LinearRegression()
        lr.fit(frame[["talent"]].to_numpy(), frame["ppg"].to_numpy())
        return lr

    base = _fit(fit)
    df = df.copy()
    df["expected_ppg"] = base.predict(df[["talent"]].to_numpy())
    df["gap"] = df["ppg"] - df["expected_ppg"]

    # COV widening factor: low coverage -> wider per-game ppg noise. COV is z-scored,
    # so map it to a multiplier centred near 1 (a 1-sd-low-COV squad gets ~30% wider).
    cov = df["cov"].to_numpy() if "cov" in df.columns else np.zeros(len(df))
    cov_mult = np.clip(1.0 - 0.30 * cov, 0.7, 1.8)

    rng = np.random.default_rng(seed)
    fit_idx = fit.index.to_numpy()
    talent_all = df["talent"].to_numpy()
    ppg_all = df["ppg"].to_numpy()
    n_games = df["n_games"].to_numpy()
    boot = np.empty((n_boot, len(df)))
    for b in range(n_boot):
        # (b) wobble the diagonal: resample the team-tournaments the line is fit on
        samp = fit.loc[rng.choice(fit_idx, size=len(fit_idx), replace=True)]
        lr = _fit(samp)
        exp_b = lr.predict(df[["talent"]].to_numpy())
        # (a) resample each team's ppg from its few group games (per-game point draw)
        ppg_b = np.array([
            _resample_ppg(ppg_all[i], int(n_games[i]), rng, cov_mult[i])
            for i in range(len(df))
        ])
        boot[b] = ppg_b - exp_b
    df["gap_lo"] = np.percentile(boot, 5, axis=0)
    df["gap_hi"] = np.percentile(boot, 95, axis=0)

    cols = ["tournament", "country_code", "team", "talent", "ppg", "expected_ppg",
            "gap", "gap_lo", "gap_hi", "n_games"]
    return df[cols].reset_index(drop=True)


def _resample_ppg(ppg: float, n_games: int, rng: np.random.Generator,
                  cov_mult: float = 1.0) -> float:
    """One bootstrap draw of a team's group-stage ppg. A 3-game ppg is a noisy point
    estimate: model each game's points as a draw around the observed mean (Gaussian
    per-game with the field's per-game points sd, scaled by coverage), average over
    n_games. Fewer games -> wider; clipped to the valid [0, 3] ppg range."""
    if n_games <= 0:
        return ppg
    per_game_sd = 1.25 * cov_mult  # rough sd of per-match points (3/1/0) in the field
    draws = rng.normal(ppg, per_game_sd, size=n_games)
    return float(np.clip(draws.mean(), 0.0, 3.0))


def _pearson(x: np.ndarray, y: np.ndarray) -> float:
    """Pearson r, NaN-safe (no scipy dep needed for one number)."""
    if len(x) < 2 or np.std(x) == 0 or np.std(y) == 0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def main() -> None:
    indices = pd.read_csv(PROC / "squad_indices.csv")
    results = pd.read_csv(RAW / "match_results.csv")

    talent = talent_score(indices)
    # carry COV onto the talent frame so compute_gaps can widen low-coverage bands
    if "COV" in indices.columns:
        talent = talent.merge(
            indices[["tournament", "country_code", "COV"]].rename(columns={"COV": "cov"}),
            on=["tournament", "country_code"], how="left")
    ppg = results_ppg(results, indices)
    gaps = compute_gaps(talent, ppg)

    PROC.mkdir(parents=True, exist_ok=True)
    out = PROC / "gap.csv"
    gaps.to_csv(out, index=False)
    print(f"gap table: {len(gaps)} team-tournaments -> {out.relative_to(REPO)}")

    # honest talent->results read, on the backtest (full group stage) only
    bt = gaps[gaps["tournament"] != "world_cup_2026"]
    r = _pearson(bt["talent"].to_numpy(), bt["ppg"].to_numpy())
    r2 = r * r
    print(f"\npooled talent -> results (backtest, n={len(bt)}): "
          f"Pearson r = {r:.2f}, R² = {r2:.2f}")
    read = ("talent explains little of the result spread — the gap is the story, "
            "not the diagonal" if r2 < 0.25 else
            "talent tracks results moderately; gaps are the residual on top")
    print(f"  read: {read}")

    show = ["team", "tournament", "talent", "ppg", "gap", "gap_lo", "gap_hi", "n_games"]
    over = bt.sort_values("gap", ascending=False).head(5)
    under = bt.sort_values("gap").head(5)
    print("\ntop 5 OVERperformers (beat their talent-implied level):")
    print(over[show].to_string(index=False))
    print("\ntop 5 UNDERperformers:")
    print(under[show].to_string(index=False))
    print("\n(bands are 90%; a band crossing 0 means the gap is not distinguishable "
          "from on-the-line at this sample size.)")


if __name__ == "__main__":
    main()

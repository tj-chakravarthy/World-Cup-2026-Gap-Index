"""Market benchmark (PLAN.md §4.6) — model Brier vs the bookmaker market.

The honest external yardstick: the market aggregates lineup leaks, injury news and
money the model deliberately excludes (the "Odds usage rule" — odds NEVER enter the
model, only score it), so it is *expected* to win. The credible claim is "within X
Brier of the market, ahead of / level with Elo", never a spun market loss.

BACKTEST source. football-data.co.uk turned out to be club-leagues-only for odds, so
the international-tournament closing odds come from the CC-BY soccer-dataset
(github.com/eatpizzanot/soccer-dataset): Pinnacle closing 1X2 from API-Football
snapshots. Coverage is exactly the four backtest tournaments that also have held-out
model predictions:

    Euro 2020 (2021)  51/51   World Cup 2022  64/64
    Euro 2024         51/51   Copa América 2024  32/32

World Cup 2018 has NO odds (API-Football closing snapshots start ~2020) and is never a
held-out test fold anyway, so the comparison set is the 198 fixtures above — model and
market matched one-to-one.

Cached slices live under data/raw/market_odds/ (gitignored bulk scrape). The model side
comes from the nested CV in evaluate.py (imported read-only); alignment is by
(tournament, oriented team pair) with a positional date tie-break for the two
group+knockout rematches. pandas/numpy; sklearn only via evaluate.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.models.match_dataset import TOURNAMENT_WINDOW, outcome, tournament_matches
from src.pipeline.name_matcher import Matcher

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"
PROC = REPO / "data" / "processed"
ODDS_DIR = RAW / "market_odds"

# soccer-dataset league id -> our tournament-edition key (TOURNAMENT_WINDOW key). The
# edition is pinned by the date window in TOURNAMENT_WINDOW, so league+window is enough.
LEAGUE_TO_TOURNAMENT = {
    78: "world_cup",   # FIFA World Cup -> world_cup_2018 / world_cup_2022 (by window)
    79: "euro",        # UEFA Euro      -> euro_2020 / euro_2024
    81: "copa",        # Copa America   -> copa_america_2024
}

# soccer-dataset team spellings that the fuzzy matcher can't close to our canonical
# names. Source-specific (not the global name_overrides.csv) — these are the only three.
ODDS_NAME_OVERRIDES = {
    "USA": "United States",
    "Türkiye": "Turkey",
    "FYR Macedonia": "North Macedonia",
}


# --- the only transform: de-vig --------------------------------------------------

def devig(odds_home: float, odds_draw: float, odds_away: float
          ) -> tuple[float, float, float]:
    """Decimal odds -> (p_home, p_draw, p_away). Implied prob 1/odds, normalised to
    remove the overround so the three sum to 1. Pure."""
    inv = np.array([1.0 / odds_home, 1.0 / odds_draw, 1.0 / odds_away], dtype=float)
    p = inv / inv.sum()
    return float(p[0]), float(p[1]), float(p[2])


# --- backtest odds loader --------------------------------------------------------

def _edition_of(tournament_base: str, date: str) -> str | None:
    """Map a base tournament ('world_cup') + a fixture date onto the edition key in
    TOURNAMENT_WINDOW (e.g. 'world_cup_2022'), or None if outside every window."""
    d = str(date)[:10]
    for key, (_, d0, d1) in TOURNAMENT_WINDOW.items():
        if key.startswith(tournament_base) and d0 <= d <= d1:
            return key
    return None


def load_backtest_odds(odds_dir: Path = ODDS_DIR) -> pd.DataFrame:
    """Tidy closing-odds frame for the backtest tournaments' fixtures:
    [tournament, date, home, away, odds_home, odds_draw, odds_away]. Empty frame if the
    cached slices are absent (source not downloaded)."""
    cols = ["tournament", "date", "home", "away",
            "odds_home", "odds_draw", "odds_away"]
    fx_path, od_path, tm_path = (odds_dir / f for f in
                                 ("fixtures.csv", "odds.csv", "teams.csv"))
    if not (fx_path.exists() and od_path.exists() and tm_path.exists()):
        return pd.DataFrame(columns=cols)

    fixtures = pd.read_csv(fx_path)
    odds = pd.read_csv(od_path)
    teams = pd.read_csv(tm_path).set_index("id")["name"]

    # one closing row per fixture; pick Pinnacle when present (the sharp book), else any
    odds = odds.sort_values("bookmaker", key=lambda s: s.ne("Pinnacle"))
    odds = odds.drop_duplicates("fixture_id", keep="first")
    od = odds.set_index("fixture_id")

    rows = []
    for _, fx in fixtures.iterrows():
        base = LEAGUE_TO_TOURNAMENT.get(int(fx["league_id"]))
        if base is None:
            continue
        edition = _edition_of(base, fx["date"])
        if edition is None or fx["id"] not in od.index:
            continue
        o = od.loc[fx["id"]]
        rows.append({
            "tournament": edition,
            "date": str(fx["date"])[:10],
            "home": teams.get(fx["home_team_id"]),
            "away": teams.get(fx["away_team_id"]),
            "odds_home": float(o["home_win"]),
            "odds_draw": float(o["draw"]),
            "odds_away": float(o["away_win"]),
        })
    return pd.DataFrame(rows, columns=cols)


# --- alignment -------------------------------------------------------------------

def align(model_preds: pd.DataFrame, odds: pd.DataFrame) -> pd.DataFrame:
    """Join the model's held-out predictions to market odds per fixture and orient the
    de-vigged market probs into the model's team1/team2 convention.

    `model_preds`: one row per held-out fixture with [tournament, team1, team2, target,
    p0, p1, p2] (p0 team1-win, p1 draw, p2 team2-win) — the model side carries fixture
    identity but no date.
    `odds`: load_backtest_odds() output (home/away + date).

    Match key is (tournament, oriented team pair). The market home team is matched to
    the model's team names per tournament (fuzzy, same matcher as the dataset) so
    'FYR Macedonia' etc. resolve. For the two tournaments with a group+knockout rematch
    of the same pair, both fixtures share team identity, so they are paired positionally
    by date — stable because the model rows are built in match-date order.

    Returns the matched subset with model probs (m_p0/m_p1/m_p2), market probs oriented
    to team1/team2 (k_p0/k_p1/k_p2), target, tournament. Orientation flips the market
    home/away probs when the matched market home == model team2.
    """
    mp = model_preds.copy()
    mp["_seq"] = mp.groupby(["tournament", "team1", "team2"]).cumcount()

    recs = []
    for tournament, grp in odds.groupby("tournament"):
        teamset = set(mp.loc[mp["tournament"] == tournament, "team1"]) | \
                  set(mp.loc[mp["tournament"] == tournament, "team2"])
        if not teamset:
            continue
        matcher = Matcher(choices=sorted(teamset), overrides=ODDS_NAME_OVERRIDES)
        g = grp.sort_values("date").reset_index(drop=True)
        for _, o in g.iterrows():
            home = matcher.match(o["home"])[0]
            away = matcher.match(o["away"])[0]
            if home is None or away is None:
                continue
            p_home, p_draw, p_away = devig(o["odds_home"], o["odds_draw"], o["odds_away"])
            recs.append({"tournament": tournament, "home": home, "away": away,
                         "k_home": p_home, "k_draw": p_draw, "k_away": p_away})
    market = pd.DataFrame(recs)
    if market.empty:
        return market

    # positional date tie-break: nth market meeting of an oriented pair -> nth model row
    market["_seq"] = market.groupby(["tournament", "home", "away"]).cumcount()

    out = []
    used = set()
    for _, mrow in mp.iterrows():
        t1, t2 = mrow["team1"], mrow["team2"]
        # market row in the SAME orientation (home==team1) ...
        cand = market[(market["tournament"] == mrow["tournament"]) &
                      (market["home"] == t1) & (market["away"] == t2) &
                      (market["_seq"] == mrow["_seq"])]
        flip = False
        if cand.empty:  # ... or the FLIPPED orientation (market home==team2)
            cand = market[(market["tournament"] == mrow["tournament"]) &
                          (market["home"] == t2) & (market["away"] == t1) &
                          (market["_seq"] == mrow["_seq"])]
            flip = True
        if cand.empty:
            continue
        krow = cand.iloc[0]
        key = (mrow["tournament"], krow["home"], krow["away"], int(krow["_seq"]))
        if key in used:
            continue
        used.add(key)
        if flip:  # market is home=team2/away=team1 -> swap to team1/team2 view
            k0, k1, k2 = krow["k_away"], krow["k_draw"], krow["k_home"]
        else:
            k0, k1, k2 = krow["k_home"], krow["k_draw"], krow["k_away"]
        out.append({
            "tournament": mrow["tournament"], "team1": t1, "team2": t2,
            "target": int(mrow["target"]),
            "m_p0": mrow["p0"], "m_p1": mrow["p1"], "m_p2": mrow["p2"],
            "k_p0": k0, "k_p1": k1, "k_p2": k2,
        })
    return pd.DataFrame(out)


# --- comparison ------------------------------------------------------------------

def _brier(probs: np.ndarray, y: np.ndarray) -> float:
    """Pooled multiclass Brier: mean summed squared error vs the one-hot outcome."""
    onehot = np.eye(3)[y.astype(int)]
    return float(((probs - onehot) ** 2).sum(axis=1).mean())


def compare(matched: pd.DataFrame, extra: dict[str, str] | None = None) -> pd.DataFrame:
    """Pooled multiclass Brier on the shared matched fixtures: model vs market (and any
    `extra` baseline whose probs are columns in `matched`, e.g. Elo-only).

    `matched` columns: target, m_p0/m_p1/m_p2 (model), k_p0/k_p1/k_p2 (market). `extra`
    maps a label -> column prefix present in `matched` (prefix+'0/1/2'). Returns a small
    table [source, n, brier], lower is better."""
    y = matched["target"].to_numpy()
    sources = {"model": "m_p", "market": "k_p"}
    if extra:
        sources.update(extra)
    rows = []
    for label, prefix in sources.items():
        cols = [f"{prefix}{i}" for i in range(3)]
        if not all(c in matched.columns for c in cols):
            continue
        probs = matched[cols].to_numpy()
        rows.append({"source": label, "n": len(matched),
                     "brier": round(_brier(probs, y), 4)})
    return pd.DataFrame(rows)


# --- main ------------------------------------------------------------------------

def _model_predictions() -> pd.DataFrame:
    """Pooled held-out per-fixture predictions carrying team identity, for the model
    (+market value, the production set) and the Elo-only baseline. Imports evaluate
    read-only. One row per held-out fixture: tournament, team1, team2, target, p0/p1/p2
    (model) and e0/e1/e2 (Elo)."""
    from src.features.player_features import load_player_features
    from src.models import evaluate

    club = load_player_features()
    observed = pd.read_csv(PROC / "vaep_observed.csv")
    results = pd.read_csv(RAW / "match_results.csv")
    folds = evaluate.fold_datasets(club, observed, results)

    model_cols = evaluate.FEATURE_GROUPS["+ market value"]
    elo_cols = evaluate.FEATURE_GROUPS["Elo only"]
    frames = []
    for tr, te, _ in folds:
        m = evaluate._fit_predict(tr, te, model_cols)
        e = evaluate._fit_predict(tr, te, elo_cols)
        d = te[["tournament", "team1", "team2", "target"]].copy()
        d[["p0", "p1", "p2"]] = m
        d[["e0", "e1", "e2"]] = e
        frames.append(d)
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    odds = load_backtest_odds()
    if odds.empty:
        print("no cached backtest odds (data/raw/market_odds/ absent) — backtest market "
              "comparison unavailable; only Elo is the free backtest baseline.")
        h, d, a = devig(2.0, 3.4, 4.0)
        print(f"devig demo: 2.0/3.4/4.0 -> H={h:.3f} D={d:.3f} A={a:.3f} (sum={h+d+a:.3f})")
        return

    preds = _model_predictions()
    matched = align(preds, odds)
    # Elo baseline on the SAME fixtures: re-align with Elo probs in the p0/p1/p2 slot
    # (a (tournament,team1,team2) merge would duplicate the rematch pairs), then attach
    # its oriented model-side probs as e0/e1/e2. align is deterministic + row-aligned.
    elo_in = preds.drop(columns=["p0", "p1", "p2"]).rename(
        columns={"e0": "p0", "e1": "p1", "e2": "p2"})
    elo_matched = align(elo_in, odds)
    for i in range(3):
        matched[f"e{i}"] = elo_matched[f"m_p{i}"].to_numpy()

    table = compare(matched, extra={"Elo only": "e"})
    PROC.mkdir(parents=True, exist_ok=True)
    matched.to_csv(PROC / "market_benchmark.csv", index=False)

    print(f"matched {len(matched)} of {len(odds)} odds fixtures to held-out predictions")
    print(matched["tournament"].value_counts().sort_index().to_string())
    print("\nMARKET BENCHMARK (pooled multiclass Brier, lower=better):")
    print(table.to_string(index=False))

    b = {r["source"]: r["brier"] for _, r in table.iterrows()}
    gap = b["model"] - b["market"]
    vs_elo = ("ahead of" if b["model"] < b.get("Elo only", b["model"]) else
              "level with" if b["model"] == b.get("Elo only", b["model"]) else "behind")
    print(f"\nhonest read: model is {gap:+.4f} Brier from the market "
          f"({'behind' if gap > 0 else 'ahead'}, as expected — the market sees lineups "
          f"and money the model excludes), and {vs_elo} Elo-only "
          f"[{b.get('Elo only')} Elo / {b['model']} model / {b['market']} market].")


if __name__ == "__main__":
    main()

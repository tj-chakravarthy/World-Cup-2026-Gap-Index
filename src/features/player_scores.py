"""Composite player score (PLAN.md §2.3) — 0-100, position-normalised.

One rating per 2026 squad player, blended by what data exists for him. Each input is
turned into a percentile *within position group within the 2026 field*, so the blend
mixes comparable 0-1 scales and the result is position-normalised by construction (a
GK and a FW are each ranked against their own kind).

DEVIATION from PLAN §2.3. PLAN used discrete tiers with predicted VAEP weighted up to
0.6. Predicted-VAEP's measured leave-one-tournament-out R^2 is ~0 (docs/deviations.md),
and the tier logic also dropped market value entirely on the observed branch — which
demoted stars who had one average tournament (Bellingham, top market value, fell to
65) below market-only fringe players, and let predicted-VAEP noise alone score back-up
keepers ~95. So the blend is reworked **market-anchored**: market value (the market's
aggregate talent prior) is the backbone weight, recent observed VAEP a moderate tilt,
predicted VAEP a small one (W_MARKET/W_OBS/W_PRED), renormalised over present
components. A player with neither market value nor observed VAEP is left unrated, not
scored from predicted noise. Predicted VAEP still enters the §3 indices and the §4.5
ablation on its own — that, not this display rating, is where it earns its keep.

Market value join is per nation (small candidate set); unmatched players are written to
a worklist that seeds name_overrides.csv. pandas only.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from src.features.player_features import position_group
from src.pipeline.name_matcher import Matcher, load_overrides, normalize

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"
PROC = REPO / "data" / "processed"

# market-anchored blend weights (see module docstring). Market value is the credible
# backbone; recent observed VAEP a moderate tilt; predicted VAEP (R^2~=0) a small one.
W_MARKET, W_OBS, W_PRED = 0.60, 0.25, 0.15
RECENT_TOURNAMENTS = ("world_cup_2022", "euro_2024")
RECENT_MIN_MINUTES = 180.0  # PLAN §2.3 "recent observed VAEP ... >=180 min"


def percentile_within_position(value: pd.Series, pos_group: pd.Series) -> pd.Series:
    """Rank a value into a 0-1 percentile within each position group. NaN stays NaN
    (no data -> no percentile). Pure, testable."""
    v = pd.to_numeric(value, errors="coerce")
    return v.groupby(pos_group).rank(pct=True)


def composite(obs_pct: float, pred_pct: float, mkt_pct: float) -> float:
    """Market-anchored blend of the available percentile components into a 0-1 score.

    Market value and recent observed VAEP are the credible signals; predicted VAEP
    (held-out R^2~=0) is only a small tilt and never a standalone rating. A player with
    neither market value nor observed VAEP is left unrated (NaN) rather than scored
    from predicted-VAEP noise (which e.g. ranks back-up keepers arbitrarily within the
    thin GK pool). Weights renormalise over whichever components are present. Pure."""
    if not (pd.notna(mkt_pct) or pd.notna(obs_pct)):
        return float("nan")
    parts = [(mkt_pct, W_MARKET), (obs_pct, W_OBS), (pred_pct, W_PRED)]
    present = [(v, w) for v, w in parts if pd.notna(v)]
    return sum(v * w for v, w in present) / sum(w for _, w in present)


def load_market_values(season: str = "2025", raw_dir: Path = RAW) -> dict[str, list[dict]]:
    """{country_code: [squad rows]} from the Transfermarkt per-nation value CSVs."""
    out: dict[str, list[dict]] = {}
    for path in sorted(raw_dir.glob(f"transfermarkt_*_{season}.csv")):
        m = re.match(rf"transfermarkt_(.+)_{season}\.csv$", path.name)
        if not m or m.group(1) == "team_ids":
            continue
        out[m.group(1)] = pd.read_csv(path).to_dict("records")
    return out


def join_market_value(squads: pd.DataFrame, tm: dict[str, list[dict]]
                      ) -> tuple[pd.Series, list[tuple[str, str]]]:
    """Per-nation fuzzy match of squad players to Transfermarkt values. Returns the
    market_value_eur series (aligned to squads) and the unmatched worklist."""
    overrides = load_overrides(context="player")
    mv = pd.Series(np.nan, index=squads.index)
    unmatched: list[tuple[str, str]] = []
    for code, group in squads.groupby("country_code"):
        cand = tm.get(code, [])
        by_norm = {normalize(c["player_name"]): c for c in cand}
        # threshold a touch below the default: the candidate set is one nation's squad
        # (~30-50 names), so collision risk is low and a looser match recovers spelling
        # variants (nicknames, transliterations) that cost real market-value coverage.
        matcher = Matcher(choices=[c["player_name"] for c in cand],
                          overrides=overrides, threshold=0.80)
        for idx, name in group["player_name"].items():
            target = matcher.match(name)[0] if cand else None
            if target is None:
                unmatched.append((code, name))
                continue
            val = by_norm.get(normalize(target), {}).get("market_value_eur")
            mv.at[idx] = pd.to_numeric(val, errors="coerce")
    return mv, unmatched


def recent_observed_pct(squads: pd.DataFrame, observed: pd.DataFrame,
                        pos_group: pd.Series) -> pd.Series:
    """Percentile of each squad player's most-recent observed tournament VAEP-per-90
    (WC22/Euro24, >=180 min), matched by name. NaN where the player has none."""
    rec = observed[observed["tournament"].isin(RECENT_TOURNAMENTS)
                   & (observed["minutes"].fillna(0) >= RECENT_MIN_MINUTES)]
    if rec.empty:
        return pd.Series(np.nan, index=squads.index)
    rec = (rec.sort_values("minutes", ascending=False)
              .drop_duplicates("player_name").set_index("player_name"))
    matcher = Matcher(choices=list(rec.index))
    vaep = pd.Series(np.nan, index=squads.index)
    for idx, name in squads["player_name"].items():
        target = matcher.match(name)[0]
        if target is not None:
            vaep.at[idx] = rec.at[target, "vaep_per90"]
    return percentile_within_position(vaep, pos_group)


def build_scores(squads: pd.DataFrame, predicted: pd.DataFrame, observed: pd.DataFrame,
                 tm: dict[str, list[dict]]) -> tuple[pd.DataFrame, list[tuple[str, str]]]:
    """Assemble the composite score table. Returns (scores, market unmatched)."""
    df = squads.copy()
    df["pos_group"] = df["position"].map(position_group)

    mv, unmatched = join_market_value(df, tm)
    df["market_value_eur"] = mv
    df["market_pct"] = percentile_within_position(mv, df["pos_group"])

    pred = predicted.set_index(["country_code", "player_name"])["vaep_per90_pred"]
    df["predicted_vaep"] = df.set_index(["country_code", "player_name"]).index.map(pred)
    df["predicted_pct"] = percentile_within_position(df["predicted_vaep"], df["pos_group"])

    df["observed_pct"] = recent_observed_pct(df, observed, df["pos_group"])

    df["composite"] = [composite(o, p, m) for o, p, m in
                       zip(df["observed_pct"], df["predicted_pct"], df["market_pct"])]
    df["player_score"] = (df["composite"] * 100).round(1)
    # data tier from coverage: Tier 1 = has 2025/26 club stats (predicted VAEP);
    # else Tier 3 = market value only. Tier 2 (intl-tournament FBref) not collected.
    df["data_tier"] = np.where(df["predicted_vaep"].notna(), 1,
                               np.where(df["market_value_eur"].notna(), 3, 0))
    return df, unmatched


def main() -> None:
    squads = pd.read_csv(RAW / "squads_2026.csv")
    predicted = pd.read_csv(PROC / "predicted_vaep.csv")
    observed = pd.read_csv(PROC / "vaep_observed.csv")
    tm = load_market_values("2025")

    df, unmatched = build_scores(squads, predicted, observed, tm)

    cols = ["country_code", "player_name", "position", "pos_group", "data_tier",
            "market_value_eur", "predicted_vaep", "observed_pct", "market_pct",
            "predicted_pct", "player_score"]
    PROC.mkdir(parents=True, exist_ok=True)
    out = PROC / "player_scores.csv"
    df[cols].to_csv(out, index=False)

    scored = df["player_score"].notna().sum()
    print(f"scored {scored}/{len(df)} players -> {out.relative_to(REPO)}")
    print("data tiers:", df["data_tier"].value_counts().to_dict())
    print(f"market value: {df['market_value_eur'].notna().sum()} | "
          f"predicted VAEP: {df['predicted_vaep'].notna().sum()} | "
          f"recent observed: {df['observed_pct'].notna().sum()}")
    if unmatched:
        wl = RAW / "name_unmatched_squad_transfermarkt.csv"
        pd.DataFrame(unmatched, columns=["country_code", "player_name"]).to_csv(wl, index=False)
        print(f"\nmarket-value unmatched ({len(unmatched)}) -> {wl.name} (seeds overrides)")
    for c in ("ENG", "BRA", "FRA"):
        g = df[df.country_code == c].nlargest(5, "player_score")
        print(f"  {c} top5:", ", ".join(f"{r.player_name}({r.player_score:.0f})"
                                        for r in g.itertuples()))


if __name__ == "__main__":
    main()

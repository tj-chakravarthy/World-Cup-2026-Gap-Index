"""Player feature table from FBref club stats (PLAN.md §2.3 / §3 inputs).

Turns the merged club-season stats (club_stats.load_club_stats) into one rated row
per player: identity + per-90 rate features + each feature's percentile rank
within (season, position group). Percentiles are the FBref-percentile component of
the composite player score (PLAN §2.3) and feed the squad indices (§3).

The headless FBref scrape currently returns only basic box-score stats; the
Opta-derived advanced stats (xG, npxG, xA, progression, passing/defense/possession
detail) are withheld and await the headed-browser (xvfb) fetch. So `build_features`
uses whichever CANDIDATE_FEATURES are present AND populated — the basic set works
now, the advanced ones slot in automatically once the headed fetch lands, no code
change. pandas only.
"""

from __future__ import annotations

import pandas as pd

from src.features.club_stats import load_club_stats

_POS_GROUP = {"GK": "GK", "DF": "DF", "MF": "MF", "FW": "FW"}

# rate features across stat groups; build_features keeps the ones with real data.
CANDIDATE_FEATURES = [
    # basic box-score (served by the headless scrape today)
    "goals_per90", "assists_per90", "goals_assists_per90",
    "shooting_shots_per90", "shooting_shots_on_target_per90",
    # advanced (withheld from headless; populate via the xvfb headed fetch)
    "passing_passes_progressive_distance", "passing_passes_into_penalty_area",
    "defense_tackles_interceptions", "defense_blocks",
    "possession_carries_progressive_distance", "possession_touches_att_pen_area",
    "possession_take_ons_won",
]


def position_group(pos) -> str:
    """FW,MF / DF / GK / … -> coarse group for within-position normalization."""
    if not isinstance(pos, str) or not pos:
        return "NA"
    return _POS_GROUP.get(pos.split(",")[0].strip(), "NA")


def available_features(df: pd.DataFrame) -> list[str]:
    """CANDIDATE_FEATURES that are present and have at least one real value."""
    out = []
    for c in CANDIDATE_FEATURES:
        if c in df.columns and pd.to_numeric(df[c], errors="coerce").notna().any():
            out.append(c)
    return out


def build_features(merged: pd.DataFrame, min_90s: float = 5.0) -> pd.DataFrame:
    """Add pos_group, numeric rate features, an eligibility flag, and a percentile
    rank per feature within (season, position group). Players under `min_90s`
    don't get a percentile (too small a sample) but stay in the table."""
    df = merged.copy()
    df["pos_group"] = df["position"].map(position_group)
    df["minutes_90s"] = pd.to_numeric(df.get("minutes_90s"), errors="coerce")
    feats = available_features(df)
    for c in feats:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["enough_minutes"] = df["minutes_90s"].fillna(0.0) >= min_90s
    for c in feats:
        eligible = df[c].where(df["enough_minutes"])
        df[f"{c}_pct"] = eligible.groupby([df["season"], df["pos_group"]]).rank(pct=True)
    return df


def load_player_features(leagues=None, seasons=None, min_90s: float = 5.0) -> pd.DataFrame:
    """Convenience: merge club stats from disk and build the feature table."""
    return build_features(load_club_stats(leagues=leagues, seasons=seasons), min_90s)

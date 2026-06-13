"""FBref club-stats loader (Stage 2 input contract).

Turns the per-(league, season, stat_type) CSVs that fetch_club_stats.py writes
into one tidy table: one row per player-club-season, with the six stat types
merged side by side. This is the bridge from the raw scrape to the predicted-VAEP
model (PLAN §2.2) and the squad indices (PLAN §3); feature engineering reads from
here, not from the raw files.

Merge: the standard table is the base (identity + playing time + scoring). Each
other stat type is joined on (Player, Squad), its shared/identity columns dropped
and its own metrics prefixed with the stat name (shooting_Standard_Sh,
passing_Total_Cmp, …) so nothing collides. A folded join name is added for the
later club/player name matching.

pandas only (in the CI dev subset); no network.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from src.pipeline.name_matcher import normalize

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"

STATS = ["standard", "shooting", "passing", "defense", "possession", "misc"]
# FBref data-stat keys. Identity columns repeat in every stat table; the standard
# table carries them, so they (plus file metadata and the redundant 90s count) are
# dropped from the others before merging.
IDENTITY = ["player", "team", "nationality", "position", "age", "birth_year"]
_DROP = set(IDENTITY) | {"league", "season", "stat_type", "minutes_90s"}
_KEY = ["player", "team"]


def merge_stats(by_stat: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Merge the six stat-type frames for one (league, season) into one row per
    player-club. `standard` is required as the base."""
    if "standard" not in by_stat:
        raise ValueError("merge_stats needs the 'standard' table as the base")
    merged = (by_stat["standard"]
              .drop(columns=["stat_type"], errors="ignore")
              .drop_duplicates(_KEY))
    for st in STATS:
        if st == "standard" or st not in by_stat:
            continue
        df = by_stat[st].drop_duplicates(_KEY)
        specific = [c for c in df.columns
                    if c not in _DROP and c not in _KEY and c not in merged.columns]
        sub = df[_KEY + specific].rename(columns={c: f"{st}_{c}" for c in specific})
        merged = merged.merge(sub, on=_KEY, how="left")
    merged.insert(merged.columns.get_loc("player") + 1,
                  "player_name_norm", merged["player"].map(normalize))
    return merged


def load_club_stats(leagues=None, seasons=None, raw_dir: Path = RAW) -> pd.DataFrame:
    """Load and merge every (league, season) present on disk into one tidy table.
    `leagues`/`seasons` (iterables) narrow what is loaded; default is everything
    pulled so far."""
    groups: dict[tuple[str, str], dict[str, pd.DataFrame]] = {}
    for path in sorted(raw_dir.glob("fbref_*_*_*.csv")):
        m = re.match(r"fbref_(.+)_(\d{4}-\d{4})_([a-z]+)\.csv$", path.name)
        if not m:
            continue
        league, season, stat = m.groups()
        if (leagues and league not in leagues) or (seasons and season not in seasons):
            continue
        groups.setdefault((league, season), {})[stat] = pd.read_csv(path)

    frames = []
    for (league, season), by_stat in sorted(groups.items()):
        # need the standard base, and skip any stale-schema CSVs (pre data-stat)
        if "standard" not in by_stat or "player" not in by_stat["standard"].columns:
            continue
        frames.append(merge_stats(by_stat))
    if not frames:
        raise FileNotFoundError(f"no FBref club-stat CSVs found under {raw_dir}")
    return pd.concat(frames, ignore_index=True)

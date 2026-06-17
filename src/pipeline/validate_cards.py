"""Validate the hand-maintained data/raw/cards_2026.csv (group-stage conduct, Art. 13 §1 f).

No card feed is wired (no key), so conduct runs at zero until cards are entered by hand. This is
the manual path: fill one row per (fixture_id, team_code) with card counts, run this to check it,
commit, and the simulator's load_conduct feeds it into the tiebreaker on the next update. The
check keeps a typo (a stray code, a negative, a non-integer) from silently skewing the standings.

Columns: fixture_id, team_code, then any of: yellow, indirect_red, direct_red,
yellow_and_direct_red. An empty (header-only) file is valid — it's the zero-conduct default.
pandas + stdlib.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from src.models.tiebreakers import CARD_POINTS, conduct_score

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"
CARDS_CSV = RAW / "cards_2026.csv"
TEAM_CODES = RAW / "team_codes.csv"

CARD_COLS = list(CARD_POINTS)          # yellow, indirect_red, direct_red, yellow_and_direct_red
REQUIRED = ["fixture_id", "team_code"]


def validate_cards(df: pd.DataFrame, field_codes: set[str]) -> None:
    """Raise ValueError if the cards frame is malformed. Header-only (no rows) is valid."""
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"cards: missing required column(s) {missing}")
    card_cols = [c for c in CARD_COLS if c in df.columns]
    if not card_cols:
        raise ValueError(f"cards: needs at least one card column from {CARD_COLS}")
    unknown = sorted(set(df["team_code"].dropna()) - field_codes)
    if unknown:
        raise ValueError(f"cards: unknown team_code(s) (not in the 48-team field): {unknown}")
    for c in card_cols:
        col = pd.to_numeric(df[c], errors="coerce")
        if col.isna().any() or (col < 0).any() or (col % 1 != 0).any():
            raise ValueError(f"cards: column {c!r} must be non-negative integers")


def main() -> None:
    if not CARDS_CSV.exists():
        print(f"no {CARDS_CSV.name} — conduct runs at zero (documented fallback)")
        return
    df = pd.read_csv(CARDS_CSV)
    field = set(pd.read_csv(TEAM_CODES)["fifa_code"])
    try:
        validate_cards(df, field)
    except ValueError as e:
        print(e, file=sys.stderr)
        sys.exit(1)
    kinds = [k for k in CARD_COLS if k in df.columns]
    by_team = {}
    for r in df.itertuples(index=False):
        cards = {k: int(getattr(r, k) or 0) for k in kinds}
        by_team[r.team_code] = by_team.get(r.team_code, 0) + conduct_score(cards)
    print(f"cards OK: {len(df)} row(s), {len(by_team)} team(s); conduct {by_team or '(none)'}")


if __name__ == "__main__":
    main()

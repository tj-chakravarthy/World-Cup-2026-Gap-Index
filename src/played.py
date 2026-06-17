"""How to read the fixtures `played` flag — one coercion, used everywhere.

The column round-trips as a bool, a 'True'/'False' string, or 1/0 depending on how it was
written and re-read. A bare `== True` then misses the string form and `bool('False')` is
wrongly truthy, so resolve(), the Monte Carlo and run_all must not each roll their own. Pure,
pandas only.
"""

from __future__ import annotations

import pandas as pd

_TRUE_STRINGS = {"true", "1"}


def is_played(value) -> bool:
    """True iff `value` marks a fixture played, across bool / 'True'-'False' / 1-0 / NaN."""
    if pd.isna(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() in _TRUE_STRINGS
    return bool(value)


def played_mask(played: pd.Series) -> pd.Series:
    """Boolean mask over a fixtures `played` column, robust to bool/string/int encodings."""
    return played.map(is_played).astype(bool)

"""Fuzzy name matcher with manual overrides (PLAN.md §"Known Challenges").

The single highest-risk data step: club and player names differ across sources
(squad page "PSV Eindhoven" vs clubelo "PSV"; FBref vs Transfermarkt spellings).
This resolves a source name to a canonical target by, in order: a hand-curated
override, an exact normalised match, then a fuzzy score above threshold.
Anything below threshold returns no match and is surfaced for the mandatory
manual review — auto-matching the easy majority, flagging the rest, never
guessing silently.

`name_overrides.csv` is the append-only record of manual corrections (committed).
rapidfuzz is used when present (it's in the apt base); a stdlib difflib fallback
keeps the matcher working in the bare dev/CI env so the tests run without it.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass, field
from importlib import util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OVERRIDES_CSV = REPO / "data" / "raw" / "name_overrides.csv"
OVERRIDE_FIELDS = ["source", "target", "context", "note"]

_HAS_RAPIDFUZZ = util.find_spec("rapidfuzz") is not None


def normalize(name: str) -> str:
    """ASCII-folded, lower-cased, punctuation-stripped, single-spaced key."""
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    folded = re.sub(r"[^a-zA-Z0-9 ]", " ", folded)
    return re.sub(r"\s+", " ", folded).strip().lower()


def _similarity(a: str, b: str) -> float:
    """0..1 similarity on normalised names, order-insensitive on tokens."""
    if _HAS_RAPIDFUZZ:
        from rapidfuzz.fuzz import token_sort_ratio
        return token_sort_ratio(a, b) / 100.0
    from difflib import SequenceMatcher
    a2, b2 = " ".join(sorted(a.split())), " ".join(sorted(b.split()))
    return SequenceMatcher(None, a2, b2).ratio()


def load_overrides(path: Path = OVERRIDES_CSV, context: str | None = None) -> dict[str, str]:
    """source name -> target name. `context` (e.g. 'club', 'player') narrows the
    table when one source spelling maps differently in different domains."""
    if not path.exists():
        return {}
    out = {}
    for r in csv.DictReader(path.open()):
        if context is None or not r.get("context") or r["context"] == context:
            out[r["source"]] = r["target"]
    return out


@dataclass
class Matcher:
    """Resolve source names to one of `choices`. Build once per target set."""
    choices: list[str]
    overrides: dict[str, str] = field(default_factory=dict)
    threshold: float = 0.84

    def __post_init__(self):
        self._norm_to_choice = {normalize(c): c for c in self.choices}

    def match(self, name: str) -> tuple[str | None, float, str]:
        """Return (target or None, score, method) with method in
        {'override', 'exact', 'fuzzy', 'none'}."""
        if name in self.overrides:
            return self.overrides[name], 1.0, "override"
        n = normalize(name)
        if n in self._norm_to_choice:
            return self._norm_to_choice[n], 1.0, "exact"
        best, best_score = None, 0.0
        for c in self.choices:
            s = _similarity(n, normalize(c))
            if s > best_score:
                best, best_score = c, s
        if best_score >= self.threshold:
            return best, best_score, "fuzzy"
        return None, best_score, "none"

    def unmatched(self, names) -> list[tuple[str, float]]:
        """Source names that resolve to nothing, with their best near-miss score —
        the worklist for the manual override review (best score first)."""
        miss = [(name, self.match(name)[1]) for name in names if self.match(name)[0] is None]
        return sorted(miss, key=lambda kv: kv[1], reverse=True)

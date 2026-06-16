"""FIFA World Cup 26 knockout bracket — structure as data.

48 teams, 12 groups A-L. Top 2 of each group plus the 8 best third-placed teams
(ranking + best-8-thirds live in tiebreakers.py, not here) enter a 32-team single
elimination: R32 -> R16 -> QF -> SF -> Final, plus a third-place playoff between the
two semifinal losers.

This module is only the *wiring*: it reads the committed fixtures_2026.csv for the R32
slot strings and encodes the R16..Final feeder adjacency from FIFA's official schedule.

Slot strings (R32, as written in the CSV):
  "1A" = winner of group A, "2B" = runner-up of group B,
  "3ABCDF" = a third-placed team from one of groups {A,B,C,D,F}.

Bracket adjacency (R16->Final) verified against FIFA's official knockout schedule,
cross-checked between two independent reproductions (Wikipedia "2026 FIFA World Cup
knockout stage" and NBC Sports). Both agree exactly. Match numbers:
  R32 73-88, R16 89-96, QF 97-100, SF 101-102, third place 103, final 104.

Third-place allocation: FIFA publishes a 495-row table (Annex C; one row per way to
pick 8 of 12 thirds) mapping each qualifying third to one of the eight 3-slots. The real
table is now committed (fetch_annex_c -> data/raw/annex_c_thirds.csv, from the public
knockout-stage article that reproduces Annex C verbatim); allocate_thirds() uses it and is
exact. If the file is absent it falls back to solving the *constraint* the slot strings
encode directly — assign each qualifying group to a slot whose group-set contains it,
one-to-one: a valid (constraint-respecting, bijective) stand-in, deterministic given the
input, but not guaranteed to be FIFA's row. Either way the bracket tree above (every
team's deep-run path) is exact; only which third lands in which R32 match was approximate.

pandas only for the CSV read; the bracket logic is pure and testable.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "data" / "raw" / "fixtures_2026.csv"
ANNEX_C = REPO / "data" / "raw" / "annex_c_thirds.csv"

GROUPS = list("ABCDEFGHIJKL")

# R16->final feeders: (match, feeder1, feeder2). Winners of feeder1 and feeder2 meet at
# match. Match 104 is the final; the third-place playoff (M103) is the two SF *losers*,
# represented below as a separate row whose feeders are the SF matches (loser semantics,
# not winner) — see THIRD_PLACE.
_TREE = [
    # Round of 16
    ("WC26-M089", "WC26-M074", "WC26-M077"),
    ("WC26-M090", "WC26-M073", "WC26-M075"),
    ("WC26-M091", "WC26-M076", "WC26-M078"),
    ("WC26-M092", "WC26-M079", "WC26-M080"),
    ("WC26-M093", "WC26-M083", "WC26-M084"),
    ("WC26-M094", "WC26-M081", "WC26-M082"),
    ("WC26-M095", "WC26-M086", "WC26-M088"),
    ("WC26-M096", "WC26-M085", "WC26-M087"),
    # Quarterfinals
    ("WC26-M097", "WC26-M089", "WC26-M090"),
    ("WC26-M098", "WC26-M093", "WC26-M094"),
    ("WC26-M099", "WC26-M091", "WC26-M092"),
    ("WC26-M100", "WC26-M095", "WC26-M096"),
    # Semifinals
    ("WC26-M101", "WC26-M097", "WC26-M098"),
    ("WC26-M102", "WC26-M099", "WC26-M100"),
    # Final
    ("WC26-M104", "WC26-M101", "WC26-M102"),
]

# Third-place playoff: the two SF losers. Same shape as a _TREE row, but the feeders
# contribute their *losers*, not winners — the simulator must read THIRD_PLACE, not
# treat M103 like a normal winner-fed node.
THIRD_PLACE = ("WC26-M103", "WC26-M101", "WC26-M102")

BRACKET_TREE: list[tuple[str, str, str]] = _TREE + [THIRD_PLACE]


def _knockout() -> pd.DataFrame:
    df = pd.read_csv(FIXTURES, dtype=str)
    return df[df["stage"].isin(["R32", "R16", "QF", "SF", "third_place", "final"])]


def r32_matchups() -> list[tuple[str, str, str]]:
    """(fixture_id, slot1, slot2) for the 16 R32 matches, slot strings as in the CSV
    ("1A","2B","3ABCDF"). Ordered by match number."""
    df = _knockout()
    r32 = df[df["stage"] == "R32"].sort_values("match_number", key=lambda c: c.astype(int))
    return [(r.fixture_id, r.home_team, r.away_team) for r in r32.itertuples()]


def _third_slots() -> list[str]:
    """The eight "3XYZ..." slot strings present in the R32 rows, match-number order."""
    return [s for _, a, b in r32_matchups() for s in (a, b) if s.startswith("3")]


def _slot_winner() -> dict[str, str]:
    """Each "3..." slot string -> the group letter of the "1X" winner it meets in R32.
    Annex C is keyed by that winner, so this bridges its rows to our slot strings."""
    out: dict[str, str] = {}
    for _, a, b in r32_matchups():
        if a.startswith("1") and b.startswith("3"):
            out[b] = a[1]
        elif b.startswith("1") and a.startswith("3"):
            out[a] = b[1]
    return out


def load_annex_c(path: Path = ANNEX_C) -> dict[frozenset, dict[str, str]] | None:
    """FIFA's exact third-place table (fetch_annex_c): {qualifying-group set -> {winner
    group -> third group}}. None if the file is absent, so allocate_thirds falls back to
    the constraint solver."""
    if not path.exists():
        return None
    df = pd.read_csv(path)
    winners = [c[2:] for c in df.columns if c.startswith("w_")]
    return {frozenset(r.groups): {w: getattr(r, f"w_{w}") for w in winners}
            for r in df.itertuples(index=False)}


def allocate_thirds(qualified_third_groups: list[str]) -> dict[str, str]:
    """Map each third-slot string (e.g. "3ABCDF") to the single group letter that fills
    it. `qualified_third_groups` is the 8 group letters whose thirds qualified.

    Respects the slot's group-set (the letters after "3"), one group per slot, bijective.
    Solved as a bipartite perfect matching by backtracking with most-constrained-slot-
    first ordering (deterministic; 8 nodes, trivial). Raises ValueError on a bad input
    (wrong count, unknown/duplicate group) or if no valid assignment exists.

    Uses FIFA's exact Annex C table (load_annex_c) when present; falls back to the
    constraint solver below — a valid bijection, but not necessarily FIFA's row — when it
    isn't."""
    qual = list(qualified_third_groups)
    if len(qual) != 8:
        raise ValueError(f"need exactly 8 qualifying third groups, got {len(qual)}: {qual}")
    if len(set(qual)) != 8:
        raise ValueError(f"duplicate third groups: {qual}")
    bad = [g for g in qual if g not in GROUPS]
    if bad:
        raise ValueError(f"unknown group letters: {bad}")

    exact = load_annex_c()
    if exact is not None and (table := exact.get(frozenset(qual))) is not None:
        sw = _slot_winner()
        assignment = {}
        for slot in _third_slots():
            g = table.get(sw.get(slot))
            if g is None or g not in slot[1:]:   # table disagrees with slot strings -> solver
                assignment = None
                break
            assignment[slot] = g
        if assignment is not None and sorted(assignment.values()) == sorted(qual):
            return assignment

    slots = _third_slots()
    remaining = set(qual)
    # candidates per slot, restricted to groups that actually qualified
    cand = {s: [g for g in s[1:] if g in remaining] for s in slots}
    assignment: dict[str, str] = {}

    def solve(left: list[str]) -> bool:
        if not left:
            return True
        # most-constrained slot first: fewest still-available candidates
        left.sort(key=lambda s: sum(1 for g in cand[s] if g in remaining))
        slot = left[0]
        for g in cand[slot]:
            if g not in remaining:
                continue
            assignment[slot] = g
            remaining.discard(g)
            if solve(left[1:]):
                return True
            remaining.add(g)
            del assignment[slot]
        return False

    if not solve(slots):
        raise ValueError(
            f"no valid third-place allocation for groups {qual} into slots {slots}"
        )
    return assignment


def resolve_r32(
    group_rankings: dict[str, list[str]],
    qualified_third_groups: list[str],
) -> dict[str, tuple[str, str]]:
    """fixture_id -> (team1, team2) for the 16 R32 matches.

    `group_rankings` maps each group letter -> [1st, 2nd, 3rd, 4th] team names.
    "1A"/"2B" resolve from the rankings (1->index 0, 2->index 1); "3XYZ..." resolves via
    allocate_thirds, then takes that group's 3rd-placed team (index 2)."""
    thirds = allocate_thirds(qualified_third_groups)

    def team(slot: str) -> str:
        rank, group = slot[0], slot[1:]
        if rank == "3":
            group = thirds[slot]          # slot's group-set -> the filling group
            return group_rankings[group][2]
        return group_rankings[group][{"1": 0, "2": 1}[rank]]

    return {fx: (team(a), team(b)) for fx, a, b in r32_matchups()}


def bracket_tree() -> list[tuple[str, str, str]]:
    """(match, feeder1, feeder2) for every knockout match R16..final plus the third-place
    playoff. Winners of feeder1/feeder2 meet at `match` — except the third-place row
    (THIRD_PLACE), whose feeders contribute their losers. Same data as BRACKET_TREE."""
    return list(BRACKET_TREE)

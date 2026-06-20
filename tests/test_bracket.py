"""WC26 knockout bracket structure (src/models/bracket.py).

Guards the R32 slot parse, the third-place allocation (constraint-respecting bijection),
the R32 team resolution, and the R16->final tree shape. The bracket adjacency is FIFA's
official schedule (Wikipedia + NBC cross-checked); these tests lock that it stays a clean
32->1 single elimination and that no fixture feeds two matches.
"""

import re

import pytest

pytest.importorskip("pandas")  # reads the committed fixtures CSV

from src.models.bracket import (
    BRACKET_TREE,
    GROUPS,
    THIRD_PLACE,
    allocate_thirds,
    bracket_tree,
    load_annex_c,
    r32_matchups,
    resolve_r32,
)

_SLOT_RE = re.compile(r"^(?:[12][A-L]|3[A-L]{2,})$")


def test_groups():
    assert GROUPS == list("ABCDEFGHIJKL")


def test_r32_sixteen_wellformed_slots():
    m = r32_matchups()
    assert len(m) == 16
    fids = [fx for fx, _, _ in m]
    assert len(set(fids)) == 16
    for fx, a, b in m:
        assert _SLOT_RE.match(a), f"bad slot {a} in {fx}"
        assert _SLOT_RE.match(b), f"bad slot {b} in {fx}"
    # exactly 8 third-slots, each a distinct multi-group set
    thirds = [s for _, a, b in m for s in (a, b) if s.startswith("3")]
    assert len(thirds) == 8
    assert len(set(thirds)) == 8
    for s in thirds:
        assert len(s) >= 3  # "3" + at least two group letters


def test_r32_slots_stay_static_not_resolved_names():
    # Regression: the live feed overwrites fixtures_2026.csv home_team/away_team with the
    # resolved team names once it slots group winners ("1A" -> "Mexico"). The R32 structure
    # must stay the slot strings (a committed constant), or resolve_r32 parses a country name
    # as a slot — group "Mexico"[1:] = "exico" -> KeyError. Host slots resolve earliest; pin one.
    m = {fx: (a, b) for fx, a, b in r32_matchups()}
    assert m["WC26-M079"] == ("1A", "3CEFHI")


def _is_valid_alloc(alloc, qual):
    from src.models.bracket import _third_slots

    slots = _third_slots()
    assert set(alloc) == set(slots)                     # every slot filled
    assert sorted(alloc.values()) == sorted(qual)       # bijective onto the qualifiers
    for slot, g in alloc.items():
        assert g in slot[1:], f"{g} not allowed in slot {slot}"


def test_allocate_thirds_real_scenario():
    # plausible real set: the eight best thirds come from these groups
    qual = list("ABEFGHIJ")
    alloc = allocate_thirds(qual)
    _is_valid_alloc(alloc, qual)


def test_allocate_thirds_another_combo():
    qual = list("CDEFIJKL")
    alloc = allocate_thirds(qual)
    _is_valid_alloc(alloc, qual)


def test_allocate_thirds_deterministic():
    qual = list("ABEFGHIJ")
    assert allocate_thirds(qual) == allocate_thirds(qual)


def test_allocate_thirds_all_495_feasible():
    # FIFA's slot group-sets are built so every 8-of-12 set has a valid assignment.
    # With the real Annex C committed this also cross-checks that FIFA's table agrees
    # with our R32 slot strings (each assigned third lands in a slot whose set allows it).
    from itertools import combinations

    for combo in combinations(GROUPS, 8):
        qual = list(combo)
        _is_valid_alloc(allocate_thirds(qual), qual)


def test_annex_c_table_loaded_and_complete():
    table = load_annex_c()
    assert table is not None, "annex_c_thirds.csv must be committed"
    assert len(table) == 495
    # the published Annex C row for thirds from {E,F,G,H,I,J,K,L}
    assert table[frozenset("EFGHIJKL")] == {
        "A": "E", "B": "J", "D": "I", "E": "F", "G": "H", "I": "G", "K": "L", "L": "K"}


def test_allocate_thirds_is_exact_annex_c():
    # the exact FIFA assignment for {E,F,G,H,I,J,K,L} (knockout-stage article, Annex C) —
    # proves the real table is wired, not just a constraint-valid bijection
    expected = {"3ABCDF": "F", "3CDFGH": "G", "3CEFHI": "E", "3EHIJK": "K",
                "3BEFIJ": "I", "3AEHIJ": "H", "3EFGIJ": "J", "3DEIJL": "L"}
    assert allocate_thirds(list("EFGHIJKL")) == expected


def test_allocate_thirds_raises_bad_input():
    with pytest.raises(ValueError):
        allocate_thirds(list("ABCDEFG"))            # only 7
    with pytest.raises(ValueError):
        allocate_thirds(list("ABCDEFGHI"))          # 9
    with pytest.raises(ValueError):
        allocate_thirds(list("ABCDEFGZ"))           # unknown group Z
    with pytest.raises(ValueError):
        allocate_thirds(list("AABCDEFG"))           # duplicate A


def test_allocate_thirds_raises_when_no_assignment(monkeypatch):
    # Drop L from every slot, then demand L be placed: the matcher must fail loud.
    import src.models.bracket as b

    monkeypatch.setattr(
        b, "_third_slots",
        lambda: ["3ABCDF", "3CDFGH", "3CEFHI", "3EHIJK", "3BEFIJ", "3AEHIJ", "3EFGIJ", "3DEIJ"],
    )
    with pytest.raises(ValueError, match="no valid"):
        b.allocate_thirds(list("ABCGHIJL"))         # L has no slot


def _synthetic_rankings():
    # each group -> [1st,2nd,3rd,4th] with globally distinct names
    return {g: [f"{g}{r}" for r in (1, 2, 3, 4)] for g in GROUPS}


def test_resolve_r32_32_distinct_teams():
    rankings = _synthetic_rankings()
    qual = list("ABEFGHIJ")
    resolved = resolve_r32(rankings, qual)
    assert len(resolved) == 16
    teams = [t for pair in resolved.values() for t in pair]
    assert len(teams) == 32
    assert len(set(teams)) == 32                    # no team in two matches
    # every "3" slot resolved to a third-placed team of a qualified group
    thirds_used = {t for t in teams if t.endswith("3")}
    assert thirds_used == {f"{g}3" for g in qual}


def test_bracket_tree_shape():
    tree = bracket_tree()
    assert tree == BRACKET_TREE
    matches = [m for m, _, _ in tree]
    assert len(matches) == len(set(matches)) == 16  # 8 R16 + 4 QF + 2 SF + 1 final + TP

    by_stage = {
        "R16": [f"WC26-M{n:03d}" for n in range(89, 97)],
        "QF": [f"WC26-M{n:03d}" for n in range(97, 101)],
        "SF": [f"WC26-M{n:03d}" for n in range(101, 103)],
        "final": ["WC26-M104"],
        "third": ["WC26-M103"],
    }
    present = set(matches)
    assert present == set(sum(by_stage.values(), []))
    assert len(by_stage["R16"]) == 8
    assert len(by_stage["QF"]) == 4
    assert len(by_stage["SF"]) == 2


def test_bracket_tree_feeders_exist():
    r32_ids = {fx for fx, _, _ in r32_matchups()}
    match_ids = {m for m, _, _ in BRACKET_TREE}
    known = r32_ids | match_ids
    for m, f1, f2 in BRACKET_TREE:
        assert f1 in known, f"{m} feeder {f1} unknown"
        assert f2 in known, f"{m} feeder {f2} unknown"
        assert f1 != f2


def test_bracket_no_fixture_feeds_two_winner_matches():
    # Winner-fed feeders (everything except the third-place playoff) must be disjoint:
    # each match's winner advances to exactly one place. The two SF feed BOTH the final
    # and the third-place game, which is correct (winners->final, losers->M103), so the
    # third-place row is excluded from this count.
    winner_tree = [r for r in BRACKET_TREE if r != THIRD_PLACE]
    feeders = [f for _, f1, f2 in winner_tree for f in (f1, f2)]
    assert len(feeders) == len(set(feeders))


def test_third_place_is_two_sf():
    assert THIRD_PLACE == ("WC26-M103", "WC26-M101", "WC26-M102")


def test_single_elimination_reduces_32_to_1():
    # Walk the winner-tree: 16 R32 matches produce 16 winners; following the adjacency
    # must collapse to a single final and one champion.
    r32 = r32_matchups()
    assert len(r32) == 16
    winner_tree = {m: (f1, f2) for m, f1, f2 in BRACKET_TREE if m != THIRD_PLACE[0]}

    # each non-R32 match consumes exactly two distinct upstream winners
    consumed = [f for fs in winner_tree.values() for f in fs]
    assert len(consumed) == len(set(consumed))
    # 16 R32 + 15 downstream-winner matches consumed as feeders == 31 nodes feeding,
    # leaving exactly one terminal node (the final)
    all_match_nodes = {fx for fx, _, _ in r32} | set(winner_tree)
    terminal = all_match_nodes - set(consumed)
    assert terminal == {"WC26-M104"}                # the final is the unique root


def _simulate(resolved, winner_pick):
    """Resolve R32 + walk the winner tree, picking a winner per match via `winner_pick`.
    Returns (champion, third_place)."""
    winners: dict[str, str] = {}
    for fx, (t1, t2) in resolved.items():
        winners[fx] = winner_pick(fx, t1, t2)
    # topological-ish: BRACKET_TREE is already ordered R16..final
    losers: dict[str, str] = {}
    for m, f1, f2 in BRACKET_TREE:
        if m == THIRD_PLACE[0]:
            continue
        a, b = winners[f1], winners[f2]
        w = winner_pick(m, a, b)
        winners[m] = w
        losers[m] = b if w == a else a
    tp_w = winner_pick(THIRD_PLACE[0], losers["WC26-M101"], losers["WC26-M102"])
    return winners["WC26-M104"], tp_w


def test_smoke_full_walk_one_champion():
    rankings = _synthetic_rankings()
    qual = list("ABEFGHIJ")
    resolved = resolve_r32(rankings, qual)

    # deterministic pick: alphabetically-first team name wins
    champion, third = _simulate(resolved, lambda fx, a, b: min(a, b))
    assert isinstance(champion, str)
    assert isinstance(third, str)
    # both come from the resolved field
    field = {t for pair in resolved.values() for t in pair}
    assert champion in field
    assert third in field

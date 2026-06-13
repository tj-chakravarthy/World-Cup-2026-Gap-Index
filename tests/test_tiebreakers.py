"""FIFA Art. 13 tiebreaker tests — MANDATORY (PLAN.md §5.1).

Hand-constructed scenarios verified against the official Art. 13 order:
head-to-head BEFORE overall GD, conduct score, then FIFA ranking (no lots).
Several scenarios are built so the *old* 2018/2022 order (overall GD first)
would give a different answer — they fail loudly if the order regresses.
"""

import pytest

from src.models.tiebreakers import (
    Match,
    Standing,
    conduct_score,
    rank_group,
    rank_third_placed,
)

pytestmark = pytest.mark.mandatory


def test_no_ties_sorts_by_points():
    matches = [
        Match("A", "B", 2, 0),
        Match("A", "C", 2, 0),
        Match("A", "D", 2, 0),
        Match("B", "C", 1, 0),
        Match("B", "D", 1, 0),
        Match("C", "D", 1, 0),
    ]
    fifa = {"A": 1, "B": 2, "C": 3, "D": 4}
    # A 9, B 6, C 3, D 0 — strictly by points, no tiebreak needed.
    assert rank_group(matches, fifa) == ["A", "B", "C", "D"]


def test_three_way_head_to_head_tie():
    """A, B, C all finish on 6 pts. Head-to-head is a points cycle, so Step 1
    falls to H2H goal difference: C(+2) > B(0) > A(-2).

    Overall GD/goals would rank A first (A smashed D 5-0). The old order would
    therefore return A,C,B — this asserts head-to-head wins, as Art. 13 requires.
    """
    matches = [
        Match("A", "B", 1, 0),   # H2H cycle
        Match("C", "A", 3, 0),
        Match("B", "C", 1, 0),
        Match("A", "D", 5, 0),   # inflates A's OVERALL gd/gf only
        Match("B", "D", 1, 0),
        Match("C", "D", 1, 0),
    ]
    fifa = {"A": 1, "B": 2, "C": 3, "D": 4}  # not consulted; H2H separates fully
    assert rank_group(matches, fifa) == ["C", "B", "A", "D"]


def test_step2_falls_through_to_conduct_fair_play():
    """A and B are level on points, drew head-to-head, and have identical
    overall GD and goals. Art. 13 §1 f) (team conduct score) decides: A has one
    yellow (-1), B has an indirect red (-3), so A ranks above B.

    FIFA rank is set to favour B, so this also proves conduct is applied BEFORE
    the FIFA-ranking fallback.
    """
    matches = [
        Match("A", "B", 1, 1),
        Match("A", "C", 2, 0),
        Match("A", "D", 0, 1),
        Match("B", "C", 2, 0),
        Match("B", "D", 0, 1),
        Match("C", "D", 0, 0),
    ]
    # A, B both: 4 pts, GD +1, GF 3. D 7 (top), C 1 (bottom).
    conduct = {"A": conduct_score({"yellow": 1}),        # -1
               "B": conduct_score({"indirect_red": 1})}  # -3
    fifa = {"A": 2, "B": 1, "C": 3, "D": 4}  # would put B first if used too early
    assert rank_group(matches, fifa, conduct) == ["D", "A", "B", "C"]


def test_fifa_ranking_is_final_fallback():
    """A and B identical on points, H2H, overall GD/goals AND conduct (both 0).
    Only Step 3 separates them, by the FIFA ranking — no drawing of lots.
    """
    matches = [
        Match("A", "B", 1, 1),
        Match("A", "C", 2, 0),
        Match("A", "D", 0, 1),
        Match("B", "C", 2, 0),
        Match("B", "D", 0, 1),
        Match("C", "D", 0, 0),
    ]
    fifa = {"A": 2, "B": 9, "C": 3, "D": 4}  # A better ranked -> A above B
    assert rank_group(matches, fifa) == ["D", "A", "B", "C"]


def test_group_unresolved_when_fifa_rank_ties_raises():
    """A and B identical on points, H2H, overall GD/goals AND conduct — only the
    FIFA ranking is left, but they share a rank. The current edition can't
    separate them; Art. 13(h) (older editions) isn't loaded, so fail loud rather
    than fabricate an order (cf. test_fifa_ranking_is_final_fallback)."""
    matches = [
        Match("A", "B", 1, 1),
        Match("A", "C", 2, 0),
        Match("A", "D", 0, 1),
        Match("B", "C", 2, 0),
        Match("B", "D", 0, 1),
        Match("C", "D", 0, 0),
    ]
    fifa = {"A": 5, "B": 5, "C": 3, "D": 4}  # A,B share a rank -> unseparable
    with pytest.raises(ValueError, match="Art. 13"):
        rank_group(matches, fifa)


def test_third_place_unresolved_when_fifa_rank_ties_raises():
    """Two thirds identical on every criterion incl. the FIFA ranking — fail loud
    (Art. 13 h) instead of an arbitrary order."""
    thirds = [
        Standing("C", points=3, gd=0, gf=4, conduct=0, fifa_rank=8),
        Standing("D", points=3, gd=0, gf=4, conduct=0, fifa_rank=8),
    ]
    with pytest.raises(ValueError, match="Art. 13"):
        rank_third_placed(thirds)


def test_three_way_tie_partial_break_reapplies_h2h():
    """Three teams (A,B,C) tied on 6 pts. The full 3-way H2H table separates A
    (bottom) but leaves B and C identical on H2H pts/GD/goals. Step 2 re-applies
    H2H to the matches between the *remaining* teams only — the single B-C game,
    which B won 2-0 — so B finishes above C.

    C has a much larger OVERALL goal difference (it beat D 5-0), so the old
    overall-GD-first order would return C,B,A. This asserts the re-application
    of head-to-head wins, exactly as Art. 13 Step 2 requires.
    """
    matches = [
        Match("A", "B", 2, 1),   # 3-way H2H: B and C come out identical,
        Match("B", "C", 2, 0),   # A is separated at the bottom
        Match("C", "A", 3, 0),
        Match("A", "D", 1, 0),
        Match("B", "D", 1, 0),
        Match("C", "D", 5, 0),   # inflates C's OVERALL gd only, not its H2H
    ]
    fifa = {"A": 1, "B": 2, "C": 3, "D": 4}  # not consulted
    assert rank_group(matches, fifa) == ["B", "C", "A", "D"]


def test_third_place_ranking_order():
    """Best third-placed teams: points -> GD -> goals -> conduct -> FIFA rank.
    No head-to-head (different groups). C and D match on pts/GD/goals; conduct
    separates them ahead of the FIFA ranking.
    """
    thirds = [
        Standing("A", points=4, gd=2, gf=5, conduct=0, fifa_rank=20),
        Standing("B", points=3, gd=1, gf=3, conduct=0, fifa_rank=15),
        Standing("C", points=3, gd=0, gf=4, conduct=0, fifa_rank=8),
        Standing("D", points=3, gd=0, gf=4, conduct=-3, fifa_rank=2),
        Standing("E", points=3, gd=0, gf=2, conduct=0, fifa_rank=1),
        Standing("F", points=1, gd=-3, gf=1, conduct=0, fifa_rank=3),
    ]
    ranked = [s.team for s in rank_third_placed(thirds)]
    assert ranked == ["A", "B", "C", "D", "E", "F"]


def test_conduct_score_card_values():
    assert conduct_score({"yellow": 2, "direct_red": 1}) == -6
    assert conduct_score({"yellow_and_direct_red": 1}) == -5
    assert conduct_score({}) == 0

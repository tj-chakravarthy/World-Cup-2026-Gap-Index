"""FIFA World Cup 26 group-stage tiebreakers — Article 13.

Order verified against the official *Regulations for the FIFA World Cup 26™*
(digitalhub.fifa.com -> FWC2026_regulations_EN.pdf), Article 13. The sequence
differs from 2018/2022: head-to-head is applied BEFORE overall goal difference,
and the final tiebreaker is the FIFA/Coca-Cola Men's World Ranking, not a
drawing of lots.

Ranking of teams equal on points (Art. 13 §1):
  Step 1 (head-to-head, matches between the teams concerned):
    a) H2H points  b) H2H goal difference  c) H2H goals scored
  Step 2: if Step 1 separates only some teams, re-apply a)-c) to the matches
    between the *remaining* tied teams only; whoever is still equal is ranked by
    d) overall goal difference  e) overall goals scored  f) team conduct score.
    Step 2 does not restart once a criterion separates a team.
  Step 3: g) most recent FIFA ranking  h) successively older editions.

Best eight third-placed teams (Art. 13 §2): overall points -> GD -> goals ->
conduct score -> FIFA ranking. No head-to-head (the thirds come from different
groups).

Pure stdlib by design: the logic is integer arithmetic on results, so the
tiebreaker stays trivially testable and free of the modelling stack. The
third-place *bracket allocation* table (which third goes to which R32 slot) is
2026 fixture data and lives with the Monte Carlo, not here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

# Art. 13 §1 f) — team conduct score card deductions. One deduction only per
# player/official per match; the team with the highest (least negative) score
# ranks higher.
CARD_POINTS = {
    "yellow": -1,
    "indirect_red": -3,        # second yellow in a match
    "direct_red": -4,
    "yellow_and_direct_red": -5,
}


def conduct_score(cards: dict[str, int]) -> int:
    """Sum card deductions into a conduct score. `cards` maps a CARD_POINTS key
    to a count, e.g. {"yellow": 3, "direct_red": 1}."""
    return sum(CARD_POINTS[kind] * n for kind, n in cards.items())


@dataclass(frozen=True)
class Match:
    home: str
    away: str
    home_goals: int
    away_goals: int


@dataclass(frozen=True)
class Standing:
    """A team's final standing in its group, carrying everything the
    third-place ranking needs (so it takes no extra arguments)."""
    team: str
    points: int
    gd: int
    gf: int
    conduct: int
    fifa_rank: int


@dataclass(frozen=True)
class _Rec:
    pts: int
    gd: int
    gf: int


def _records(teams: Iterable[str], matches: Iterable[Match]) -> dict[str, _Rec]:
    """Points / GD / GF for `teams`, counting only matches in which BOTH ends
    are in `teams`. Pass the whole group for overall stats, or a tied subset for
    head-to-head stats."""
    teams = set(teams)
    pts = {t: 0 for t in teams}
    gf = {t: 0 for t in teams}
    ga = {t: 0 for t in teams}
    for m in matches:
        if m.home not in teams or m.away not in teams:
            continue
        gf[m.home] += m.home_goals
        ga[m.home] += m.away_goals
        gf[m.away] += m.away_goals
        ga[m.away] += m.home_goals
        if m.home_goals > m.away_goals:
            pts[m.home] += 3
        elif m.home_goals < m.away_goals:
            pts[m.away] += 3
        else:
            pts[m.home] += 1
            pts[m.away] += 1
    return {t: _Rec(pts[t], gf[t] - ga[t], gf[t]) for t in teams}


def _partition(teams: list[str], key) -> list[list[str]]:
    """Sort `teams` by `key` descending and split into groups of equal key,
    best group first."""
    ordered = sorted(teams, key=key, reverse=True)
    groups: list[list[str]] = []
    for t in ordered:
        if groups and key(t) == key(groups[-1][0]):
            groups[-1].append(t)
        else:
            groups.append([t])
    return groups


@dataclass
class _Ctx:
    matches: list[Match]
    overall: dict[str, _Rec]
    conduct: dict[str, int]
    fifa_rank: dict[str, int]


def _order_overall(tied: list[str], ctx: _Ctx) -> list[str]:
    """Art. 13 §1 d)-f) then Step 3 g)-h). A lexicographic sort is exactly the
    'apply next criterion to whoever is still tied, never restart' rule. FIFA
    rank is a strict total order, so this always resolves."""
    def key(t: str):
        r = ctx.overall[t]
        # higher gd/gf/conduct first; lower (better) FIFA rank first
        return (r.gd, r.gf, ctx.conduct.get(t, 0), -ctx.fifa_rank[t])
    return sorted(tied, key=key, reverse=True)


def _order_tied(tied: list[str], ctx: _Ctx) -> list[str]:
    """Order teams equal on points. Step 1 = head-to-head over the tied set;
    Step 2 = one re-application of head-to-head to any still-tied subset, then
    fall through to overall criteria."""
    h2h = _records(tied, ctx.matches)
    out: list[str] = []
    for group in _partition(tied, key=lambda t: (h2h[t].pts, h2h[t].gd, h2h[t].gf)):
        if len(group) == 1:
            out.extend(group)
            continue
        # Step 2: re-apply a)-c) to matches between the remaining teams only.
        h2h2 = _records(group, ctx.matches)
        for sub in _partition(group, key=lambda t: (h2h2[t].pts, h2h2[t].gd, h2h2[t].gf)):
            if len(sub) == 1:
                out.extend(sub)
            else:
                out.extend(_order_overall(sub, ctx))  # no head-to-head restart
    return out


def group_table(
    matches: Iterable[Match],
    fifa_rank: dict[str, int],
    conduct: dict[str, int] | None = None,
) -> list[Standing]:
    """Full group ranking, 1st place first. `fifa_rank` (1 = best) must cover
    every team — it is Art. 13's guaranteed final tiebreaker. `conduct` maps
    team -> conduct score (default 0)."""
    matches = list(matches)
    teams = sorted({t for m in matches for t in (m.home, m.away)})
    missing = [t for t in teams if t not in fifa_rank]
    if missing:
        raise ValueError(f"fifa_rank missing teams (required as final tiebreaker): {missing}")
    conduct = conduct or {}
    overall = _records(teams, matches)
    ctx = _Ctx(matches, overall, conduct, fifa_rank)

    order: list[str] = []
    for group in _partition(teams, key=lambda t: overall[t].pts):
        order.extend(group if len(group) == 1 else _order_tied(group, ctx))

    return [
        Standing(t, overall[t].pts, overall[t].gd, overall[t].gf,
                 conduct.get(t, 0), fifa_rank[t])
        for t in order
    ]


def rank_group(
    matches: Iterable[Match],
    fifa_rank: dict[str, int],
    conduct: dict[str, int] | None = None,
) -> list[str]:
    """Team names in finishing order (1st..last)."""
    return [s.team for s in group_table(matches, fifa_rank, conduct)]


def rank_third_placed(thirds: Iterable[Standing]) -> list[Standing]:
    """Rank the third-placed teams (Art. 13 §2): overall points -> GD -> goals
    -> conduct -> FIFA ranking. No head-to-head; the Standings already carry
    every field, so this is a single lexicographic sort."""
    return sorted(
        thirds,
        key=lambda s: (s.points, s.gd, s.gf, s.conduct, -s.fifa_rank),
        reverse=True,
    )

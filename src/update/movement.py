"""Odds movement after a result — the 'what changed' panel (PLAN.md §6).

After a recompute, diff the new tournament-sim odds against the snapshot from just before the
new result(s) landed: which teams' title odds (p_winner) and knockout-advancement odds (p_R32)
moved most, plus the fixture(s) that caused it. run_all snapshots the old simulation.json in
memory before overwriting it and calls build_movement; the site renders movement.json in the
'what changed after the last result' panel. Pure builder. pandas (fixtures lookup) only."""

from __future__ import annotations

import pandas as pd

MIN_DELTA = 0.0005  # 0.05pp — below this is Monte-Carlo wobble, not signal


def _by_code(payload: dict) -> dict[str, dict]:
    return {t["country_code"]: t for t in payload.get("teams", [])}


def _movers(before: dict[str, dict], after: dict[str, dict], key: str, top_n: int) -> list[dict]:
    """Teams ranked by absolute change in `key`, biggest first, tiny wobble dropped."""
    rows = []
    for code, a in after.items():
        b = before.get(code)
        if b is None or key not in a or key not in b:
            continue
        d = a[key] - b[key]
        if abs(d) < MIN_DELTA:
            continue
        rows.append({"country_code": code, "before": round(b[key], 5),
                     "after": round(a[key], 5), "delta": round(d, 5)})
    rows.sort(key=lambda r: abs(r["delta"]), reverse=True)
    return rows[:top_n]


def _resolved_cards(newly_ids: set[str], fixtures: pd.DataFrame) -> list[dict]:
    """The just-resolved fixtures (cause of the movement): code pair, score, outcome."""
    fx = fixtures.set_index("fixture_id")
    cards = []
    for fid in sorted(newly_ids):
        if fid not in fx.index:
            continue
        r = fx.loc[fid]
        hs, as_ = r["home_score"], r["away_score"]
        if pd.isna(hs) or pd.isna(as_):
            continue
        hs, as_ = int(hs), int(as_)
        cards.append({"fixture_id": fid, "team1": r["home_code"], "team2": r["away_code"],
                      "score": f"{hs}-{as_}", "outcome": 0 if hs > as_ else (2 if hs < as_ else 1)})
    return cards


def build_movement(before: dict, after: dict, newly_ids, fixtures: pd.DataFrame,
                   top_n: int = 5) -> dict:
    """Diff two sim payloads into the movement artifact. `before` may be empty (first run):
    then there are no movers, only the resolved cards. Pure."""
    b, a = _by_code(before), _by_code(after)
    return {
        "generated_at": after.get("generated_at"),
        "since": before.get("generated_at"),
        "newly_resolved": _resolved_cards(set(newly_ids), fixtures),
        "title_movers": _movers(b, a, "p_winner", top_n),
        "advance_movers": _movers(b, a, "p_R32", top_n),
    }

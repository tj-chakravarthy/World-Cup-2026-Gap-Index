"""Fixtures for WC 2026 — the lock's spine (PLAN.md §1.5).

Writes the committed reference CSV:

  data/raw/fixtures_2026.csv  — all 104 fixtures: official match number, stage,
    group, kickoff (UTC), venue, both teams (FIFA code where known), and the
    score for matches already played. The schedule is fixed; results refresh on
    re-run, so the daily cron can call this for update_actuals too.

Fixture-id scheme: WC26-M{match_number:03d}, keyed on FIFA's official match
number (1..104) — stable and unique for group and knockout fixtures alike.

Source: fixturedownload.com's structured WC2026 feed (the Dec-2025 draw for the
72 group fixtures, bracket-slot placeholders like "1A"/"3ABCDF" for the 32
knockout slots whose teams aren't decided yet). Authoritative enough for the
schedule + draw spine; the group draw and any in-tournament results still want a
cross-check against FIFA/Wikipedia before they back a committed lock.

Stdlib only by design (urllib + csv), like the rest of the Stage-0 pipeline:
runs in plain CI without the modelling stack, and the output is a flat feed ->
flat CSV with nothing pandas buys here.
"""

from __future__ import annotations

import csv
import json
import sys
import urllib.request
from pathlib import Path

FEED_URL = "https://fixturedownload.com/feed/json/fifa-world-cup-2026"

REPO = Path(__file__).resolve().parents[2]
FIXTURES_CSV = REPO / "data" / "raw" / "fixtures_2026.csv"

# fixturedownload RoundNumber -> stage. Round 8 holds both the third-place match
# (lower match number) and the final, so it is split by match number below.
_STAGE_BY_ROUND = {1: "group", 2: "group", 3: "group",
                   4: "R32", 5: "R16", 6: "QF", 7: "SF"}

# Feed country name -> FIFA trigram, for the 48 teams of the 2026 draw. Knockout
# slots carry bracket-placeholder tokens ("1A", "3ABCDF", "To be announced"),
# which have no code yet and are left blank.
_FIFA_CODE = {
    "Algeria": "ALG", "Argentina": "ARG", "Australia": "AUS", "Austria": "AUT",
    "Belgium": "BEL", "Bosnia and Herzegovina": "BIH", "Brazil": "BRA",
    "Cabo Verde": "CPV", "Canada": "CAN", "Colombia": "COL", "Congo DR": "COD",
    "Croatia": "CRO", "Curaçao": "CUW", "Czechia": "CZE", "Côte d'Ivoire": "CIV",
    "Ecuador": "ECU", "Egypt": "EGY", "England": "ENG", "France": "FRA",
    "Germany": "GER", "Ghana": "GHA", "Haiti": "HAI", "IR Iran": "IRN",
    "Iraq": "IRQ", "Japan": "JPN", "Jordan": "JOR", "Korea Republic": "KOR",
    "Mexico": "MEX", "Morocco": "MAR", "Netherlands": "NED", "New Zealand": "NZL",
    "Norway": "NOR", "Panama": "PAN", "Paraguay": "PAR", "Portugal": "POR",
    "Qatar": "QAT", "Saudi Arabia": "KSA", "Scotland": "SCO", "Senegal": "SEN",
    "South Africa": "RSA", "Spain": "ESP", "Sweden": "SWE", "Switzerland": "SUI",
    "Tunisia": "TUN", "Türkiye": "TUR", "USA": "USA", "Uruguay": "URU",
    "Uzbekistan": "UZB",
}


def fetch_feed(url: str = FEED_URL) -> list[dict]:
    req = urllib.request.Request(url, headers={"User-Agent": "gapindex-fixtures"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def _stage(match_number: int, round_number: int) -> str:
    if round_number == 8:
        return "final" if match_number == 104 else "third_place"
    try:
        return _STAGE_BY_ROUND[round_number]
    except KeyError:
        raise ValueError(f"match {match_number}: unknown RoundNumber {round_number}")


def _iso(dt_utc: str) -> str:
    # feed gives "2026-06-11 19:00:00Z" -> ISO-8601 with a T separator
    return dt_utc.replace(" ", "T")


def build_fixtures(feed: list[dict]) -> list[dict]:
    rows = []
    for m in feed:
        n = m["MatchNumber"]
        stage = _stage(n, m["RoundNumber"])
        is_group = stage == "group"
        grp = (m["Group"] or "").replace("Group ", "")
        home, away = m["HomeTeam"], m["AwayTeam"]
        rows.append({
            "fixture_id": f"WC26-M{n:03d}",
            "match_number": n,
            "stage": stage,
            "group": grp,
            "matchday": m["RoundNumber"] if is_group else "",
            "kickoff_utc": _iso(m["DateUtc"]),
            "venue_key": m["Location"],
            "home_team": home,
            "away_team": away,
            # group teams are always decided; knockout teams are slot placeholders ("Winner Group
            # A") until groups finish, then real names — code them once the feed resolves them, blank
            # while still a placeholder, so live knockout results + receipts can attach.
            "home_code": _FIFA_CODE[home] if is_group else _FIFA_CODE.get(home, ""),
            "away_code": _FIFA_CODE[away] if is_group else _FIFA_CODE.get(away, ""),
            "home_score": m["HomeTeamScore"] if m["HomeTeamScore"] is not None else "",
            "away_score": m["AwayTeamScore"] if m["AwayTeamScore"] is not None else "",
            # the feed's decisive winner — names the team even on a shootout-decided draw, "Draw"
            # for a level group result, "" while undecided. Map to a code; the sim pins a knockout
            # winner off this directly (so a shootout, incl. the final, doesn't need the next round).
            "winner_code": _FIFA_CODE.get(m.get("Winner") or "", ""),
            "played": m["HomeTeamScore"] is not None,
        })
    return rows


def validate(rows: list[dict]) -> None:
    """Fail loudly before writing — the lock spine has to be right."""
    if len(rows) != 104:
        raise ValueError(f"expected 104 fixtures, got {len(rows)}")
    ids = [r["fixture_id"] for r in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate fixture_id")
    n_venues = len({r["venue_key"] for r in rows})
    if n_venues != 16:
        raise ValueError(f"expected 16 host venues, got {n_venues}")
    # every decided (group) team must map to a FIFA code
    unmapped = sorted({r["home_team"] for r in rows if r["stage"] == "group"
                       and not r["home_code"]}
                      | {r["away_team"] for r in rows if r["stage"] == "group"
                         and not r["away_code"]})
    if unmapped:
        raise ValueError(f"group-stage teams without a FIFA code: {unmapped}")
    codes = {r["home_code"] for r in rows if r["home_code"]} | \
            {r["away_code"] for r in rows if r["away_code"]}
    if len(codes) != 48:
        raise ValueError(f"expected 48 distinct group-stage teams, got {len(codes)}")
    # a named winner must be one of the two participants and the match must be played — the sim
    # pins knockout results off this, so a stray winner_code can't silently advance a non-participant
    for r in rows:
        wc = r["winner_code"]
        if wc and (wc not in (r["home_code"], r["away_code"]) or not r["played"]):
            raise ValueError(f"{r['fixture_id']}: winner_code {wc!r} not a played participant")


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(fieldnames)
        for r in rows:
            w.writerow([r[k] for k in fieldnames])


def write_fixtures(rows: list[dict], path: Path = FIXTURES_CSV) -> None:
    fields = ["fixture_id", "match_number", "stage", "group", "matchday",
              "kickoff_utc", "venue_key", "home_team", "away_team",
              "home_code", "away_code", "home_score", "away_score", "winner_code", "played"]
    _write_csv(path, fields, rows)


def main() -> None:
    feed = fetch_feed()
    rows = build_fixtures(feed)
    validate(rows)
    write_fixtures(rows)
    played = sum(r["played"] for r in rows)
    print(f"wrote {len(rows)} fixtures ({played} played) -> {FIXTURES_CSV}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"fetch_fixtures_venues failed: {e}", file=sys.stderr)
        sys.exit(1)

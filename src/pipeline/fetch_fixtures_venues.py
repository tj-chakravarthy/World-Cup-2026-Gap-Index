"""Fixtures + venues for WC 2026 — the lock's spine (PLAN.md §1.5).

Writes two committed reference CSVs:

  data/raw/fixtures_2026.csv  — all 104 fixtures: official match number, stage,
    group, kickoff (UTC), venue, both teams (FIFA code where known), and the
    score for matches already played. The schedule is fixed; results refresh on
    re-run, so the daily cron can call this for update_actuals too.
  data/raw/venues_2026.csv    — the 16 host venues with lat/lon, altitude, IANA
    timezone, a roof flag, and approximate June/July climate normals.

Fixture-id scheme: WC26-M{match_number:03d}, keyed on FIFA's official match
number (1..104) — stable and unique for group and knockout fixtures alike.

Source: fixturedownload.com's structured WC2026 feed (the Dec-2025 draw for the
72 group fixtures, bracket-slot placeholders like "1A"/"3ABCDF" for the 32
knockout slots whose teams aren't decided yet). Authoritative enough for the
schedule + draw spine; the group draw and any in-tournament results still want a
cross-check against FIFA/Wikipedia before they back a committed lock.

Venue lat/lon are stadium-approximate (well within the inter-city distances the
haversine travel feature cares about). Climate normals and the roof flag are
hand-entered approximations — heat_mismatch is exploratory per PLAN.md §1.5.

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
VENUES_CSV = REPO / "data" / "raw" / "venues_2026.csv"

# fixturedownload RoundNumber -> stage. Round 8 holds both the third-place match
# (lower match number) and the final, so it is split by match number below.
_STAGE_BY_ROUND = {1: "group", 2: "group", 3: "group",
                   4: "R32", 5: "R16", 6: "QF", 7: "SF"}

# 16 host venues, keyed by the feed's generic Location string (FIFA uses these
# unbranded names during the tournament). lat/lon stadium-approximate; altitude
# in metres; tz is the IANA zone (for local-kickoff + timezone-shift features);
# roofed = fixed/retractable roof that neutralises heat; climate_high_c /
# climate_rh_pct are rough June-July daily-high normals (exploratory).
_VENUES = [
    # venue_key,                       stadium,                  city,             ctry, lat,     lon,       alt,  tz,                      roof, high, rh
    ("Mexico City Stadium",            "Estadio Azteca",         "Mexico City",    "MEX", 19.303, -99.150,  2240, "America/Mexico_City",   0, 23, 55),
    ("Guadalajara Stadium",            "Estadio Akron",          "Guadalajara",    "MEX", 20.682, -103.462, 1551, "America/Mexico_City",   0, 27, 55),
    ("Monterrey Stadium",              "Estadio BBVA",           "Monterrey",      "MEX", 25.669, -100.244,  500, "America/Monterrey",     0, 34, 50),
    ("Toronto Stadium",                "BMO Field",              "Toronto",        "CAN", 43.633, -79.418,   76, "America/Toronto",       0, 26, 60),
    ("BC Place Vancouver",             "BC Place",               "Vancouver",      "CAN", 49.277, -123.112,   0, "America/Vancouver",     1, 22, 65),
    ("Atlanta Stadium",                "Mercedes-Benz Stadium",  "Atlanta",        "USA", 33.755, -84.401,   320, "America/New_York",      1, 31, 65),
    ("Boston Stadium",                 "Gillette Stadium",       "Foxborough",     "USA", 42.091, -71.264,    90, "America/New_York",      0, 27, 65),
    ("Dallas Stadium",                 "AT&T Stadium",           "Arlington",      "USA", 32.748, -97.093,   160, "America/Chicago",       1, 35, 55),
    ("Houston Stadium",                "NRG Stadium",            "Houston",        "USA", 29.685, -95.411,    15, "America/Chicago",       1, 34, 70),
    ("Kansas City Stadium",            "Arrowhead Stadium",      "Kansas City",    "USA", 39.049, -94.484,   270, "America/Chicago",       0, 31, 60),
    ("Los Angeles Stadium",            "SoFi Stadium",           "Inglewood",      "USA", 33.953, -118.339,   30, "America/Los_Angeles",   1, 27, 65),
    ("Miami Stadium",                  "Hard Rock Stadium",      "Miami Gardens",  "USA", 25.958, -80.239,     3, "America/New_York",      0, 32, 70),
    ("New York/New Jersey Stadium",    "MetLife Stadium",        "East Rutherford","USA", 40.814, -74.074,     5, "America/New_York",      0, 29, 60),
    ("Philadelphia Stadium",           "Lincoln Financial Field","Philadelphia",   "USA", 39.901, -75.168,    12, "America/New_York",      0, 30, 60),
    ("San Francisco Bay Area Stadium", "Levi's Stadium",         "Santa Clara",    "USA", 37.403, -121.970,    4, "America/Los_Angeles",   0, 27, 70),
    ("Seattle Stadium",                "Lumen Field",            "Seattle",        "USA", 47.595, -122.332,    5, "America/Los_Angeles",   0, 23, 65),
]
_VENUE_KEYS = {v[0] for v in _VENUES}

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
            # codes only for the decided (group-stage) teams; knockout slots blank
            "home_code": _FIFA_CODE[home] if is_group else "",
            "away_code": _FIFA_CODE[away] if is_group else "",
            "home_score": m["HomeTeamScore"] if m["HomeTeamScore"] is not None else "",
            "away_score": m["AwayTeamScore"] if m["AwayTeamScore"] is not None else "",
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
    bad_venue = sorted({r["venue_key"] for r in rows} - _VENUE_KEYS)
    if bad_venue:
        raise ValueError(f"fixtures reference unknown venues: {bad_venue}")
    used_venues = {r["venue_key"] for r in rows}
    if used_venues != _VENUE_KEYS:
        raise ValueError(f"venue table/fixtures mismatch: {_VENUE_KEYS ^ used_venues}")
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


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict | tuple]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(fieldnames)
        for r in rows:
            w.writerow([r[k] for k in fieldnames] if isinstance(r, dict) else r)


def write_venues(path: Path = VENUES_CSV) -> None:
    fields = ["venue_key", "stadium", "city", "country", "lat", "lon",
              "altitude_m", "tz", "roofed", "climate_high_c", "climate_rh_pct"]
    _write_csv(path, fields, _VENUES)


def write_fixtures(rows: list[dict], path: Path = FIXTURES_CSV) -> None:
    fields = ["fixture_id", "match_number", "stage", "group", "matchday",
              "kickoff_utc", "venue_key", "home_team", "away_team",
              "home_code", "away_code", "home_score", "away_score", "played"]
    _write_csv(path, fields, rows)


def main() -> None:
    feed = fetch_feed()
    rows = build_fixtures(feed)
    validate(rows)
    write_venues()
    write_fixtures(rows)
    played = sum(r["played"] for r in rows)
    print(f"wrote {len(rows)} fixtures ({played} played) -> {FIXTURES_CSV}")
    print(f"wrote {len(_VENUES)} venues -> {VENUES_CSV}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"fetch_fixtures_venues failed: {e}", file=sys.stderr)
        sys.exit(1)

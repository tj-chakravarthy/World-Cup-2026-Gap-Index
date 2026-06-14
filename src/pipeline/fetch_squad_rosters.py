"""Squad rosters for WC 2018/2022/2026 — the player foundation (PLAN.md §1.1).

Parses the Wikipedia "{year} FIFA World Cup squads" pages into one row per player:
country (FIFA trigram + page name), name + a folded join name, position, date of
birth, age at the tournament, caps, goals, and club. club_country and data_tier
are left blank — they need the league/club-strength map that rides with the FBref
layer, filled later, not fabricated here.

2026 is the live foundation; 2018/2022 are backtest-index inputs (§4.5). Each page
lays a squad out as a wikitable (No./Pos./Player/DOB/Caps/Goals/Club) under a
heading with the team name; team names match the martj42 spelling set, so they
resolve to FIFA codes through the crosswalk (team_codes.py) plus a small supplement
for nations that played a past WC but not 2026. The build VALIDATES: the right
squad count for the edition, every team coded, plausible squad sizes — a silent
miss here poisons every downstream player feature.

bs4 + stdlib by design (no pandas). The default run fetches the historical editions
(2018, 2022); squads_2026.csv already exists — regenerate it with `--year 2026`.
Run: python -m src.pipeline.fetch_squad_rosters
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import unicodedata
import urllib.request
from datetime import date
from pathlib import Path

from bs4 import BeautifulSoup

from src.pipeline.team_codes import TeamCodes

UA = "gapindex-research/0.1 (World Cup club-to-national gap analysis)"
REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"

# year -> (wikipedia page, tournament start date, expected squad count)
EDITIONS = {
    2018: ("2018_FIFA_World_Cup_squads", date(2018, 6, 14), 32),
    2022: ("2022_FIFA_World_Cup_squads", date(2022, 11, 20), 32),
    2026: ("2026_FIFA_World_Cup_squads", date(2026, 6, 11), 48),
}

# FIFA trigrams for nations in a past WC squad but absent from the 2026 crosswalk.
_EXTRA_CODES = {
    "Costa Rica": "CRC", "Denmark": "DEN", "Iceland": "ISL", "Nigeria": "NGA",
    "Peru": "PER", "Poland": "POL", "Russia": "RUS", "Serbia": "SRB",
    "Cameroon": "CMR", "Wales": "WAL",
}

FIELDS = ["year", "country_code", "country", "player_name", "player_name_norm",
          "position", "dob", "age_at_tournament", "caps", "goals", "club",
          "club_country", "data_tier"]

_POS = re.compile(r"\b(GK|DF|MF|FW)\b")
_FOOTNOTE = re.compile(r"\[[^\]]*\]")
_CAPTAIN = re.compile(r"\(\s*(?:c|vc|captain|vice[-\s]?captain)\s*\)", re.I)


def _clean(text: str) -> str:
    text = _FOOTNOTE.sub("", text)
    text = _CAPTAIN.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _norm(name: str) -> str:
    """ASCII-folded, lower-cased join key (stands in for unidecode)."""
    folded = unicodedata.normalize("NFKD", name)
    folded = folded.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", folded).strip().lower()


def _int(text: str) -> int:
    digits = re.sub(r"[^0-9]", "", text)
    return int(digits) if digits else 0


def _age(dob: str, on: date = date(2026, 6, 11)) -> int | str:
    try:
        d = date.fromisoformat(dob)
    except ValueError:
        return ""
    return on.year - d.year - ((on.month, on.day) < (d.month, d.day))


def _is_squad_table(table) -> bool:
    head = " ".join(th.get_text(" ", strip=True) for th in table.select("tr:first-child th"))
    return "Player" in head and "Club" in head


def _team_of(table) -> str | None:
    h = table.find_previous(["h3", "h2"])
    return _clean(h.get_text(" ", strip=True).replace("[edit]", "")) if h else None


def parse_squads(html: str) -> list[dict]:
    """One row per player across all squad tables (age added per edition later)."""
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for table in soup.select("table.wikitable"):
        if not _is_squad_table(table):
            continue
        team = _team_of(table)
        for tr in table.select("tr")[1:]:
            cells = tr.find_all(["th", "td"])
            if len(cells) < 7:
                continue
            _no, pos, player, dob_cell, caps, goals, club = cells[:7]
            name = _clean(player.get_text(" ", strip=True))
            if not name:
                continue
            bday = dob_cell.select_one(".bday")
            pos_m = _POS.search(pos.get_text(" ", strip=True))
            rows.append({
                "team": team,
                "player_name": name,
                "player_name_norm": _norm(name),
                "position": pos_m.group(1) if pos_m else "",
                "dob": bday.text.strip() if bday else "",
                "caps": _int(caps.get_text()),
                "goals": _int(goals.get_text()),
                "club": _clean(club.get_text(" ", strip=True)),
            })
    return rows


def _code(team: str, tc: TeamCodes) -> str:
    return tc.martj42_to_fifa.get(team) or _EXTRA_CODES.get(team, "")


def build_rows(players: list[dict], tc: TeamCodes, *, year: int,
               tournament_start: date, expected_teams: int) -> list[dict]:
    """Attach FIFA codes + age, validate coverage."""
    out, unmapped = [], set()
    for p in players:
        code = _code(p["team"], tc)
        if not code:
            unmapped.add(p["team"])
        out.append({
            "year": year, "country_code": code, "country": p["team"],
            "player_name": p["player_name"], "player_name_norm": p["player_name_norm"],
            "position": p["position"], "dob": p["dob"],
            "age_at_tournament": _age(p["dob"], tournament_start),
            "caps": p["caps"], "goals": p["goals"], "club": p["club"],
            "club_country": "", "data_tier": "",
        })
    if unmapped:
        raise ValueError(f"squad teams not coded (add to crosswalk/_EXTRA_CODES): {sorted(unmapped)}")
    teams = {r["country"] for r in out}
    if len(teams) != expected_teams:
        raise ValueError(f"{year}: expected {expected_teams} squads, parsed {len(teams)}")
    thin = {t for t in teams if sum(r["country"] == t for r in out) < 11}
    if thin:
        raise ValueError(f"implausibly small squads (<11): {sorted(thin)}")
    return out


def fetch_year(year: int, tc: TeamCodes) -> Path:
    page, start, n = EDITIONS[year]
    req = urllib.request.Request(f"https://en.wikipedia.org/wiki/{page}", headers={"User-Agent": UA})
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")
    rows = build_rows(parse_squads(html), tc, year=year, tournament_start=start, expected_teams=n)
    out = RAW / f"squads_{year}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"{year}: wrote {len(rows)} players across "
          f"{len({r['country_code'] for r in rows})} squads -> {out.name}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, choices=list(EDITIONS),
                    help="one edition (default: the historical 2018 + 2022)")
    args = ap.parse_args()
    years = [args.year] if args.year else [2018, 2022]
    tc = TeamCodes.load()
    for y in years:
        fetch_year(y, tc)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"squad fetch failed: {e}", file=sys.stderr)
        sys.exit(1)

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

The §4.5 backtest also needs three continental editions (Euro 2020, Euro 2024,
Copa América 2024). Same page shape, same parser; they go through fetch_backtest
into squads_{slug}.csv with softer validation (thin/uncoded nations logged and
skipped, not fatal — a partial file still feeds the index).

bs4 + stdlib by design (no pandas). The default run fetches the historical editions
(2018, 2022); squads_2026.csv already exists — regenerate it with `--year 2026`.
Run: python -m src.pipeline.fetch_squad_rosters
     python -m src.pipeline.fetch_squad_rosters --backtest euro2024
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import unicodedata
import urllib.parse
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

# Continental tournaments the backtest needs (§4.5). Same page shape as the WC
# editions (one wikitable per nation), so the WC parser handles them as-is; they
# write to squads_{slug}.csv and carry the tournament YEAR in the year column.
# slug -> (wikipedia page, year, tournament start date, expected squad count)
BACKTEST_EDITIONS = {
    "euro2020": ("UEFA_Euro_2020_squads", 2020, date(2021, 6, 11), 24),
    "euro2024": ("UEFA_Euro_2024_squads", 2024, date(2024, 6, 14), 24),
    "copa2024": ("2024_Copa_América_squads", 2024, date(2024, 6, 20), 16),
}

# FIFA trigrams for nations in a past WC/continental squad but absent from the
# 2026 crosswalk. The euro/copa block covers teams that never made WC 2018/2022.
_EXTRA_CODES = {
    "Costa Rica": "CRC", "Denmark": "DEN", "Iceland": "ISL", "Nigeria": "NGA",
    "Peru": "PER", "Poland": "POL", "Russia": "RUS", "Serbia": "SRB",
    "Cameroon": "CMR", "Wales": "WAL",
    "Albania": "ALB", "Bolivia": "BOL", "Chile": "CHI", "Finland": "FIN",
    "Georgia": "GEO", "Hungary": "HUN", "Italy": "ITA", "Jamaica": "JAM",
    "North Macedonia": "MKD", "Romania": "ROU", "Slovakia": "SVK",
    "Slovenia": "SVN", "Ukraine": "UKR", "Venezuela": "VEN",
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


def _fetch_html(page: str) -> str:
    # quote the path: continental page titles carry non-ASCII (Copa "América").
    url = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(page)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8")


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
    html = _fetch_html(page)
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


def fetch_backtest(slug: str, tc: TeamCodes) -> Path:
    """Euro/Copa edition -> squads_{slug}.csv. Robust by design: a nation that
    parses thin or stays uncoded is logged to stderr and skipped, not fatal — a
    partial roster file still feeds the index. Same schema as the WC editions."""
    page, year, start, n_teams = BACKTEST_EDITIONS[slug]
    html = _fetch_html(page)
    players = parse_squads(html)

    # squad sizes per team, to drop implausibly thin (mis-parsed) squads.
    sizes = {}
    for p in players:
        sizes[p["team"]] = sizes.get(p["team"], 0) + 1

    rows, dropped = [], set()
    for p in players:
        team = p["team"]
        code = _code(team, tc)
        if not code:
            dropped.add(f"{team} (no FIFA code)")
            continue
        if sizes[team] < 11:
            dropped.add(f"{team} (thin: {sizes[team]} rows)")
            continue
        rows.append({
            "year": year, "country_code": code, "country": team,
            "player_name": p["player_name"], "player_name_norm": p["player_name_norm"],
            "position": p["position"], "dob": p["dob"],
            "age_at_tournament": _age(p["dob"], start),
            "caps": p["caps"], "goals": p["goals"], "club": p["club"],
            "club_country": "", "data_tier": "",
        })

    teams_ok = {r["country"] for r in rows}
    if dropped:
        print(f"{slug}: dropped {sorted(dropped)}", file=sys.stderr)
    if len(teams_ok) != n_teams:
        print(f"{slug}: WARN parsed {len(teams_ok)}/{n_teams} squads", file=sys.stderr)

    out = RAW / f"squads_{slug}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"{slug}: wrote {len(rows)} players across {len(teams_ok)} squads -> {out.name}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, choices=list(EDITIONS),
                    help="one WC edition (default: the historical 2018 + 2022)")
    ap.add_argument("--backtest", choices=list(BACKTEST_EDITIONS),
                    help="one continental edition (euro2020/euro2024/copa2024)")
    args = ap.parse_args()
    tc = TeamCodes.load()
    if args.backtest:
        fetch_backtest(args.backtest, tc)
        return
    years = [args.year] if args.year else [2018, 2022]
    for y in years:
        fetch_year(y, tc)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"squad fetch failed: {e}", file=sys.stderr)
        sys.exit(1)

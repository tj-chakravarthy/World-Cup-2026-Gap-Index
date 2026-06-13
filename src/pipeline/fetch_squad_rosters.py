"""Squad rosters for WC 2026 — the player foundation (PLAN.md §1.1).

Parses the Wikipedia "2026 FIFA World Cup squads" page into one row per player:
country (FIFA trigram + page name), name + a folded join name, position, date of
birth, age at the tournament, caps, goals, and club. club_country and data_tier
are left blank — they need the league/club-strength map that rides with the
(deferred) FBref layer, so they're filled later, not fabricated here.

The page lays each squad out as a wikitable (No./Pos./Player/DOB/Caps/Goals/Club)
under an h3 with the team name; team names match the martj42 spelling set, so
they resolve to FIFA codes through the existing crosswalk (team_codes.py). The
build VALIDATES: 48 teams, every team mapped, a plausible squad size — a silent
miss here poisons every downstream player feature.

bs4 + stdlib by design (no pandas): the page is one flat table per team, and
unicodedata folding gives an ASCII join name without the unidecode dependency.
Run: python -m src.pipeline.fetch_squad_rosters
"""

from __future__ import annotations

import csv
import re
import sys
import unicodedata
import urllib.request
from datetime import date
from pathlib import Path

from bs4 import BeautifulSoup

from src.pipeline.team_codes import TeamCodes

URL = "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_squads"
UA = "gapindex-research/0.1 (World Cup club-to-national gap analysis)"
TOURNAMENT_START = date(2026, 6, 11)

REPO = Path(__file__).resolve().parents[2]
SQUADS_CSV = REPO / "data" / "raw" / "squads_2026.csv"

FIELDS = ["year", "country_code", "country", "player_name", "player_name_norm",
          "position", "dob", "age_at_tournament", "caps", "goals", "club",
          "club_country", "data_tier"]

_POS = re.compile(r"\b(GK|DF|MF|FW)\b")
_FOOTNOTE = re.compile(r"\[[^\]]*\]")
_CAPTAIN = re.compile(r"\((?:c|vc)\)", re.I)


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


def _age(dob: str) -> int | str:
    try:
        d = date.fromisoformat(dob)
    except ValueError:
        return ""
    return TOURNAMENT_START.year - d.year - (
        (TOURNAMENT_START.month, TOURNAMENT_START.day) < (d.month, d.day))


def _is_squad_table(table) -> bool:
    head = " ".join(th.get_text(" ", strip=True) for th in table.select("tr:first-child th"))
    return "Player" in head and "Club" in head


def _team_of(table) -> str | None:
    h = table.find_previous(["h3", "h2"])
    return _clean(h.get_text(" ", strip=True).replace("[edit]", "")) if h else None


def parse_squads(html: str) -> list[dict]:
    """One row per player across all squad tables."""
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
            no, pos, player, dob_cell, caps, goals, club = cells[:7]
            name = _clean(player.get_text(" ", strip=True))
            if not name:
                continue
            bday = dob_cell.select_one(".bday")
            dob = bday.text.strip() if bday else ""
            pos_m = _POS.search(pos.get_text(" ", strip=True))
            rows.append({
                "team": team,
                "player_name": name,
                "player_name_norm": _norm(name),
                "position": pos_m.group(1) if pos_m else "",
                "dob": dob,
                "age_at_tournament": _age(dob),
                "caps": _int(caps.get_text()),
                "goals": _int(goals.get_text()),
                "club": _clean(club.get_text(" ", strip=True)),
            })
    return rows


def build_rows(players: list[dict], tc: TeamCodes) -> list[dict]:
    """Attach FIFA codes and validate coverage. team_codes keys on the martj42
    spelling, which matches the squad page names for all 48 finalists."""
    out, unmapped = [], set()
    for p in players:
        code = tc.martj42_to_fifa.get(p["team"])
        if code is None:
            unmapped.add(p["team"])
            continue
        out.append({
            "year": 2026, "country_code": code, "country": p["team"],
            "player_name": p["player_name"], "player_name_norm": p["player_name_norm"],
            "position": p["position"], "dob": p["dob"],
            "age_at_tournament": p["age_at_tournament"], "caps": p["caps"],
            "goals": p["goals"], "club": p["club"], "club_country": "", "data_tier": "",
        })
    if unmapped:
        raise ValueError(f"squad teams not in crosswalk: {sorted(unmapped)}")

    teams = {r["country_code"] for r in out}
    if len(teams) != 48:
        raise ValueError(f"expected 48 squads, parsed {len(teams)}")
    thin = {c for c in teams if sum(r["country_code"] == c for r in out) < 11}
    if thin:
        raise ValueError(f"implausibly small squads (<11): {sorted(thin)}")
    return out


def main() -> None:
    req = urllib.request.Request(URL, headers={"User-Agent": UA})
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")
    rows = build_rows(parse_squads(html), TeamCodes.load())

    SQUADS_CSV.parent.mkdir(parents=True, exist_ok=True)
    with SQUADS_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} players across "
          f"{len({r['country_code'] for r in rows})} squads -> {SQUADS_CSV.relative_to(REPO)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"squad fetch failed: {e}", file=sys.stderr)
        sys.exit(1)

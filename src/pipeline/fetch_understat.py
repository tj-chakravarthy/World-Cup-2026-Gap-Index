"""Understat club-season player xG/xA (advanced-club feed, PLAN.md §1.2).

FBref stopped serving Opta advanced stats to scrapers (see docs/deviations.md), so
club xG/npxG/xA/buildup come from Understat instead. Understat moved its data off
the league HTML into an XHR endpoint, `getLeagueData/{league}/{season}`, which
returns gzip JSON {teams, players, dates}. Keyless, no Cloudflare, no browser.
Big-5 leagues; season is the start year (2023 = 2023/24), matched to the FBref
seasons so the two feeds join per player-season. One CSV per (league, season)
under data/raw/ (gitignored). Stdlib only.

Run: python3 -m src.pipeline.fetch_understat   (or --league/--season to narrow)
"""

from __future__ import annotations

import argparse
import csv
import gzip
import html
import json
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"
ENDPOINT = "https://understat.com/getLeagueData/{league}/{season}"

LEAGUES = ["EPL", "La_liga", "Bundesliga", "Serie_A", "Ligue_1"]
SEASONS = ["2017", "2020", "2021", "2023", "2025"]  # start year; matches FBref seasons
FIELDS = ["id", "player_name", "team_title", "position", "games", "time", "goals",
          "npg", "xG", "npxG", "assists", "xA", "shots", "key_passes",
          "xGChain", "xGBuildup", "yellow_cards", "red_cards"]
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
           "X-Requested-With": "XMLHttpRequest"}


def parse_league_data(raw: bytes, gzipped: bool) -> list[dict]:
    """gzip-decode (if needed) and return the players list, HTML-unescaping string
    fields (Understat encodes names as entities, e.g. O&#039;Shea). Pure, testable."""
    if gzipped:
        raw = gzip.decompress(raw)
    players = json.loads(raw.decode("utf-8"))["players"]
    for p in players:
        for k, v in p.items():
            if isinstance(v, str):
                p[k] = html.unescape(v)
    return players


def fetch_players(league: str, season: str) -> list[dict]:
    req = urllib.request.Request(
        ENDPOINT.format(league=league, season=season),
        headers={**HEADERS, "Referer": f"https://understat.com/league/{league}/{season}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return parse_league_data(r.read(), r.headers.get("Content-Encoding") == "gzip")


def fetch_one(league: str, season: str, refresh: bool = False) -> Path:
    out = RAW / f"understat_{league}_{season}.csv"
    if out.exists() and not refresh:
        return out
    players = fetch_players(league, season)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["league", "season"] + FIELDS, extrasaction="ignore")
        w.writeheader()
        for p in players:
            w.writerow({"league": league, "season": season, **p})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", choices=LEAGUES)
    ap.add_argument("--season", choices=SEASONS)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    leagues = [args.league] if args.league else LEAGUES
    seasons = [args.season] if args.season else SEASONS
    done = fail = 0
    for lg in leagues:
        for sn in seasons:
            try:
                out = fetch_one(lg, sn, args.refresh)
                n = sum(1 for _ in open(out)) - 1
                print(f"  {lg} {sn}: {n} players -> {out.name}")
                done += 1
            except Exception as e:
                print(f"  {lg} {sn}: FAILED {e}", file=sys.stderr)
                fail += 1
            time.sleep(1.5)
    print(f"done: {done} ok, {fail} failed")
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()

"""FBref club-season player stats — Tier-1 (PLAN.md §1.2). Headless Chromium.

FBref sits behind a Cloudflare JS challenge that no plain HTTP client clears
(curl/requests/soccerdata all 403). A real browser executes the challenge, so we
drive headless Chromium via Selenium (all from apt: chromium, chromium-driver,
python3-selenium — no pip). Confirmed clearing CF locally on the dev box; falls
back to running on a residential box (bedford) only if an IP gets flagged.

One CSV per (league, season, stat_type) under data/raw/ — large, regenerable, so
gitignored. The scrape is the slow/fragile step: it caches on disk (skips files
already pulled), waits out the challenge, and is polite between requests. FBref
hides most player tables inside HTML comments and uses multi-level over-headers,
so we strip the comments and parse by each cell's data-stat key — pandas.read_html
silently drops the grouped stat columns (Total/Short/… → NaN) on these tables.

NOTE: FBref serves real data only on the `standard` and `shooting` tables (basic
box-score). All Opta advanced stats — xG/npxG/progression plus the whole
passing/defense/possession/misc tables — are structurally withheld from automated
extraction (not rate-limiting; tested headed+xvfb on a second IP — see
docs/deviations.md). So pull `--stats standard,shooting` only; club xG comes from
Understat (fetch_understat.py). On a box where headless can't clear Cloudflare
(e.g. bedford), run headed under xvfb: `xvfb-run -a python ... --headed`.

Run a pilot:   python3 -m src.pipeline.fetch_club_stats --league ENG --season 2023-2024 --stats standard
Run the lot:   python3 -m src.pipeline.fetch_club_stats --stats standard,shooting
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"
CHROMIUM = "/usr/bin/chromium"
CHROMEDRIVER = "/usr/bin/chromedriver"

# FBref comp-id + URL slug. Tier-1 = senior men's first-tier European leagues
# (PLAN §1.2). Ids verified against FBref's competitions index. These all run an
# Aug–May calendar, so they share the {YYYY}-{YYYY} season format below. The
# calendar-year / non-European leagues (MLS, Brazil, Argentina, J1, K-League,
# Saudi, Scandinavia, …) use single-year season strings and need per-league
# season handling — tracked as a follow-up, see docs/deviations.md.
LEAGUES = {
    "ENG": (9, "Premier-League"),
    "ESP": (12, "La-Liga"),
    "ITA": (11, "Serie-A"),
    "GER": (20, "Bundesliga"),
    "FRA": (13, "Ligue-1"),
    "NED": (23, "Eredivisie"),
    "POR": (32, "Primeira-Liga"),
    "BEL": (37, "Belgian-Pro-League"),
    "ENG2": (10, "Championship"),
    "TUR": (26, "Super-Lig"),
    "SCO": (40, "Scottish-Premiership"),
    "SUI": (57, "Swiss-Super-League"),
    "AUT": (56, "Austrian-Bundesliga"),
    "GRE": (27, "Super-League-Greece"),
    "DEN": (50, "Danish-Superliga"),
    "CRO": (63, "Hrvatska-NL"),
    "POL": (36, "Ekstraklasa"),
    "CZE": (66, "Czech-First-League"),
}
# pre-tournament club seasons for the backtest/CV set + the live season (PLAN §1.2).
SEASONS = ["2017-2018", "2020-2021", "2021-2022", "2023-2024", "2025-2026"]
# stat_type -> (URL path segment, player table id)
STATS = {
    "standard": ("stats", "stats_standard"),
    "shooting": ("shooting", "stats_shooting"),
    "passing": ("passing", "stats_passing"),
    "defense": ("defense", "stats_defense"),
    "possession": ("possession", "stats_possession"),
    "misc": ("misc", "stats_misc"),
}
DELAY_S = 4.0  # polite gap between page loads


def make_driver(headless: bool = True) -> webdriver.Chrome:
    opts = Options()
    opts.binary_location = CHROMIUM
    args = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
            "--window-size=1920,1080", "--disable-blink-features=AutomationControlled",
            "--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"]
    if headless:
        args.insert(0, "--headless=new")  # else headed (under xvfb) where headless can't clear CF
    for a in args:
        opts.add_argument(a)
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    d = webdriver.Chrome(service=Service(executable_path=CHROMEDRIVER), options=opts)
    d.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument",
                      {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"})
    return d


def _load(driver, url: str, table_id: str, timeout: float = 45.0) -> str:
    """Navigate, wait out the CF challenge, return the target table's HTML
    (from the live DOM, or comment-stripped source if FBref hid it)."""
    driver.get(url)
    deadline = time.time() + timeout
    while time.time() < deadline:
        src = driver.page_source or ""
        if "Just a moment" not in (driver.title or "") and f'id="{table_id}"' in src:
            soup = BeautifulSoup(src.replace("<!--", "").replace("-->", ""), "lxml")
            t = soup.find("table", id=table_id)
            if t is not None:
                return str(t)
        time.sleep(2)
    raise RuntimeError(f"blocked/timeout loading {url} (title={driver.title!r})")


def _parse_players(table_html: str) -> pd.DataFrame:
    """Parse the player table by FBref's per-cell data-stat keys (stable ids like
    'passes_completed', 'xg'), skipping the repeated mid-table header rows.
    data-stat parsing sidesteps the multi-level over-headers that make
    pandas.read_html drop the grouped stat columns to NaN."""
    table = BeautifulSoup(table_html, "lxml").find("table")
    rows = []
    for tr in table.select("tbody tr"):
        if "thead" in (tr.get("class") or []):
            continue
        row = {c.get("data-stat"): c.get_text(strip=True)
               for c in tr.find_all(["th", "td"]) if c.get("data-stat")}
        if row.get("player"):
            rows.append(row)
    return pd.DataFrame(rows).drop(columns=["ranker", "matches"], errors="ignore")


def fetch_one(driver, league: str, season: str, stat: str, refresh: bool = False) -> Path:
    comp_id, slug = LEAGUES[league]
    path, table_id = STATS[stat]
    out = RAW / f"fbref_{league}_{season}_{stat}.csv"
    if out.exists() and not refresh:
        return out
    url = f"https://fbref.com/en/comps/{comp_id}/{season}/{path}/{season}-{slug}-Stats"
    df = _parse_players(_load(driver, url, table_id))
    df.insert(0, "stat_type", stat)
    df.insert(0, "season", season)
    df.insert(0, "league", league)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", choices=list(LEAGUES), help="limit to one league")
    ap.add_argument("--season", choices=SEASONS, help="limit to one season")
    ap.add_argument("--stats", help="comma-separated stat types (default all); "
                    "use 'standard,shooting' — the only tables FBref serves real data for")
    ap.add_argument("--headed", action="store_true",
                    help="run headed under xvfb (needed where headless can't clear Cloudflare)")
    ap.add_argument("--refresh", action="store_true", help="re-pull cached files")
    args = ap.parse_args()

    leagues = [args.league] if args.league else list(LEAGUES)
    seasons = [args.season] if args.season else SEASONS
    if args.stats:
        stat_types = args.stats.split(",")
        bad = [s for s in stat_types if s not in STATS]
        if bad:
            ap.error(f"unknown stat types {bad}; choose from {list(STATS)}")
    else:
        stat_types = list(STATS)
    jobs = [(lg, sn, st) for lg in leagues for sn in seasons for st in stat_types]

    driver = make_driver(headless=not args.headed)
    done = fail = 0
    try:
        for i, (lg, sn, st) in enumerate(jobs):
            try:
                out = fetch_one(driver, lg, sn, st, refresh=args.refresh)
                n = sum(1 for _ in open(out)) - 1
                print(f"  [{i+1}/{len(jobs)}] {lg} {sn} {st}: {n} rows -> {out.name}")
                done += 1
            except Exception as e:
                print(f"  [{i+1}/{len(jobs)}] {lg} {sn} {st}: FAILED {e}", file=sys.stderr)
                fail += 1
            time.sleep(DELAY_S)
    finally:
        driver.quit()
    print(f"done: {done} pulled, {fail} failed")
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()

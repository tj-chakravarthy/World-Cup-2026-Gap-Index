"""Transfermarkt national-team squad market values (PLAN.md §1.2 Tier-3 / §2.3).

Market value is the one input with no keyless source — it is a Transfermarkt
product. Same Cloudflare situation as FBref, same fix: headed Chromium via Selenium
(apt chromium/chromium-driver/python3-selenium, no pip). Unlike FBref, Transfermarkt
serves the full table to a real browser — the squad page `kader/.../plus/1` carries
per-player market value in its `table.items`.

Two steps, both cached on disk:
  1. discover — quick-search each nation, pick the SENIOR national team by fuzzy
     match of the result's anchor text to the country name (youth/Olympic variants
     carry suffixes and lose the match). Writes transfermarkt_team_ids.csv. Nations
     that don't resolve are surfaced for manual override, never guessed.
  2. scrape — per (nation, season) load the squad page, VERIFY the page title names
     the team, parse the items table → one CSV per (code, season) under data/raw/.

Each squad file maps to its pre-tournament Transfermarkt season (PLAN §1.2; saison_id =
the season's start year) — see SQUAD_SOURCES. Market value is time-stamped, so the
backtest squads get their own season's values, not today's.

Run discovery:  python -m src.pipeline.fetch_transfermarkt --discover
Run the lot:    python -m src.pipeline.fetch_transfermarkt
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote_plus

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

from src.pipeline.name_matcher import Matcher, normalize

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"
CHROMIUM = "/usr/bin/chromium"
CHROMEDRIVER = "/usr/bin/chromedriver"

IDS_CSV = RAW / "transfermarkt_team_ids.csv"
ID_FIELDS = ["country_code", "country", "tm_id", "tm_slug", "tm_text", "score", "method"]
SQUAD_FIELDS = ["country_code", "season", "player_name", "position", "club",
                "tm_player_id", "market_value_eur"]

SEARCH_URL = "https://www.transfermarkt.com/schnellsuche/ergebnis/schnellsuche?query={q}"
KADER_URL = ("https://www.transfermarkt.com/{slug}/kader/verein/{tm_id}"
             "/saison_id/{season}/plus/1")
# squad file -> Transfermarkt saison_id (the squad's pre-tournament season, PLAN §1.2).
# WC editions plus the continental backtest editions (Euro 2020 -> 2020/21, Euro 2024
# and Copa 2024 -> 2023/24) so the §4.5 ablation's market step is fair across folds.
SQUAD_SOURCES = {
    "squads_2018.csv": "2017", "squads_2022.csv": "2021", "squads_2026.csv": "2025",
    "squads_euro2020.csv": "2020", "squads_euro2024.csv": "2023",
    "squads_copa2024.csv": "2023",
}
TM_SEASONS = sorted(set(SQUAD_SOURCES.values()))
# non-senior variants to drop from search candidates before the fuzzy match
_VARIANT = re.compile(r"\b(U-?\d+|Olympic|Olympia|Beach|Futsal|Women|Ladies|Youth|"
                      r"amateur|XI|B)\b", re.I)
DELAY_S = 3.0  # polite gap between page loads (PLAN "Known Challenges": sleep 3)


def parse_market_value(s: str) -> int | None:
    """Transfermarkt value string -> euros. '€20.00m'->20000000, '€800k'->800000,
    '€500'->500, '-'/''->None. Pure, testable."""
    s = (s or "").strip().replace("\xa0", " ")
    m = re.search(r"€\s*([\d.,]+)\s*(m|k|bn)?", s, re.I)
    if not m:
        return None
    num = float(m.group(1).replace(",", ""))
    mult = {"bn": 1_000_000_000, "m": 1_000_000, "k": 1_000, None: 1}[
        (m.group(2) or "").lower() or None]
    return int(round(num * mult))


def parse_squad_table(table_html: str, code: str, season: str) -> list[dict]:
    """Parse a kader/plus/1 `table.items` into squad rows. Player name from the
    /profil/spieler/ anchor, position from the inline-table's second line, club
    from the /verein/ anchor title, market value from the trailing `rechts` cell.
    Pure, testable."""
    table = BeautifulSoup(table_html, "lxml").find("table", class_="items")
    rows = []
    for tr in table.select("tbody > tr"):
        cls = tr.get("class") or []
        if not cls or cls[0] not in ("odd", "even"):
            continue  # skip group/separator rows
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 3:
            continue
        name_a = tr.select_one("a[href*='/profil/spieler/']")
        if not name_a:
            continue
        player = name_a.get_text(strip=True)
        pid = re.search(r"/spieler/(\d+)", name_a.get("href", ""))
        inline = tr.select_one("table.inline-table")
        pos = ""
        if inline:
            inner = inline.select("tr")
            if len(inner) > 1:
                pos = inner[1].get_text(strip=True)
        club_a = tr.select_one("td.zentriert a[href*='/verein/'] img")
        club = (club_a.get("alt") or club_a.get("title") or "").strip() if club_a else ""
        if not club:
            ca = tr.select_one("td.zentriert a[title][href*='/verein/']")
            club = ca.get("title", "").strip() if ca else ""
        mv = parse_market_value(tds[-1].get_text(" ", strip=True))
        rows.append({"country_code": code, "season": season, "player_name": player,
                     "position": pos, "club": club,
                     "tm_player_id": pid.group(1) if pid else "",
                     "market_value_eur": mv if mv is not None else ""})
    return rows


def harvest_search_candidates(search_html: str) -> list[tuple[str, str, str]]:
    """(slug, tm_id, text) for every distinct national/club verein link on a
    quick-search result page. Pure, testable."""
    soup = BeautifulSoup(search_html, "lxml")
    seen, out = set(), []
    for a in soup.select("a[href*='/verein/']"):
        m = re.search(r"/([^/]+)/(?:startseite|kader)/verein/(\d+)", a.get("href", ""))
        txt = a.get_text(strip=True)
        if not m or not txt or m.group(2) in seen:
            continue
        seen.add(m.group(2))
        out.append((m.group(1), m.group(2), txt))
    return out


def pick_national_team(candidates, country: str, threshold: float = 0.84):
    """Pick the senior national team from search candidates: drop youth/Olympic/etc.
    variants, then take the best fuzzy text match to the country name. Returns
    (slug, tm_id, text, score) or None. Pure, testable."""
    senior = [c for c in candidates if not _VARIANT.search(c[2])]
    m = Matcher(choices=[c[2] for c in senior], threshold=threshold)
    target, score, method = m.match(country)
    if target is None:
        return None
    for slug, tm_id, txt in senior:
        if txt == target:
            return slug, tm_id, txt, score
    return None


def make_driver(headless: bool = True) -> webdriver.Chrome:
    opts = Options()
    opts.binary_location = CHROMIUM
    args = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
            "--window-size=1920,1080", "--disable-blink-features=AutomationControlled",
            "--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"]
    if headless:
        args.insert(0, "--headless=new")
    for a in args:
        opts.add_argument(a)
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    d = webdriver.Chrome(service=Service(executable_path=CHROMEDRIVER), options=opts)
    d.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument",
                      {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"})
    return d


def _load(driver, url: str, needle: str, timeout: float = 40.0) -> str:
    """Navigate, wait out any challenge until `needle` is in the source, return it."""
    driver.get(url)
    deadline = time.time() + timeout
    while time.time() < deadline:
        src = driver.page_source or ""
        if "Just a moment" not in (driver.title or "") and needle in src:
            return src
        time.sleep(2)
    raise RuntimeError(f"blocked/timeout loading {url} (title={driver.title!r})")


def discover_ids(driver, nations: list[tuple[str, str]]) -> list[dict]:
    """nations = [(code, country)] -> resolved id rows; unresolved go to stderr."""
    resolved, unresolved = [], []
    for code, country in nations:
        try:
            src = _load(driver, SEARCH_URL.format(q=quote_plus(country)), "/verein/")
            pick = pick_national_team(harvest_search_candidates(src), country)
        except Exception as e:
            print(f"  {code} {country}: search FAILED {e}", file=sys.stderr)
            pick = None
        if pick:
            slug, tm_id, txt, score = pick
            method = "exact" if normalize(txt) == normalize(country) else "fuzzy"
            resolved.append({"country_code": code, "country": country, "tm_id": tm_id,
                             "tm_slug": slug, "tm_text": txt, "score": round(score, 3),
                             "method": method})
            print(f"  {code} {country}: -> {txt!r} id={tm_id} ({method} {score:.2f})")
        else:
            unresolved.append((code, country))
            print(f"  {code} {country}: UNRESOLVED — manual override needed", file=sys.stderr)
        time.sleep(DELAY_S)
    if unresolved:
        print(f"\n{len(unresolved)} unresolved (add to {IDS_CSV.name} by hand): "
              f"{[c for c, _ in unresolved]}", file=sys.stderr)
    return resolved


def write_ids(rows: list[dict]) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    with open(IDS_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ID_FIELDS)
        w.writeheader()
        w.writerows(rows)


def load_ids() -> dict[str, dict]:
    if not IDS_CSV.exists():
        return {}
    return {r["country_code"]: r for r in csv.DictReader(IDS_CSV.open())}


def fetch_squad(driver, code: str, slug: str, tm_id: str, season: str,
                verify_name: str, refresh: bool = False) -> Path:
    out = RAW / f"transfermarkt_{code}_{season}.csv"
    if out.exists() and not refresh:
        return out
    src = _load(driver, KADER_URL.format(slug=slug, tm_id=tm_id, season=season),
                'class="items"')
    # verify the page is the team we asked for, not a redirect/wrong id. Check
    # against the Transfermarkt name (tm_text), not the squad-file country — TM uses
    # its own spelling (Türkiye, Democratic Republic of the Congo) in the title.
    if normalize(verify_name).split()[0] not in normalize(driver.title):
        raise RuntimeError(f"title {driver.title!r} does not name {verify_name!r} (id {tm_id})")
    rows = parse_squad_table(src, code, season)
    if not rows:
        raise RuntimeError(f"no squad rows parsed for {code} {season} (id {tm_id})")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SQUAD_FIELDS)
        w.writeheader()
        w.writerows(rows)
    return out


def squad_jobs() -> list[tuple[str, str, str]]:
    """(code, country, season) for every nation in each squad file, mapped to its
    pre-tournament Transfermarkt season. De-duplicated."""
    jobs, seen = [], set()
    for fname, season in SQUAD_SOURCES.items():
        f = RAW / fname
        if not f.exists():
            continue
        for r in csv.DictReader(f.open()):
            key = (r["country_code"], season)
            if key not in seen:
                seen.add(key)
                jobs.append((r["country_code"], r["country"], season))
    return jobs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover", action="store_true", help="harvest team ids only")
    ap.add_argument("--country", help="limit to one FIFA code")
    ap.add_argument("--season", choices=TM_SEASONS)
    ap.add_argument("--headed", action="store_true", help="run headed under xvfb")
    ap.add_argument("--refresh", action="store_true", help="re-pull cached files")
    args = ap.parse_args()

    driver = make_driver(headless=not args.headed)
    try:
        ids = load_ids()
        # incremental discovery: only nations not already in the crosswalk, so manual
        # alias overrides (Türkiye, Czechia, ...) are preserved, not re-resolved away.
        needed = sorted({(c, n) for c, n, _ in squad_jobs()})
        if args.country:
            needed = [(c, n) for c, n in needed if c == args.country]
        todo = needed if args.discover else [(c, n) for c, n in needed if c not in ids]
        if todo:
            print(f"discovering {len(todo)} national-team ids...")
            ids.update({r["country_code"]: r for r in discover_ids(driver, todo)})
            write_ids(sorted(ids.values(), key=lambda r: r["country_code"]))
            print(f"wrote {len(ids)} ids -> {IDS_CSV.name}")
            if args.discover:
                return

        jobs = squad_jobs()
        if args.country:
            jobs = [j for j in jobs if j[0] == args.country]
        if args.season:
            jobs = [j for j in jobs if j[2] == args.season]
        done = fail = 0
        for i, (code, country, season) in enumerate(jobs):
            row = ids.get(code)
            if not row:
                print(f"  [{i+1}/{len(jobs)}] {code} {season}: no id, skipped",
                      file=sys.stderr)
                fail += 1
                continue
            try:
                out = fetch_squad(driver, code, row["tm_slug"], row["tm_id"], season,
                                  row.get("tm_text") or country, refresh=args.refresh)
                n = sum(1 for _ in open(out)) - 1
                print(f"  [{i+1}/{len(jobs)}] {code} {season}: {n} players -> {out.name}")
                done += 1
            except Exception as e:
                print(f"  [{i+1}/{len(jobs)}] {code} {season}: FAILED {e}", file=sys.stderr)
                fail += 1
            time.sleep(DELAY_S)
        print(f"done: {done} pulled, {fail} failed")
        if fail:
            sys.exit(1)
    finally:
        driver.quit()


if __name__ == "__main__":
    main()

"""FIFA/Coca-Cola Men's World Ranking — the Art. 13 final group tiebreaker.

Art. 13 §1 g) ranks teams still level on points, GD, GF and conduct by the most recent
FIFA ranking. The simulator otherwise falls back to an Elo-order proxy (deviations.md);
this pulls the real thing.

FIFA serves the ranking from inside.fifa.com: the men's-ranking page embeds the list of
published editions (allAvailableDates) in its __NEXT_DATA__, and /api/ranking-overview
returns one edition's full table. The newest editions use a new id scheme the public
overview endpoint doesn't serve yet, so we walk editions newest-first and take the most
recent one that actually returns rows. Writes data/raw/fifa_rankings_2026.csv
(fifa_code, rank, points, edition_date). requests (apt base).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import requests

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"
OUT = RAW / "fifa_rankings_2026.csv"
PAGE = "https://inside.fifa.com/fifa-world-ranking/men"
API = "https://inside.fifa.com/api/ranking-overview"
UA = {"User-Agent": "Mozilla/5.0", "Referer": PAGE}


def available_editions() -> list[dict]:
    """[{id, date}, ...] newest-first, from the page's embedded Next.js data."""
    html = requests.get(PAGE, headers=UA, timeout=30).text
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise RuntimeError("FIFA ranking page layout changed: no __NEXT_DATA__")
    data = json.loads(m.group(1))
    dates = data["props"]["pageProps"]["pageData"]["ranking"]["allAvailableDates"]
    return [{"id": d["id"], "date": d["date"]} for d in dates]


def fetch_edition(date_id: str) -> list[dict]:
    """One edition's rows: {fifa_code, rank, points}. Empty if the endpoint has no data."""
    r = requests.get(API, headers=UA, params={"locale": "en", "dateId": date_id}, timeout=30)
    r.raise_for_status()
    rows = []
    for item in r.json().get("rankings", []):
        ri = item["rankingItem"]
        if ri.get("rank") is None or not ri.get("countryCode"):
            continue  # unranked / placeholder rows
        rows.append({"fifa_code": ri["countryCode"], "rank": int(ri["rank"]),
                     "points": float(ri["totalPoints"])})
    return rows


def latest_ranking() -> tuple[str, list[dict]]:
    """The newest edition the public API actually serves: (edition_date, rows)."""
    for ed in available_editions():
        rows = fetch_edition(ed["id"])
        if rows:
            return ed["date"], rows
    raise RuntimeError("no FIFA edition returned rows")


def main() -> None:
    edition_date, rows = latest_ranking()
    df = pd.DataFrame(rows).sort_values("rank").reset_index(drop=True)
    df["edition_date"] = edition_date
    RAW.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)

    field = set(pd.read_csv(RAW / "team_codes.csv")["fifa_code"])
    covered = field & set(df["fifa_code"])
    print(f"FIFA ranking edition {edition_date}: {len(df)} teams -> {OUT.relative_to(REPO)}")
    print(f"WC2026 field covered: {len(covered)}/{len(field)}")
    missing = sorted(field - covered)
    if missing:
        print(f"  MISSING (not in FIFA list — check code mapping): {missing}")
    print(df[df["fifa_code"].isin(field)].head(10).to_string(index=False))


if __name__ == "__main__":
    main()

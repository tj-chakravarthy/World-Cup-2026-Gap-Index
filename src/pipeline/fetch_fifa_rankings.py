"""FIFA/Coca-Cola Men's World Ranking — the Art. 13 final group tiebreaker.

Art. 13 §1 g) ranks teams still level on points, GD, GF and conduct by the most recent
FIFA ranking. The simulator otherwise falls back to an Elo-order proxy (deviations.md);
this pulls the real thing.

Source: FIFA's Data Connect API (api.fifa.com/api/v3), the backend inside.fifa.com's ranking
page actually calls. Two hops: `rankingschedules/all` lists the published editions (newest =
the current one), then `rankingsbyschedule` returns that edition's full table. The older
`ranking-overview` endpoint only serves editions up to 2025-09-18, which is why this uses the
Data Connect API instead. Writes data/raw/fifa_rankings_2026.csv (fifa_code, rank, points,
edition_date). requests (apt base).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import requests

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"
OUT = RAW / "fifa_rankings_2026.csv"

FDCP = "https://api.fifa.com/api/v3"
# Public web-client id embedded in inside.fifa.com's ranking page — not a secret. If FIFA
# rotates it the calls 4xx and this fails loudly; refresh it from the page's JS bundle.
ID_CLIENT = "64e9afa8-c5c0-413d-882b-bc9e6a81e264"
UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://inside.fifa.com/fifa-world-ranking/men"}


def _get(path: str, **params) -> dict:
    r = requests.get(f"{FDCP}{path}", params={"idClient": ID_CLIENT, **params},
                     headers=UA, timeout=30)
    r.raise_for_status()
    return r.json()


def latest_schedule() -> tuple[str, str]:
    """(rankingScheduleId, official date YYYY-MM-DD) of the most recent men's edition
    (type=0 international, gender=1 men)."""
    scheds = _get("/rankingschedules/all", type=0, gender=1)["Results"]
    latest = max(scheds, key=lambda s: s["OfficialDate"])
    return latest["IdRankingSchedule"], latest["OfficialDate"][:10]


def fetch_ranking(schedule_id: str) -> list[dict]:
    """One edition's full table -> [{fifa_code, rank, points}], from rankingsbyschedule."""
    rows = []
    for t in _get("/rankingsbyschedule", rankingScheduleId=schedule_id, count=300).get("Results", []):
        if t.get("IdCountry") and t.get("Rank") is not None:
            rows.append({"fifa_code": t["IdCountry"], "rank": int(t["Rank"]),
                         "points": float(t.get("DecimalTotalPoints") or 0)})
    return rows


def main() -> None:
    schedule_id, edition_date = latest_schedule()
    df = pd.DataFrame(fetch_ranking(schedule_id)).sort_values("rank").reset_index(drop=True)
    df["edition_date"] = edition_date

    # coverage gate BEFORE writing: a partial canonical file silently downgrades the Art. 13
    # final tiebreaker to the Elo-order proxy at sim time (load_fifa_rankings returns None unless
    # every field team is present). Refuse to write an incomplete ranking — fail loud here rather
    # than let a half-real ranking pass as canonical.
    field = set(pd.read_csv(RAW / "team_codes.csv")["fifa_code"])
    missing = sorted(field - set(df["fifa_code"]))
    if missing:
        raise SystemExit(
            f"FIFA ranking edition {edition_date} covers {len(field) - len(missing)}/{len(field)} "
            f"of the WC2026 field — refusing to write a partial {OUT.name} (check code mapping). "
            f"Missing: {missing}"
        )

    RAW.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    print(f"FIFA ranking edition {edition_date} ({schedule_id}): {len(df)} teams "
          f"-> {OUT.relative_to(REPO)}")
    print(f"WC2026 field covered: {len(field)}/{len(field)}")
    print(df[df["fifa_code"].isin(field)].head(8).to_string(index=False))


if __name__ == "__main__":
    main()

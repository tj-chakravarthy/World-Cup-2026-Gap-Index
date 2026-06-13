"""Venue heat forecast — Open-Meteo (PLAN.md §1.5). Keyless, no scraping.

Climate normals are already baked into venues_2026.csv (Stage 0). This is the
other half of the heat feature: a live daily forecast per venue for the next
~2 weeks, so matches inside the forecast window use the real expected heat
(temperature + humidity + apparent temperature) instead of the long-run normal.
heat_index itself is assembled at feature time (PLAN §1.5 / Stage 3); this just
pulls and stores the forecast.

Forecast snapshot, regenerable -> gitignored. Stdlib only.
Run: python -m src.pipeline.fetch_weather
"""

from __future__ import annotations

import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://api.open-meteo.com/v1/forecast"
DAILY = "temperature_2m_max,apparent_temperature_max,relative_humidity_2m_mean"
FORECAST_DAYS = 16  # Open-Meteo's max free horizon

REPO = Path(__file__).resolve().parents[2]
VENUES_CSV = REPO / "data" / "raw" / "venues_2026.csv"
WEATHER_CSV = REPO / "data" / "raw" / "weather_forecast.csv"
FIELDS = ["venue_key", "date", "temp_max_c", "apparent_max_c", "rh_mean_pct", "fetched_at"]


def fetch_venue(lat: str, lon: str) -> dict:
    q = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon, "daily": DAILY,
        "forecast_days": FORECAST_DAYS, "timezone": "UTC",
    })
    with urllib.request.urlopen(f"{API}?{q}", timeout=30) as resp:
        return json.load(resp)["daily"]


def build_rows(venues: list[dict], now: str) -> list[dict]:
    rows = []
    for v in venues:
        d = fetch_venue(v["lat"], v["lon"])
        for i, day in enumerate(d["time"]):
            rows.append({
                "venue_key": v["venue_key"], "date": day,
                "temp_max_c": d["temperature_2m_max"][i],
                "apparent_max_c": d["apparent_temperature_max"][i],
                "rh_mean_pct": d["relative_humidity_2m_mean"][i],
                "fetched_at": now,
            })
        time.sleep(0.5)  # be polite to the free endpoint
    return rows


def main() -> None:
    venues = list(csv.DictReader(VENUES_CSV.open()))
    now = datetime.now(timezone.utc).date().isoformat()
    rows = build_rows(venues, now)
    if len(rows) < len(venues):
        raise ValueError(f"got {len(rows)} forecast rows for {len(venues)} venues")

    WEATHER_CSV.parent.mkdir(parents=True, exist_ok=True)
    with WEATHER_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} forecast rows for {len(venues)} venues "
          f"(through {rows[-1]['date']}) -> {WEATHER_CSV.relative_to(REPO)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"weather fetch failed: {e}", file=sys.stderr)
        sys.exit(1)

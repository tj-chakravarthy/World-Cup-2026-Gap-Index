"""Per-fixture, per-team travel/rest context (PLAN.md §1.5).

The unified match model trains on one row per (fixture, team). This module turns
a fixtures frame into the tidy travel/rest block of that row: how rested a team
is, how far it has flown, how much its body-clock has shifted, and the venue's
altitude. Computed independently for the home and away team of each fixture, so
the output is long: two rows per fixture, keyed (fixture_id, team_code).

The builder is generic — it works on any fixtures frame that carries the needed
columns (a kickoff timestamp, a per-row team code, and, when available, that
row's venue coords/tz/altitude). The 2026 path joins venue coords from
venues_2026.csv and computes everything. Historical fixtures built from
match_results lack coords (only city/country): for those, rest_days still comes
from dates alone, but travel/timezone/altitude are emitted as NaN and
`context_missing` is set True. We never fabricate coordinates.

Great-circle distance is the haversine formula in stdlib math (the `haversine`
pip package is not a dependency). pandas only otherwise.
"""

from __future__ import annotations

import math
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"

EARTH_RADIUS_KM = 6371.0
# first match of a team has no prior fixture; assume a week's rest (squads gather
# pre-tournament). travel/tz are 0 for the first match — no journey to measure.
DEFAULT_FIRST_REST_DAYS = 7.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km (haversine, Earth radius 6371 km)."""
    rlat1, rlon1, rlat2, rlon2 = map(math.radians, (lat1, lon1, lat2, lon2))
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def tz_offset_hours(tz: str, when: pd.Timestamp) -> float:
    """UTC offset (hours) of an IANA tz at a given instant — DST-aware via zoneinfo.
    Returns NaN for a missing/unknown tz so the caller can flag missingness."""
    if not isinstance(tz, str) or not tz:
        return float("nan")
    try:
        off = when.to_pydatetime().astimezone(ZoneInfo(tz)).utcoffset()
    except Exception:
        return float("nan")
    return off.total_seconds() / 3600.0 if off is not None else float("nan")


def _team_long(fixtures: pd.DataFrame) -> pd.DataFrame:
    """Explode a wide fixtures frame (home_*/away_*) into one row per team-fixture.

    Expects: fixture_id, kickoff_utc, home_code, away_code, and the per-side venue
    columns lat/lon/tz/altitude_m already joined as home_lat/away_lat etc. Venue
    columns may be absent (historical fixtures): then they come out NaN.
    """
    ts = pd.to_datetime(fixtures["kickoff_utc"], utc=True)
    rows = []
    for side, other in (("home", "away"), ("away", "home")):
        sub = pd.DataFrame({
            "fixture_id": fixtures["fixture_id"].values,
            "kickoff_utc": ts.values,
            "team_code": fixtures[f"{side}_code"].values,
            "opp_code": fixtures[f"{other}_code"].values,
            "lat": fixtures.get(f"{side}_lat"),
            "lon": fixtures.get(f"{side}_lon"),
            "tz": fixtures.get(f"{side}_tz"),
            "venue_altitude_m": fixtures.get(f"{side}_altitude_m"),
        })
        rows.append(sub)
    out = pd.concat(rows, ignore_index=True)
    # missing-coord side keeps NaN (historical fixtures); ensure columns exist
    for c in ("lat", "lon", "venue_altitude_m"):
        if c not in out or out[c] is None:
            out[c] = float("nan")
    if "tz" not in out or out["tz"] is None:
        out["tz"] = None
    return out


def build_travel_rest(fixtures: pd.DataFrame) -> pd.DataFrame:
    """One row per (fixture_id, team_code) with the travel/rest context block.

    `fixtures` columns required: fixture_id, kickoff_utc (ISO/UTC), home_code,
    away_code. Optional per-side venue columns (join them in for the full 2026
    compute): {home,away}_lat, {home,away}_lon, {home,away}_tz,
    {home,away}_altitude_m. When the venue columns are absent or NaN for a row,
    travel/timezone/altitude come out NaN and `context_missing` is True for that
    team-fixture; rest is always computed from kickoff dates.

    Output columns: fixture_id, team_code, opp_code, kickoff_utc, rest_days,
    rest_diff, travel_km_since_last, cumulative_travel_km, timezone_shift_hours,
    venue_altitude_m, context_missing.
    """
    long = _team_long(fixtures)
    long = long.sort_values(["team_code", "kickoff_utc"]).reset_index(drop=True)

    long["tz_offset"] = [
        tz_offset_hours(tz, when) for tz, when in zip(long["tz"], long["kickoff_utc"])
    ]

    out_parts = []
    for code, g in long.groupby("team_code", sort=False):
        g = g.copy()
        prev_time = g["kickoff_utc"].shift(1)
        rest = (g["kickoff_utc"] - prev_time).dt.total_seconds() / 86400.0
        g["rest_days"] = rest.fillna(DEFAULT_FIRST_REST_DAYS)

        prev_lat, prev_lon = g["lat"].shift(1), g["lon"].shift(1)
        leg = [
            haversine_km(la0, lo0, la1, lo1)
            if pd.notna(la0) and pd.notna(lo0) and pd.notna(la1) and pd.notna(lo1)
            else float("nan")
            for la0, lo0, la1, lo1 in zip(prev_lat, prev_lon, g["lat"], g["lon"])
        ]
        g["travel_km_since_last"] = leg
        # first match has no leg -> 0 km travelled (not missing); coords known.
        first = prev_time.isna()
        g.loc[first & g["lat"].notna(), "travel_km_since_last"] = 0.0
        g["cumulative_travel_km"] = g["travel_km_since_last"].cumsum()

        prev_off = g["tz_offset"].shift(1)
        g["timezone_shift_hours"] = g["tz_offset"] - prev_off
        g.loc[first & g["tz_offset"].notna(), "timezone_shift_hours"] = 0.0
        out_parts.append(g)

    out = pd.concat(out_parts, ignore_index=True)
    # missing iff this row's venue coords are absent (can't place the team)
    out["context_missing"] = out["lat"].isna() | out["lon"].isna()

    # rest_diff needs both teams' rest_days; join per fixture on the opponent.
    rest_lookup = out.set_index(["fixture_id", "team_code"])["rest_days"]
    opp_rest = out.apply(
        lambda r: rest_lookup.get((r["fixture_id"], r["opp_code"]), float("nan")),
        axis=1,
    )
    out["rest_diff"] = out["rest_days"] - opp_rest

    cols = [
        "fixture_id", "team_code", "opp_code", "kickoff_utc", "rest_days",
        "rest_diff", "travel_km_since_last", "cumulative_travel_km",
        "timezone_shift_hours", "venue_altitude_m", "context_missing",
    ]
    return out[cols].sort_values(["kickoff_utc", "fixture_id", "team_code"]).reset_index(drop=True)


def join_venue_coords(fixtures: pd.DataFrame, venues: pd.DataFrame) -> pd.DataFrame:
    """Attach each fixture's venue lat/lon/tz/altitude as home_* and away_* columns.

    Both teams of a fixture play at the same venue (`venue_key`), so home and away
    get identical coords; the home/away split exists so the per-team builder reads
    a uniform schema (and so a historical frame with per-side venues would also
    fit). 2026 helper — `venues` is venues_2026.csv.
    """
    v = venues.set_index("venue_key")[["lat", "lon", "tz", "altitude_m"]]
    out = fixtures.copy()
    for side in ("home", "away"):
        joined = out["venue_key"].map(v.to_dict("index"))
        out[f"{side}_lat"] = [d["lat"] if isinstance(d, dict) else float("nan") for d in joined]
        out[f"{side}_lon"] = [d["lon"] if isinstance(d, dict) else float("nan") for d in joined]
        out[f"{side}_tz"] = [d["tz"] if isinstance(d, dict) else None for d in joined]
        out[f"{side}_altitude_m"] = [d["altitude_m"] if isinstance(d, dict) else float("nan") for d in joined]
    return out


def load_travel_rest_2026(raw_dir: Path = RAW) -> pd.DataFrame:
    """Convenience: build the 2026 travel/rest context from disk (fixtures +
    venues). Full compute — coords available, so context_missing is False."""
    fixtures = pd.read_csv(raw_dir / "fixtures_2026.csv")
    venues = pd.read_csv(raw_dir / "venues_2026.csv")
    return build_travel_rest(join_venue_coords(fixtures, venues))

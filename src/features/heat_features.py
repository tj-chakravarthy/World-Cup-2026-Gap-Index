"""Per-fixture heat context (PLAN.md §1.5).

Apparent temperature at kickoff, from the venue climate normals
(climate_high_c + climate_rh_pct in venues_2026.csv), modulated by kickoff hour
and damped for roofed (climate-controlled) stadiums. This is the climate-normals
baseline. fetch_weather.py pulls an Open-Meteo live forecast per venue; for
matches <=7 days out the consumer overrides the climate value with that
forecast's apparent_max_c (PLAN §1.5). We leave the hook here but don't call it.

heat_mismatch (a team's heat vs. the climate its players are acclimatised to) is
deferred — exploratory in PLAN, and the squads' club_country column is empty, so
there's no origin climate to compare against. Not implemented here.

pandas only.
"""

from __future__ import annotations

import pandas as pd

# Kickoff-hour modulation. Climate_high_c is the daily high, reached mid-afternoon.
# Afternoon kickoffs sit at (or just under) that high; evening kickoffs cool off.
# Simple piecewise scale of the daily high by local kickoff hour — a fraction of
# the high, not a full diurnal model. Kolla mot live-forecast när den finns.
_HOUR_SCALE = [
    (11, 14, 1.00),  # noon–early afternoon: at the daily high
    (14, 17, 0.97),  # mid-afternoon: just off the peak
    (17, 19, 0.90),  # early evening
    (19, 24, 0.82),  # night games: meaningfully cooler
]
_DEFAULT_HOUR_SCALE = 0.85  # outside the table (very early / very late)

# Roofed venues are climate-controlled; pull the apparent temp toward a comfort
# baseline rather than zeroing it (air handling isn't perfect, crowd adds load).
ROOFED_DAMP = 0.5
ROOFED_BASELINE_C = 22.0


def heat_index_c(temp_c: float, rh_pct: float) -> float:
    """Humidity-adjusted apparent temperature in Celsius (NOAA heat-index regression).

    The NOAA Rothfusz regression is defined in Fahrenheit; we convert in/out so the
    public API stays in Celsius (the unit of the climate normals). Below ~26.7C
    (80F) the regression isn't meaningful, so the dry temperature is returned
    unchanged. Monotonic non-decreasing in both temp and humidity over the warm
    range, which is what the feature needs.

    Baseline = climate normals. A live Open-Meteo apparent_temperature_max
    (fetch_weather.py) overrides this for matches <=7 days out at consume time.
    """
    t_f = temp_c * 9.0 / 5.0 + 32.0
    if t_f < 80.0:
        return temp_c
    rh = rh_pct
    hi_f = (-42.379 + 2.04901523 * t_f + 10.14333127 * rh
            - 0.22475541 * t_f * rh - 6.83783e-3 * t_f * t_f
            - 5.481717e-2 * rh * rh + 1.22874e-3 * t_f * t_f * rh
            + 8.5282e-4 * t_f * rh * rh - 1.99e-6 * t_f * t_f * rh * rh)
    return (hi_f - 32.0) * 5.0 / 9.0


def hour_scale(local_hour: int) -> float:
    """Fraction of the daily high realised at a given local kickoff hour."""
    for lo, hi, s in _HOUR_SCALE:
        if lo <= local_hour < hi:
            return s
    return _DEFAULT_HOUR_SCALE


def kickoff_heat_c(climate_high_c: float, climate_rh_pct: float,
                   local_hour: int, roofed: int) -> float:
    """Apparent temperature a fixture is played in, from climate normals.

    Scale the daily-high climate temperature toward the kickoff hour's level,
    apply the humidity heat-index, then damp roofed venues toward the indoor
    comfort baseline.
    """
    temp = climate_high_c * hour_scale(local_hour)
    hi = heat_index_c(temp, climate_rh_pct)
    if roofed:
        hi = ROOFED_BASELINE_C + (hi - ROOFED_BASELINE_C) * (1.0 - ROOFED_DAMP)
    return hi


def attach_fixture_heat(fixtures: pd.DataFrame, venues: pd.DataFrame) -> pd.DataFrame:
    """One row per fixture with its kickoff heat (apparent temp at the venue).

    `fixtures`: fixture_id, kickoff_utc (ISO/UTC), venue_key. `venues`:
    venue_key, tz, roofed, climate_high_c, climate_rh_pct. Local kickoff hour is
    the UTC kickoff converted to the venue tz.

    Output columns: fixture_id, local_hour, climate_high_c, climate_rh_pct,
    roofed, heat_index_c.
    """
    v = venues.set_index("venue_key")
    ts = pd.to_datetime(fixtures["kickoff_utc"], utc=True)

    rows = []
    for fid, vkey, t in zip(fixtures["fixture_id"], fixtures["venue_key"], ts):
        ven = v.loc[vkey]
        local_hour = int(t.tz_convert(ven["tz"]).hour)
        roofed = int(ven["roofed"])
        rows.append({
            "fixture_id": fid,
            "local_hour": local_hour,
            "climate_high_c": float(ven["climate_high_c"]),
            "climate_rh_pct": float(ven["climate_rh_pct"]),
            "roofed": roofed,
            "heat_index_c": kickoff_heat_c(
                float(ven["climate_high_c"]), float(ven["climate_rh_pct"]),
                local_hour, roofed),
        })
    return pd.DataFrame(rows)

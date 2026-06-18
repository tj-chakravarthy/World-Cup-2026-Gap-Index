"""Static pre-tournament analysis for the site — analysis.json (PLAN.md §6).

The live page is the forecast; this surfaces the work behind it so it doesn't read as just a
simulator: the namesake Gap Index (talent vs result on completed tournaments, with uncertainty
bands), the club-stats player ratings, the feature ablation that explains why the live model is
Elo + market value only, and the backtest calibration. All four derive from the processed backtest
outputs (gitignored scrapes -> regenerable) and don't change during 2026, so this is built once and
committed — not on the live cron. pandas + stdlib.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
PROC = REPO / "data" / "processed"
OUT = REPO / "web" / "public" / "data" / "analysis.json"

# pretty tournament labels for the gap cards
TLABEL = {
    "world_cup_2018": "World Cup 2018", "world_cup_2022": "World Cup 2022",
    "euro_2020": "Euro 2020", "euro_2024": "Euro 2024",
    "copa_america_2024": "Copa América 2024",
}


def _gap() -> dict:
    """Talent-vs-result on the completed tournaments. gap = actual ppg - expected ppg (the residual
    talent doesn't explain); gap_lo/gap_hi is its band. R² is how much of points talent explains."""
    g = pd.read_csv(PROC / "gap.csv")
    g = g[g["tournament"] != "world_cup_2026"].copy()   # completed tournaments only (full gaps)
    ss_res = float((g["gap"] ** 2).sum())
    ss_tot = float(((g["ppg"] - g["ppg"].mean()) ** 2).sum())
    r2 = round(1 - ss_res / ss_tot, 2) if ss_tot else None
    g = g.sort_values("gap", ascending=False)
    teams = [{"t": TLABEL.get(r.tournament, r.tournament), "code": r.country_code, "team": r.team,
              "gap": round(r.gap, 2), "lo": round(r.gap_lo, 2), "hi": round(r.gap_hi, 2),
              "talent": round(r.talent, 2), "n": int(r.n_games)} for r in g.itertuples()]
    return {"r2": r2, "n_teams": len(teams), "teams": teams}


def _players(top: int = 40) -> dict:
    """The top club-stats player ratings (player_score, 0-100 from VAEP + market value) plus the
    size of the rated pool, so the site can show '40 of N'. Players with neither market value nor
    observed VAEP are left unrated (no score) and don't count toward the pool."""
    p = pd.read_csv(PROC / "player_scores.csv")
    rated = p.dropna(subset=["player_score"])
    top_rows = rated.sort_values("player_score", ascending=False).head(top)
    players = [{"name": r.player_name, "code": r.country_code, "pos": r.pos_group,
                "score": round(r.player_score, 1),
                "mv": round(r.market_value_eur / 1e6, 1) if pd.notna(r.market_value_eur) else None}
               for r in top_rows.itertuples()]
    return {"rated": int(len(rated)), "top": players}


def _ablation() -> dict:
    """Feature ablation on the backtest (Brier, lower better; ci_lo/ci_hi the 95% interval)."""
    a = pd.read_csv(PROC / "ablation.csv")
    rows = [{"set": r.feature_set, "brier": round(r.brier, 4),
             "lo": round(r.ci_lo, 4), "hi": round(r.ci_hi, 4)} for r in a.itertuples()]
    return {"n": int(a["n"].iloc[0]), "rows": rows}


def _calibration() -> list[dict]:
    """Reliability bins: predicted vs observed per outcome (on the diagonal = calibrated)."""
    c = pd.read_csv(PROC / "calibration_reliability.csv")
    return [{"outcome": r.outcome, "pred": round(r.pred_mean, 3),
             "obs": round(r.obs_rate, 3), "n": int(r.n)} for r in c.itertuples()]


def build() -> dict:
    pl = _players()
    return {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "gap": _gap(), "players": pl["top"], "players_rated": pl["rated"],
            "ablation": _ablation(), "calibration": _calibration()}


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(build(), indent=2) + "\n")
    g = build()["gap"]
    print(f"analysis.json -> {OUT.relative_to(REPO)} (gap R²={g['r2']}, {g['n_teams']} teams)")


if __name__ == "__main__":
    main()

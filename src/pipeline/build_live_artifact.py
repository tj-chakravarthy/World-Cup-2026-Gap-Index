"""Live predictions artifact — predictions_live.json (PLAN.md §6).

Packages the production match model's per-fixture W/D/L (predictions_2026_wdl.csv, from
match_model.py) plus Dixon-Coles tilted top-scorelines into the committed schema
(docs/artifact_schema.md), validated by write_predictions. Covers the unplayed group
fixtures (both teams known); already-played fixtures are evidence-only; the 32 knockout
slots are pending (participants undecided). The W/D/L is reused as-is, so this is a fast
repackage — only the scorelines need a Dixon-Coles fit + lambda-tilt (§5.2), no index
rebuild. Mirrors to web/public/data/ for the (future) static site. pandas + scipy.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from src.models.dixon_coles import fit as dc_fit
from src.models.scoreline import tilted_matrix
from src.pipeline.write_predictions import SCHEMA_VERSION, load_fixture_ids, write

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"
PROC = REPO / "data" / "processed"
OUT = REPO / "data" / "predictions" / "predictions_live.json"
WEB_MIRROR = REPO / "web" / "public" / "data" / "predictions_live.json"
WC_START = "2026-06-11"


def _git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                              capture_output=True, text=True).stdout.strip() or "nogit"
    except Exception:
        return "nogit"


def top_scorelines(matrix: np.ndarray, n: int = 5) -> list[dict]:
    """The n most likely (home-away) scorelines from a scoreline matrix. Pure."""
    side = matrix.shape[0]
    flat = np.argsort(matrix, axis=None)[::-1][:n]
    return [{"score": f"{int(i // side)}-{int(i % side)}", "p": round(float(matrix.flat[i]), 4)}
            for i in flat]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def model_inputs(indices: pd.DataFrame, fixtures: pd.DataFrame,
                 field: str = "world_cup_2026") -> dict:
    """The two live-model inputs per group fixture, in a legible form. The model is just
    ELO + MKT (z-scored index differentials); here each team's Elo and squad-value standing
    is expressed as a percentile within the tournament field — same ordering as the z-score,
    but fan-readable. Fixed pre-tournament, so it serves both the upcoming-fixture cards and
    the resolved track-record cards (predictions_live.json drops played games). Pure."""
    idx = indices[indices["tournament"] == field].set_index("country_code")
    elo_pct = idx["ELO"].rank(pct=True).mul(100)
    mkt_pct = idx["MKT"].rank(pct=True).mul(100)

    def _p(s: pd.Series, code: str):
        v = s.get(code)
        return None if v is None or pd.isna(v) else int(round(v))

    fx = {}
    for r in fixtures[fixtures["stage"] == "group"].itertuples():
        if r.home_code not in idx.index or r.away_code not in idx.index:
            continue
        fx[r.fixture_id] = {"team1": r.home_code, "team2": r.away_code,
                            "elo1": _p(elo_pct, r.home_code), "elo2": _p(elo_pct, r.away_code),
                            "mkt1": _p(mkt_pct, r.home_code), "mkt2": _p(mkt_pct, r.away_code)}
    return {"generated_at": _now(), "field": field,
            "metric": "percentile_within_field", "fixtures": fx}


def build_live(preds: pd.DataFrame, fixtures: pd.DataFrame, dc, code2m: dict[str, str],
               *, stale: bool = False) -> dict:
    """Assemble the live artifact dict from per-fixture W/D/L + tilted scorelines.

    stale=True (the fixture refresh fell back to cached scores, run_all's fresh=False) flags
    the live 'fixtures' source so the site's stale banner fires; the static match_results /
    match_model sources aren't live-refreshed, so they stay fresh."""
    now = _now()
    base = float(np.exp(dc.intercept))
    fx_meta = fixtures.set_index("fixture_id")
    predictions, covered, excluded = [], [], []
    for r in preds.itertuples():
        kickoff = str(fx_meta.loc[r.fixture_id, "kickoff_utc"])
        # exclude played fixtures AND any already kicked off — a lagging score feed can leave a
        # kicked-off match played=False; never publish a post-kickoff prediction (it isn't
        # "upcoming", and its real pre-kickoff prediction was committed in an earlier run). Keeps
        # the published set == the logged set (both pre-kickoff); write_predictions re-checks it.
        if bool(r.played) or kickoff <= now:
            excluded.append(r.fixture_id)
            continue
        na, nb = code2m.get(r.home_code), code2m.get(r.away_code)
        if na in dc.attack and nb in dc.attack:
            lam1, lam2 = dc.rates(na, nb, neutral=True)
        else:
            lam1 = lam2 = base
        m = tilted_matrix(lam1, lam2, dc.rho, (r.p_home, r.p_draw, r.p_away))
        wdl = {"team1": float(r.p_home), "draw": float(r.p_draw), "team2": float(r.p_away)}
        predictions.append({
            "fixture_id": r.fixture_id, "stage": "group",
            "kickoff_utc": kickoff,
            "team1": r.home_code, "team2": r.away_code, "model_source": "live_full",
            "wdl": wdl, "scorelines": top_scorelines(m),
            "members": {"full": wdl}, "conformal_set": None, "stale": stale})
        covered.append(r.fixture_id)

    all_ids = set(fixtures["fixture_id"])
    pending = sorted(all_ids - set(covered) - set(excluded))  # knockout slots, teams TBD
    return {
        "schema_version": SCHEMA_VERSION, "kind": "live",
        "model_version": f"live-elo-mkt@{_git_sha()}", "generated_at": now,
        "locked_at_utc": None, "tournament": "FIFA World Cup 26",
        "coverage": {"covered_fixture_ids": covered,
                     "excluded_played_fixture_ids": excluded,
                     "pending_undetermined_fixture_ids": pending},
        "sources": [{"name": n, "as_of": now, "stale": stale and n == "fixtures"}
                    for n in ("fixtures", "match_results", "match_model")],
        "predictions": predictions,
    }


def main() -> None:
    preds = pd.read_csv(PROC / "predictions_2026_wdl.csv")
    fixtures = pd.read_csv(RAW / "fixtures_2026.csv")
    results = pd.read_csv(RAW / "match_results.csv")
    tc = pd.read_csv(RAW / "team_codes.csv")
    code2m = dict(zip(tc["fifa_code"], tc["martj42_name"]))
    pre = results[results["date"].astype(str) < WC_START].dropna(
        subset=["home_score", "away_score"])
    dc = dc_fit([(str(r.date), r.home_team, r.away_team, int(r.home_score),
                  int(r.away_score), bool(r.neutral)) for r in pre.itertuples()],
                ref_date=WC_START)

    artifact = build_live(preds, fixtures, dc, code2m)
    write(artifact, OUT, fixture_universe=load_fixture_ids())
    WEB_MIRROR.parent.mkdir(parents=True, exist_ok=True)
    WEB_MIRROR.write_text(OUT.read_text())
    cov = artifact["coverage"]
    print(f"predictions_live.json: {len(artifact['predictions'])} fixtures "
          f"(covered {len(cov['covered_fixture_ids'])}, played "
          f"{len(cov['excluded_played_fixture_ids'])}, pending "
          f"{len(cov['pending_undetermined_fixture_ids'])}) -> {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()

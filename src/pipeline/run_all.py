"""Live update orchestrator (PLAN.md §6).

Refresh results, and if a new result has landed since last run, recompute the forecast
+ simulation, rewrite the JSON artifacts, append the prediction log, and stamp freshness.

Idempotent by design: no new result -> no work, no commit (so the GitHub Actions cron
can poll every 15 min cheaply and only the post-match run does the heavy recompute).
Loud failure: any step that throws exits non-zero, so the workflow fails visibly rather
than silently freezing a "live" site (PLAN §6 operational robustness). Fixture refresh is
best-effort with a cached fallback — one broken scraper degrades freshness, not the run.

v1 calls the stage mains in sequence; the pre-tournament squad-index build is a fixed
snapshot but repeats across match_model and monte_carlo — folding it into one shared,
cached bundle is the obvious next optimisation (heavy runs are ~per-match, so it is not
urgent). pandas only.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"
PRED = REPO / "data" / "predictions"
FIXTURES = RAW / "fixtures_2026.csv"
MARKER = PRED / ".last_played"
LIVE = PRED / "predictions_live.json"
SIM = PRED / "simulation.json"


def played_fixture_ids(fixtures: pd.DataFrame) -> set[str]:
    """The set of fixture_ids marked played, robust to bool/str encodings. Pure."""
    flag = fixtures["played"].astype(str).str.strip().str.lower().isin(["true", "1"])
    return set(fixtures.loc[flag, "fixture_id"])


def _refresh_fixtures() -> None:
    """Best-effort live-score refresh (keyless fixturedownload feed). On failure keep the
    cached fixtures — degrade freshness, don't crash (PLAN §6 cached fallback)."""
    try:
        from src.pipeline import fetch_fixtures_venues
        fetch_fixtures_venues.main()
    except Exception as e:  # noqa: BLE001 - scrapers are allowed to fail
        print(f"warn: fixture refresh failed ({e}); using cached fixtures", file=sys.stderr)


def _step(name: str, fn) -> None:
    """Run a pipeline step; any exception fails the whole run loudly (non-zero exit)."""
    try:
        fn()
    except Exception as e:  # noqa: BLE001
        print(f"FAIL [{name}]: {e}", file=sys.stderr)
        sys.exit(1)


def main(force: bool = False) -> None:
    _refresh_fixtures()
    played = played_fixture_ids(pd.read_csv(FIXTURES))
    last = set(MARKER.read_text().split()) if MARKER.exists() else set()
    artifacts_exist = LIVE.exists() and SIM.exists()
    if not force and artifacts_exist and played == last:
        print(f"no new results ({len(played)} played); nothing to update")
        return
    print(f"new evidence: {len(played)} played (was {len(last)}); recomputing forecast")

    from src.models import match_model, monte_carlo
    from src.pipeline import build_live_artifact
    _step("match_model", match_model.main)        # predictions_2026_wdl.csv
    _step("monte_carlo", monte_carlo.main)         # tournament_sim.csv + simulation.json
    _step("build_live_artifact", build_live_artifact.main)  # predictions_live.json

    try:  # track-record log (append-only); best-effort so a log hiccup never fails the run
        from src.update import prediction_log
        n = prediction_log.log_predictions(json.loads(LIVE.read_text()))
        print(f"prediction_log: +{n} new rows")
    except Exception as e:  # noqa: BLE001
        print(f"warn: prediction_log skipped ({e})", file=sys.stderr)

    PRED.mkdir(parents=True, exist_ok=True)
    MARKER.write_text(" ".join(sorted(played)))
    print(f"update complete {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} "
          f"({len(played)} results in)")


def check() -> bool:
    """Refresh fixtures and report whether a new result landed (or artifacts are
    missing) — the cheap pre-step the cron runs every poll before paying for the heavy
    recompute. True => recompute needed."""
    _refresh_fixtures()
    played = played_fixture_ids(pd.read_csv(FIXTURES))
    last = set(MARKER.read_text().split()) if MARKER.exists() else set()
    changed = played != last or not (LIVE.exists() and SIM.exists())
    print(f"played={len(played)} marker={len(last)} artifacts={LIVE.exists() and SIM.exists()} "
          f"-> changed={changed}")
    return changed


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(10 if check() else 0)  # exit 10 = new results, recompute needed
    main(force="--force" in sys.argv)

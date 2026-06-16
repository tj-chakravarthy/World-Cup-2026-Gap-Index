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

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"
PRED = REPO / "data" / "predictions"
PROC = REPO / "data" / "processed"
FIXTURES = RAW / "fixtures_2026.csv"
MARKER = PRED / ".last_played"
LIVE = PRED / "predictions_live.json"
SIM = PRED / "simulation.json"
WEB_LIVE = REPO / "web" / "public" / "data" / "predictions_live.json"
LIVE_SIMS = 100_000   # full draw count — the published site number; ~5x slower per update


def played_fixture_ids(fixtures: pd.DataFrame) -> set[str]:
    """The set of fixture_ids marked played, robust to bool/str encodings. Pure."""
    flag = fixtures["played"].astype(str).str.strip().str.lower().isin(["true", "1"])
    return set(fixtures.loc[flag, "fixture_id"])


def _refresh_fixtures() -> bool:
    """Best-effort live-score refresh (keyless fixturedownload feed). Returns whether it
    succeeded; on failure keep the cached fixtures — degrade freshness, don't crash
    (PLAN §6 cached fallback). The caller surfaces the stale signal loudly."""
    try:
        from src.pipeline import fetch_fixtures_venues
        fetch_fixtures_venues.main()
        return True
    except Exception as e:  # noqa: BLE001 - scrapers are allowed to fail
        print(f"warn: fixture refresh FAILED ({e}); using cached fixtures — DATA MAY BE STALE",
              file=sys.stderr)
        return False


def _step(name: str, fn) -> None:
    """Run a pipeline step; any exception fails the whole run loudly (non-zero exit)."""
    try:
        fn()
    except Exception as e:  # noqa: BLE001
        print(f"FAIL [{name}]: {e}", file=sys.stderr)
        sys.exit(1)


def main(force: bool = False, rebuild: bool = False) -> None:
    fresh = _refresh_fixtures()
    fixtures = pd.read_csv(FIXTURES)
    played = played_fixture_ids(fixtures)
    last = set(MARKER.read_text().split()) if MARKER.exists() else set()
    if not force and not rebuild and LIVE.exists() and SIM.exists() and played == last:
        print(f"no new results ({len(played)} played); nothing to update")
        return
    print(f"new evidence: {len(played)} played (was {len(last)}); recomputing forecast")

    import json
    newly = played - last  # the fixtures that resolved this run — cause of the movement
    before_sim = None      # snapshot the old odds before _sim overwrites simulation.json
    if SIM.exists():
        try:
            before_sim = json.loads(SIM.read_text())
        except Exception:  # noqa: BLE001 - a corrupt snapshot just means no movement panel
            before_sim = None

    from src.models import monte_carlo
    from src.pipeline import build_live_artifact, write_predictions
    bundle = monte_carlo.load_or_build_bundle(rebuild=rebuild)  # cached pre-tournament model

    def _sim():  # tournament_sim.csv + simulation.json (+ web mirror)
        # live updates run the full 100k draws so the public site number matches the model's
        # nominal precision (MC noise ~0.1pp). ~5x heavier than the old 20k, but the cron only
        # recomputes on a new result and the job's 6h budget covers it; clustered results just
        # queue (cancel-in-progress:false) and catch up.
        df = monte_carlo.simulate(bundle, fixtures, n_sims=LIVE_SIMS)
        PROC.mkdir(parents=True, exist_ok=True)
        df.to_csv(PROC / "tournament_sim.csv", index=False)
        monte_carlo.write_simulation_json(df, LIVE_SIMS)

    def _live():  # predictions_2026_wdl.csv -> predictions_live.json -> track-record log
        preds = monte_carlo.group_fixture_wdl(bundle, fixtures)
        preds.to_csv(PROC / "predictions_2026_wdl.csv", index=False)
        artifact = build_live_artifact.build_live(preds, fixtures, bundle.dc, bundle.code2m,
                                                  stale=not fresh)
        write_predictions.write(artifact, LIVE,
                                fixture_universe=write_predictions.load_fixture_ids())
        WEB_LIVE.parent.mkdir(parents=True, exist_ok=True)
        WEB_LIVE.write_text(LIVE.read_text())
        # the two live-model inputs per fixture (Elo + squad value), for the match cards
        mi = json.dumps(build_live_artifact.model_inputs(bundle.indices, fixtures), indent=2)
        for p in (PRED / "model_inputs.json", WEB_LIVE.parent / "model_inputs.json"):
            p.write_text(mi)
        try:  # append-only log, best-effort so a log hiccup never fails the run
            from src.update import prediction_log
            print(f"prediction_log: +{prediction_log.log_predictions(artifact)} new rows")
        except Exception as e:  # noqa: BLE001
            print(f"warn: prediction_log skipped ({e})", file=sys.stderr)

    _step("simulate", _sim)
    _step("live_artifact", _live)
    try:  # publish the public track-record receipts (resolved predictions vs results)
        import json
        from src.update import prediction_log
        art = prediction_log.track_record_artifact(prediction_log.load_log(), fixtures)
        for p in (PRED / "track_record.json", WEB_LIVE.parent / "track_record.json"):
            p.write_text(json.dumps(art, indent=2))
        print(f"track_record: {art['n_resolved']} resolved / {art['n_logged']} logged")
    except Exception as e:  # noqa: BLE001
        print(f"warn: track_record skipped ({e})", file=sys.stderr)
    try:  # 'what changed' panel — diff the new sim odds against the pre-result snapshot
        from src.update import movement
        mv = movement.build_movement(before_sim or {}, json.loads(SIM.read_text()), newly, fixtures)
        for p in (PRED / "movement.json", WEB_LIVE.parent / "movement.json"):
            p.write_text(json.dumps(mv, indent=2))
        print(f"movement: {len(mv['newly_resolved'])} new result(s), "
              f"{len(mv['title_movers'])} title / {len(mv['advance_movers'])} advance movers")
    except Exception as e:  # noqa: BLE001
        print(f"warn: movement skipped ({e})", file=sys.stderr)
    try:  # refresh the README's "top of the board" line + stamp; best-effort
        from src.update import readme_summary
        if readme_summary.update_readme():
            print("README top-board updated")
    except Exception as e:  # noqa: BLE001
        print(f"warn: README update skipped ({e})", file=sys.stderr)
    MARKER.write_text(" ".join(sorted(played)))
    print(f"update complete {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} "
          f"({len(played)} results in, data {'fresh' if fresh else 'STALE (cached)'})")


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
    main(force="--force" in sys.argv, rebuild="--rebuild" in sys.argv)

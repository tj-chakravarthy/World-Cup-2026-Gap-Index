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

import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.played import played_mask

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"
PRED = REPO / "data" / "predictions"
PROC = REPO / "data" / "processed"
FIXTURES = RAW / "fixtures_2026.csv"
CARDS = RAW / "cards_2026.csv"
MARKER = PRED / ".last_played"
CARDS_MARKER = PRED / ".cards_hash"   # hash of cards at last recompute, so a cards edit re-runs
LIVE = PRED / "predictions_live.json"
SIM = PRED / "simulation.json"
WEB_LIVE = REPO / "web" / "public" / "data" / "predictions_live.json"
LIVE_SIMS = 100_000   # full draw count — the published site number; ~5x slower per update


def played_fixture_ids(fixtures: pd.DataFrame) -> set[str]:
    """The set of fixture_ids marked played, robust to bool/str encodings. Pure."""
    return set(fixtures.loc[played_mask(fixtures["played"]), "fixture_id"])


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


def _should_recompute(*, force: bool, rebuild: bool, artifacts_exist: bool, played: set, last: set,
                      fresh: bool, was_stale: bool, live_covers_kicked_off: bool,
                      cards_changed: bool) -> bool:
    """Whether main() must rebuild the live artifacts. Beyond a new result this also catches the
    stale-banner transitions, a covered fixture passing kickoff, and a fair-play cards edit, so they
    don't silently no-op when the caller didn't pass --force: publish the banner on a fresh feed
    failure, clear it on recovery (was_stale != would-be-stale), drop a now-kicked-off match, and
    pick up committed conduct. Mirrors check()'s recompute signal so the handoff can't drop one. Pure."""
    if force or rebuild or not artifacts_exist:
        return True
    if played != last or live_covers_kicked_off or cards_changed:
        return True
    return was_stale != (not fresh)   # the published stale flag would flip -> republish to reflect it


def main(force: bool = False, rebuild: bool = False) -> None:
    fresh = _refresh_fixtures()
    fixtures = pd.read_csv(FIXTURES)
    played = played_fixture_ids(fixtures)
    last = set(MARKER.read_text().split()) if MARKER.exists() else set()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not _should_recompute(force=force, rebuild=rebuild,
                             artifacts_exist=LIVE.exists() and SIM.exists(),
                             played=played, last=last, fresh=fresh,
                             was_stale=_committed_live_is_stale(),
                             live_covers_kicked_off=_live_covers_kicked_off(now),
                             cards_changed=_cards_changed()):
        print(f"no new results ({len(played)} played) and no stale/kickoff/cards change; nothing to update")
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

    def _live():  # validate, log, THEN publish — nothing goes live un-logged (the §6 guarantee)
        preds = monte_carlo.fixture_wdl(bundle, fixtures)
        preds.to_csv(PROC / "predictions_2026_wdl.csv", index=False)
        artifact = build_live_artifact.build_live(preds, fixtures, bundle.dc, bundle.code2m,
                                                  stale=not fresh)
        # The append-only log backs "every prediction committed before kickoff", so it is a HARD
        # gate, not best-effort: if logging fails the run fails, the cron skips its commit (its
        # `if:` implies success()), and an un-logged forecast never ships — better a red run you
        # can see than a silent publish. But the log is never edited, so validate FIRST: a schema
        # failure (e.g. an unpinned '@nogit' model_version) must not leave orphan rows for a
        # version the writer then rejects. So validate -> log -> write (write re-checks).
        # log_predictions is idempotent on (model_version, fixture_id), so a retry adds nothing.
        from src.update import prediction_log
        universe = write_predictions.load_fixture_ids()
        write_predictions.validate(artifact, universe)
        print(f"prediction_log: +{prediction_log.log_predictions(artifact)} new rows")
        write_predictions.write(artifact, LIVE, fixture_universe=universe)
        WEB_LIVE.parent.mkdir(parents=True, exist_ok=True)
        WEB_LIVE.write_text(LIVE.read_text())
        # the two live-model inputs per fixture (Elo + squad value), for the match cards
        mi = json.dumps(build_live_artifact.model_inputs(bundle.indices, fixtures), indent=2)
        for p in (PRED / "model_inputs.json", WEB_LIVE.parent / "model_inputs.json"):
            p.write_text(mi)

    def _cards():  # validate the manual fair-play cards before they feed the sim's Art. 13 tiebreaker
        # if any cards are loaded they must be well-formed AND complete (every played group match,
        # both teams) — load_conduct scores a missing row as zero, which would silently bias the
        # standings. A red run beats a quietly wrong tiebreaker. Empty/absent cards = the zero default.
        if not CARDS.exists():
            return
        df = pd.read_csv(CARDS)
        if df.empty:
            return
        from src.pipeline.validate_cards import TEAM_CODES, validate_cards
        validate_cards(df, set(pd.read_csv(TEAM_CODES)["fifa_code"]), fixtures)

    _step("cards", _cards)
    _step("simulate", _sim)
    _step("live_artifact", _live)
    # track_record is a HARD gate: it's the public accountability receipt, and the cron commit is
    # atomic (the commit step's `if:` implies success(), so a failed run commits nothing). Publish
    # the whole consistent set — forecast, sim, receipts — or nothing; never a fresh forecast beside
    # stale receipts (worse than a red cron once the site is public). It's pure derivation from the
    # log written above (also hard), so it rarely fails; when it does, a red run is the right signal
    # and the next run regenerates it (the log is idempotent). movement + README below stay
    # best-effort: a cosmetic panel / stamp that lags one cycle is not an accountability claim and
    # must not block the forecast.
    def _track():  # public track-record receipts (resolved predictions vs results), from the log
        import json
        from src.update import prediction_log
        # backfill the immutable locked pre-kickoff calls (idempotent) so the receipts also
        # cover matches played before the live model came online, attributed to the lock.
        prediction_log.import_locked_receipts()
        art = prediction_log.track_record_artifact(prediction_log.load_log(), fixtures)
        for p in (PRED / "track_record.json", WEB_LIVE.parent / "track_record.json"):
            p.write_text(json.dumps(art, indent=2))
        print(f"track_record: {art['n_resolved']} resolved / {art['n_receipts']} receipts "
              f"({art['n_audit_rows']} audit rows)")

    _step("track_record", _track)
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
    CARDS_MARKER.write_text(_cards_hash())   # record the cards we just used, so next poll is idle
    print(f"update complete {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} "
          f"({len(played)} results in, data {'fresh' if fresh else 'STALE (cached)'})")


def _committed_live_is_stale() -> bool:
    """Did the last published run flag its fixture feed stale? Read from the committed
    predictions_live.json — its own stale bit is the cross-run state (CI runners are
    ephemeral, so no separate counter file would survive between polls)."""
    if not LIVE.exists():
        return False
    try:
        import json
        art = json.loads(LIVE.read_text())
        return any(s.get("stale") for s in art.get("sources", []))
    except Exception:  # noqa: BLE001 - a missing/garbled file just means "not known stale"
        return False


def _live_covers_kicked_off(now: str) -> bool:
    """True if the committed live artifact still PREDICTS a fixture whose kickoff has passed.
    build_live drops post-kickoff fixtures when it runs, but the cheap gate must notice kickoff
    on its own — it's deterministic (no feed needed), whereas the result landing lags. Otherwise a
    pre-match forecast for an in-progress or finished match keeps showing until the slow feed
    catches up. ISO-8601 Z is fixed-width UTC, so the string compare is chronological."""
    if not LIVE.exists():
        return False
    try:
        import json
        art = json.loads(LIVE.read_text())
        return any(str(p.get("kickoff_utc", "")) <= now for p in art.get("predictions", []))
    except Exception:  # noqa: BLE001 - a missing/garbled file just means "nothing to drop"
        return False


def _cards_hash() -> str:
    """Content hash of the manual fair-play cards file ('' if absent)."""
    return hashlib.sha256(CARDS.read_bytes()).hexdigest() if CARDS.exists() else ""


def _cards_changed() -> bool:
    """Did cards_2026.csv change since the last recompute? The result/freshness/kickoff signals
    don't notice a committed cards edit on their own, so without this the simulator's conduct would
    never pick it up (docs/external_pinger.md's 'next cron run' claim). The hash is stored in a
    committed marker, so it survives ephemeral runners."""
    marked = CARDS_MARKER.read_text().strip() if CARDS_MARKER.exists() else ""
    return _cards_hash() != marked


def check() -> int:
    """Cheap pre-step the cron runs every poll. Exit code: 10 = recompute, 0 = idle, 1 = fail.

    A fixture-refresh failure is never silent (PLAN §6): the first one recomputes so the run
    republishes with stale=True and the site's banner fires (a stale heartbeat); a SECOND
    consecutive failure (the committed artifact is already stale) fails the cron so the outage
    is visible to me, not just the public. On recovery, a still-stale artifact is recomputed to
    clear the flag."""
    fresh = _refresh_fixtures()
    was_stale = _committed_live_is_stale()
    if not fresh and was_stale:
        print("fixture feed down across consecutive polls — failing the run (stale already "
              "published; this escalates it)", file=sys.stderr)
        return 1
    played = played_fixture_ids(pd.read_csv(FIXTURES))
    last = set(MARKER.read_text().split()) if MARKER.exists() else set()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    kicked_off = _live_covers_kicked_off(now)
    cards_changed = _cards_changed()
    # recompute on: a new result, missing artifacts, a fresh feed failure (publish the stale
    # heartbeat), recovery from a stale state (clear the banner), a covered fixture whose kickoff
    # has passed (drop the now-in-progress/finished match), OR an edit to the manual fair-play
    # cards (so committed conduct actually reaches the simulator).
    changed = (played != last or not (LIVE.exists() and SIM.exists())
               or not fresh or (fresh and was_stale) or kicked_off or cards_changed)
    print(f"played={len(played)} marker={len(last)} fresh={fresh} was_stale={was_stale} "
          f"kicked_off={kicked_off} cards_changed={cards_changed} -> "
          f"{'recompute' if changed else 'idle'}")
    return 10 if changed else 0


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(check())  # 10 = recompute, 0 = idle, 1 = fail (sustained feed outage)
    main(force="--force" in sys.argv, rebuild="--rebuild" in sys.argv)

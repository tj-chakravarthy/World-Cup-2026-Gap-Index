"""Stage-0 lock builder: thin Dixon-Coles (C) + Elo-sigmoid (E) -> the locked
prediction artifact (PLAN.md Build Order Stage 0, tasks 4 + 6).

Reads the committed Stage-0 spine (fixtures, results, elo, team_codes), fits the
thin goals model on pre-tournament internationals, and predicts every fixture
that is unplayed AND has both teams known at lock time. Fixtures that have
kicked off are excluded (can't be predicted honestly); knockout fixtures whose
teams aren't determined yet are pending. Writes through write_predictions, which
enforces the artifact invariants and refuses to overwrite an existing lock.

Headline W/D/L + scorelines are Dixon-Coles; the Elo baseline rides along in
each prediction's `members` for audit. Run: python -m src.pipeline.build_lock
"""

from __future__ import annotations

import csv
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from src.models import dixon_coles
from src.models.elo_baseline import elo_wdl
from src.pipeline import write_predictions
from src.pipeline.team_codes import TeamCodes

REPO = Path(__file__).resolve().parents[2]
FIXTURES_CSV = REPO / "data" / "raw" / "fixtures_2026.csv"
RESULTS_CSV = REPO / "data" / "raw" / "match_results.csv"
ELO_CSV = REPO / "data" / "raw" / "elo_national_current.csv"
PRED_DIR = REPO / "data" / "predictions"

TOURNAMENT = "FIFA World Cup 26"
TOURNAMENT_START = "2026-06-11"  # exclude WC2026 + any future-dated rows from the fit
BASE_DRAW = 0.231                # field draw rate, match_results since 2018


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _ts(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def load_fit_matches(path: Path = RESULTS_CSV) -> list[tuple]:
    """(date, home, away, home_goals, away_goals, neutral) for every result
    strictly before the tournament with valid integer scores."""
    out = []
    for r in csv.DictReader(path.open()):
        d = r["date"]
        if not d or d >= TOURNAMENT_START:
            continue
        try:
            hg, ag = int(r["home_score"]), int(r["away_score"])
        except (ValueError, KeyError):
            continue
        out.append((d, r["home_team"], r["away_team"], hg, ag,
                    r["neutral"].strip().upper() == "TRUE"))
    return out


def load_elo(path: Path = ELO_CSV) -> dict[str, float]:
    """eloratings team_name -> current Elo."""
    return {r["team_name"]: float(r["elo"]) for r in csv.DictReader(path.open())}


def partition(fixtures: list[dict], locked_at: datetime) -> tuple[list, list, list]:
    """Split fixtures into (covered, excluded_played, pending_undetermined).
    covered = not kicked off and both teams known; excluded = played or kicked
    off by lock time; pending = teams not yet determined (knockouts)."""
    covered, excluded, pending = [], [], []
    for r in fixtures:
        known = bool(r["home_code"]) and bool(r["away_code"])
        kicked_off = r["played"].strip() == "True" or _dt(r["kickoff_utc"]) <= locked_at
        if kicked_off:
            excluded.append(r)
        elif known:
            covered.append(r)
        else:
            pending.append(r)
    return covered, excluded, pending


def build_predictions(covered: list[dict], model: dixon_coles.DCModel,
                      elo_by_name: dict[str, float], tc: TeamCodes) -> list[dict]:
    fifa_to_martj42 = {v: k for k, v in tc.martj42_to_fifa.items()}
    fifa_to_elo = {v: k for k, v in tc.eloratings_to_fifa.items()}
    preds = []
    for r in covered:
        t1, t2 = r["home_code"], r["away_code"]
        dc = model.predict(fifa_to_martj42[t1], fifa_to_martj42[t2], neutral=True)
        e = elo_wdl(elo_by_name[fifa_to_elo[t1]], elo_by_name[fifa_to_elo[t2]], BASE_DRAW)
        preds.append({
            "fixture_id": r["fixture_id"],
            "stage": r["stage"],
            "kickoff_utc": r["kickoff_utc"],
            "team1": t1,
            "team2": t2,
            "model_source": "locked_minimal",
            "wdl": dc["wdl"],
            "scorelines": dc["scorelines"],
            "members": {"C": dc["wdl"], "E": e},
            "conformal_set": None,
            "stale": False,
        })
    return preds


def _model_version() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                             capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        sha = "unknown"
    return f"stage0-EC-thin@{sha}"


def build_artifact(locked_at: datetime, covered, excluded, pending,
                   preds: list[dict], elo_as_of: str) -> dict:
    ts = _ts(locked_at)
    ids = lambda rows: sorted(r["fixture_id"] for r in rows)
    return {
        "schema_version": "1.0",
        "kind": "locked",
        "model_version": _model_version(),
        "generated_at": ts,
        "locked_at_utc": ts,
        "tournament": TOURNAMENT,
        "coverage": {
            "covered_fixture_ids": ids(covered),
            "excluded_played_fixture_ids": ids(excluded),
            "pending_undetermined_fixture_ids": ids(pending),
            "lock_basis": "unplayed and both teams known at locked_at_utc",
        },
        "sources": [
            {"name": "fixtures", "as_of": ts, "stale": False},
            {"name": "results", "as_of": ts, "stale": False},
            {"name": "elo", "as_of": elo_as_of, "stale": False},
        ],
        "predictions": sorted(preds, key=lambda p: p["fixture_id"]),
    }


def main() -> None:
    locked_at = datetime.now(timezone.utc).replace(microsecond=0)
    fixtures = list(csv.DictReader(FIXTURES_CSV.open()))
    covered, excluded, pending = partition(fixtures, locked_at)

    # clock sanity: a played fixture kicking off after the lock instant means the
    # system clock trails the fixture feed — refuse rather than mislabel.
    for r in fixtures:
        if r["played"].strip() == "True" and _dt(r["kickoff_utc"]) > locked_at:
            raise SystemExit(f"clock behind feed ({r['fixture_id']} kicks off after lock); not locking")

    model = dixon_coles.fit(load_fit_matches())
    elo_by_name = load_elo()
    tc = TeamCodes.load()
    preds = build_predictions(covered, model, elo_by_name, tc)

    elo_as_of = next(csv.DictReader(ELO_CSV.open()))["as_of"] + "T00:00:00Z"
    artifact = build_artifact(locked_at, covered, excluded, pending, preds, elo_as_of)

    PRED_DIR.mkdir(parents=True, exist_ok=True)
    out = PRED_DIR / f"predictions_locked_{locked_at:%Y%m%d}.json"
    write_predictions.write(artifact, out, fixture_universe=write_predictions.load_fixture_ids())
    print(f"locked {len(preds)} fixtures -> {out.relative_to(REPO)}")
    print(f"  covered={len(covered)} excluded={len(excluded)} pending={len(pending)} rho={model.rho:.4f}")


if __name__ == "__main__":
    main()

"""Append-only prediction audit log (PLAN.md §6, §7.2) — the receipts behind /track-record.

Logs what the model predicted for each fixture BEFORE it was played, then scores
those predictions against the realised result. Append-only: a logged (model_version,
fixture_id) pair is never rewritten or deleted, so the track record can't be tuned
after the fact. Re-runs are idempotent on that key.

Pre-kickoff by construction: log_predictions drops any row whose kickoff has already passed
(a lagging score feed can leave a kicked-off fixture marked unplayed and re-included), so new
appends are guaranteed before-kickoff. Because the log is never rewritten, one earlier
post-kickoff re-log predates that guard — WC26-M013 logged 2026-06-15T23:15Z for a 22:00Z
kickoff. It is kept as honest history rather than edited out: scoring ignores it
(latest_per_fixture keeps only the latest PRE-kickoff row per fixture), and every row carries
logged_at + kickoff_utc, so any reader can verify each prediction's before/after-kickoff
status directly from the raw file.

Columns are the immutable receipt fields only — the per-prediction artifact fields
(docs/artifact_schema.md) flattened to one row. Outcomes are NOT stored; resolve() joins them
from the played fixtures (in memory) when building the track record.
pandas + pyarrow (parquet).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.played import played_mask

REPO = Path(__file__).resolve().parents[2]
LOG_PATH = REPO / "data" / "predictions" / "prediction_log.parquet"

# what every log row carries; load_log returns an empty frame with exactly these
LOG_COLUMNS = [
    "logged_at",
    "model_version",
    "model_source",
    "fixture_id",
    "kickoff_utc",
    "team1",
    "team2",
    "p_team1",
    "p_draw",
    "p_team2",
    "top_score",
    "top_score_p",
]

# idempotency key — one logged prediction per model identity per fixture
KEY = ["model_version", "fixture_id"]

# receipt attribution: the live match model vs the immutable pre-kickoff lock (a thin stage-0
# model). The committed locked artifact(s) carry pre-registered, pre-kickoff calls.
_MODEL_LABEL = {"live_full": "live", "locked_minimal": "pre-kickoff (locked)"}
LOCKED_GLOB = "predictions_locked_*.json"


def _now_iso() -> str:
    """UTC now, ISO-8601 with trailing Z (matches the artifact's generated_at)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _top_score(scorelines: list[dict]) -> tuple[str | None, float | None]:
    """Highest-p scoreline as (label, p). Argmax rather than trusting sort order."""
    if not scorelines:
        return None, None
    best = max(scorelines, key=lambda s: s["p"])
    return best["score"], float(best["p"])


def _artifact_rows(artifact: dict, logged_at: str | None = None) -> pd.DataFrame:
    """Flatten an artifact's predictions[] to log rows (model_version from top level).

    logged_at defaults to now (a live append); pass the artifact's lock instant to backfill the
    locked pre-kickoff file, so its rows carry the time they were actually committed (before
    those kickoffs) rather than now (after them)."""
    model_version = artifact["model_version"]
    logged_at = logged_at or _now_iso()
    rows = []
    for p in artifact["predictions"]:
        wdl = p["wdl"]
        top_score, top_score_p = _top_score(p.get("scorelines") or [])
        rows.append(
            {
                "logged_at": logged_at,
                "model_version": model_version,
                "model_source": p["model_source"],
                "fixture_id": p["fixture_id"],
                "kickoff_utc": p["kickoff_utc"],
                "team1": p["team1"],
                "team2": p["team2"],
                "p_team1": float(wdl["team1"]),
                "p_draw": float(wdl["draw"]),
                "p_team2": float(wdl["team2"]),
                "top_score": top_score,
                "top_score_p": top_score_p,
            }
        )
    return pd.DataFrame(rows, columns=LOG_COLUMNS)


def load_log(log_path: Path = LOG_PATH) -> pd.DataFrame:
    """The full log; empty frame with LOG_COLUMNS if the file doesn't exist yet."""
    log_path = Path(log_path)
    if not log_path.exists():
        return pd.DataFrame(columns=LOG_COLUMNS)
    return pd.read_parquet(log_path)


def log_predictions(artifact: dict, log_path: Path = LOG_PATH, logged_at: str | None = None) -> int:
    """Append one row per prediction not already logged on (model_version, fixture_id).

    Idempotent: re-running the same artifact appends nothing; a new model_version logs
    fresh even for the same fixtures. Returns the number of rows appended. logged_at overrides
    the stamp (lock instant for the locked backfill); the pre-kickoff drop is relative to it.
    """
    log_path = Path(log_path)
    new = _artifact_rows(artifact, logged_at)
    # pre-kickoff only (audit-trail integrity): drop any row whose kickoff already passed — a
    # lagging feed can leave a kicked-off fixture marked unplayed, and its genuine pre-kickoff
    # prediction is already logged. ISO-8601 Z is fixed-width UTC, so the string compare holds.
    new = new[new["kickoff_utc"] > new["logged_at"]]
    existing = load_log(log_path)

    if not existing.empty:
        seen = set(map(tuple, existing[KEY].itertuples(index=False, name=None)))
        mask = [tuple(t) not in seen for t in new[KEY].itertuples(index=False, name=None)]
        new = new[mask]

    if new.empty:
        return 0

    out = new if existing.empty else pd.concat([existing, new], ignore_index=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(log_path, index=False)
    return len(new)


def import_locked_receipts(log_path: Path = LOG_PATH, pred_dir: Path | None = None) -> int:
    """Backfill the committed locked artifact(s) into the log as pre-registered receipts.

    The locked file is the immutable pre-kickoff prediction (model_source 'locked_minimal');
    its calls were committed at locked_at_utc — before those kickoffs — but never lived in the
    append-only live log, so the public track record omitted matches played before the live model
    came online. Log them at their lock instant (not now), so they count as the honest pre-kickoff
    receipts they are. Idempotent on (model_version, fixture_id). Returns rows added."""
    import json
    pred_dir = Path(pred_dir) if pred_dir else LOG_PATH.parent
    added = 0
    for p in sorted(pred_dir.glob(LOCKED_GLOB)):
        art = json.loads(p.read_text())
        added += log_predictions(art, log_path, logged_at=art["locked_at_utc"])
    return added


def resolve(log: pd.DataFrame, fixtures: pd.DataFrame) -> pd.DataFrame:
    """Join each logged prediction to its realised result. PURE (no IO).

    Adds actual_home, actual_away, actual_outcome (0 team1 win / 1 draw / 2 team2 win,
    from team1's = home_code's perspective), called (argmax of the wdl == outcome), and
    exact_score_hit (top_score == realised "H-A"). Unplayed fixtures stay unresolved
    (NaN/None) — outcome is null until played, per the schema contract.
    """
    out = log.copy()

    played = fixtures[played_mask(fixtures["played"])]
    res = played.set_index("fixture_id")[["home_score", "away_score"]]
    mapping = {fid: (h, a) for fid, (h, a) in res.iterrows()}

    actual_home, actual_away, actual_outcome = [], [], []
    called, exact = [], []
    for r in out.itertuples(index=False):
        hit = mapping.get(r.fixture_id)
        if hit is None or pd.isna(hit[0]) or pd.isna(hit[1]):
            actual_home.append(pd.NA)
            actual_away.append(pd.NA)
            actual_outcome.append(pd.NA)
            called.append(pd.NA)
            exact.append(pd.NA)
            continue
        h, a = int(hit[0]), int(hit[1])
        oc = 0 if h > a else (1 if h == a else 2)
        probs = [r.p_team1, r.p_draw, r.p_team2]
        pred = int(max(range(3), key=lambda k: probs[k]))
        actual_home.append(h)
        actual_away.append(a)
        actual_outcome.append(oc)
        called.append(bool(pred == oc))
        exact.append(bool(r.top_score == f"{h}-{a}"))

    out["actual_home"] = pd.array(actual_home, dtype="Int64")
    out["actual_away"] = pd.array(actual_away, dtype="Int64")
    out["actual_outcome"] = pd.array(actual_outcome, dtype="Int64")
    out["called"] = pd.array(called, dtype="boolean")
    out["exact_score_hit"] = pd.array(exact, dtype="boolean")
    return out


def latest_per_fixture(log: pd.DataFrame) -> pd.DataFrame:
    """Keep the latest prediction *logged strictly before kickoff* per (model_source,
    fixture_id) — the one genuinely standing when the ball rolled.

    The append-only log can carry post-kickoff rows: a lagging score feed leaves a fixture
    'unplayed', so build_live re-logs it after kickoff. Scoring those would break the
    'committed before kickoff' guarantee the site makes, so they're dropped — and a fixture
    with no pre-kickoff row at all is excluded entirely (no honest receipt exists). ISO-8601
    Z timestamps are fixed-width UTC, so the string compare is chronological. PURE."""
    if log.empty:
        return log
    pre = log[log["logged_at"] < log["kickoff_utc"]]
    return (pre.sort_values("logged_at")
               .drop_duplicates(["model_source", "fixture_id"], keep="last")
               .reset_index(drop=True))


def _brier(rows: pd.DataFrame) -> float:
    """Multiclass Brier: mean over rows of sum_k (p_k - onehot_k)^2 (lower is better)."""
    total = 0.0
    for r in rows.itertuples(index=False):
        oc = int(r.actual_outcome)
        probs = [r.p_team1, r.p_draw, r.p_team2]
        total += sum((probs[k] - (1.0 if k == oc else 0.0)) ** 2 for k in range(3))
    return total / len(rows)


def _summary(logged: pd.DataFrame, resolved: pd.DataFrame) -> dict:
    """Block of metrics for one slice (a model_source or the overall set)."""
    n_logged = len(logged)
    n_resolved = len(resolved)
    if n_resolved == 0:
        return {
            "n_logged": n_logged,
            "n_resolved": 0,
            "called": {"count": 0, "rate": None},
            "brier": None,
            "exact_score_hits": {"count": 0, "rate": None, "note": "for fun"},
        }
    called_n = int(resolved["called"].sum())
    exact_n = int(resolved["exact_score_hit"].sum())
    return {
        "n_logged": n_logged,
        "n_resolved": n_resolved,
        "called": {"count": called_n, "rate": called_n / n_resolved},
        "brier": _brier(resolved),
        "exact_score_hits": {
            "count": exact_n,
            "rate": exact_n / n_resolved,
            "note": "for fun",
        },
    }


def track_record(log: pd.DataFrame, fixtures: pd.DataFrame) -> dict:
    """Scored track record over resolved (played) predictions, per model_source + overall.

    PURE. Scored on the standing prediction per fixture (latest model_version), so a
    version bump doesn't double-count. Unresolved rows are excluded from the resolved
    metrics (Brier, called rate, exact hits) but still counted in n_logged.
    """
    log = latest_per_fixture(log)
    resolved_all = resolve(log, fixtures)
    is_resolved = resolved_all["actual_outcome"].notna()

    out: dict = {"by_model_source": {}}
    for src in sorted(log["model_source"].unique()) if not log.empty else []:
        logged_src = resolved_all[resolved_all["model_source"] == src]
        out["by_model_source"][src] = _summary(
            logged_src, logged_src[logged_src["actual_outcome"].notna()]
        )
    out["overall"] = _summary(resolved_all, resolved_all[is_resolved])
    return out


def track_record_artifact(log: pd.DataFrame, fixtures: pd.DataFrame) -> dict:
    """The receipts for the site: every RESOLVED prediction — what was called before kickoff
    vs the actual result — plus the committed/resolved counts. The scored aggregates (Brier,
    called rate) are deliberately NOT included while the live sample is tiny; the model's test
    is the §4.5 backtest, surfaced as context in the site copy. PURE.
    """
    # n_audit_rows: the full append-only log (re-logs across model versions). n_receipts below:
    # the standing pre-kickoff receipts actually shown (one per match). The two differ, so name them.
    n_audit_rows = int(len(log))
    standing = latest_per_fixture(log)
    if standing.empty:
        return {"generated_at": _now_iso(), "n_receipts": 0, "n_audit_rows": n_audit_rows,
                "n_resolved": 0, "resolved": []}
    # one receipt per match: prefer the live model's call, else the pre-registered locked one
    # (so matches played before the live model went online still show, attributed to the lock).
    pref = standing["model_source"].map(lambda s: 0 if s == "live_full" else 1)
    one = (standing.assign(_pref=pref).sort_values("_pref")
                   .drop_duplicates("fixture_id", keep="first").drop(columns="_pref"))
    resolved = resolve(one, fixtures)
    res = resolved[resolved["actual_outcome"].notna()].sort_values("kickoff_utc")
    rows = [
        {
            "fixture_id": r.fixture_id,
            "kickoff_utc": r.kickoff_utc,
            "team1": r.team1,
            "team2": r.team2,
            "model": _MODEL_LABEL.get(r.model_source, r.model_source),
            "p_team1": round(float(r.p_team1), 4),
            "p_draw": round(float(r.p_draw), 4),
            "p_team2": round(float(r.p_team2), 4),
            "actual": f"{int(r.actual_home)}-{int(r.actual_away)}",
            "outcome": int(r.actual_outcome),   # 0 team1 win / 1 draw / 2 team2 win
            "called": bool(r.called),
            "top_score": r.top_score,
            "exact_hit": bool(r.exact_score_hit) if pd.notna(r.exact_score_hit) else False,
        }
        for r in res.itertuples(index=False)
    ]
    return {
        "generated_at": _now_iso(),
        "n_receipts": int(len(one)),       # standing pre-kickoff receipts (one per match)
        "n_audit_rows": n_audit_rows,      # total append-only log rows (larger)
        "n_resolved": int(len(res)),
        "resolved": rows,
    }

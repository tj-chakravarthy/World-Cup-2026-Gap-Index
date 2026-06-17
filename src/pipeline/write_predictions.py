"""Prediction-artifact writer + schema validator (Stage 0).

Enforces the invariants in `docs/artifact_schema.md` before anything touches
disk. The locked file can never be re-issued, so the cheap insurance is to
refuse to write a malformed or invariant-breaking artifact at all — and to
refuse to clobber an existing locked file.

Stdlib only by design: the artifact is JSON and the checks are arithmetic on
it, so validation stays out of the modelling stack and runs in plain CI.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = "1.0"
WDL_TOL = 1e-6  # |sum(wdl) - 1| must stay under this

_TOP_KEYS = {
    "schema_version", "kind", "model_version", "generated_at", "locked_at_utc",
    "tournament", "coverage", "sources", "predictions",
}
_COVERAGE_SETS = (
    "covered_fixture_ids",
    "excluded_played_fixture_ids",
    "pending_undetermined_fixture_ids",
)
_MODEL_SOURCE = {"locked": "locked_minimal", "live": "live_full"}

_FIXTURES_CSV = Path(__file__).resolve().parents[2] / "data" / "raw" / "fixtures_2026.csv"


class SchemaError(ValueError):
    """Artifact violates docs/artifact_schema.md."""


def load_fixture_ids(path: str | Path = _FIXTURES_CSV) -> set[str]:
    """The canonical fixture-id universe (all 104), for the completeness check
    (invariant 6). Pass to validate()/write() so a locked file can't drop a
    fixture and still pass."""
    with open(path, newline="") as f:
        return {row["fixture_id"] for row in csv.DictReader(f)}


def _utc(value: str, field: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as e:
        raise SchemaError(f"{field}: not an ISO-8601 timestamp: {value!r}") from e


def validate(artifact: dict, fixture_universe: set[str] | None = None) -> None:
    """Raise SchemaError if `artifact` breaks any documented invariant. When
    `fixture_universe` is given (the canonical fixture-id set), also enforce that
    the three coverage sets together account for exactly it — no omitted
    fixtures, no unknown ids (invariant 6)."""
    missing = _TOP_KEYS - artifact.keys()
    if missing:
        raise SchemaError(f"missing top-level keys: {sorted(missing)}")
    if artifact["schema_version"] != SCHEMA_VERSION:
        raise SchemaError(f"schema_version must be {SCHEMA_VERSION!r}")

    kind = artifact["kind"]
    if kind not in _MODEL_SOURCE:
        raise SchemaError(f"kind must be 'locked' or 'live', got {kind!r}")

    # model_version must be pinned to a real commit — an unresolved git sha ('@nogit') makes the
    # audit log unidentifiable (and, since the log dedupes on model_version, can drop re-logs).
    if str(artifact["model_version"]).endswith("@nogit"):
        raise SchemaError(
            f"model_version is unpinned ({artifact['model_version']!r}) — the build couldn't "
            "resolve the git sha; refusing to publish an unidentifiable artifact"
        )

    generated_at = _utc(artifact["generated_at"], "generated_at")

    cov = artifact["coverage"]
    sets = {name: set(cov.get(name, [])) for name in _COVERAGE_SETS}
    for name in _COVERAGE_SETS:
        ids = cov.get(name, [])
        if len(ids) != len(set(ids)):
            raise SchemaError(f"coverage.{name} has duplicate ids")
    # pairwise disjoint (invariant 5)
    names = list(_COVERAGE_SETS)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            overlap = sets[a] & sets[b]
            if overlap:
                raise SchemaError(f"coverage {a} and {b} overlap: {sorted(overlap)}")

    preds = artifact["predictions"]
    pred_ids = [p["fixture_id"] for p in preds]
    if len(pred_ids) != len(set(pred_ids)):
        raise SchemaError("duplicate fixture_id in predictions")
    # exactly one prediction per covered id, none for excluded/pending (invariant 5)
    if set(pred_ids) != sets["covered_fixture_ids"]:
        raise SchemaError(
            "predictions must match covered_fixture_ids exactly "
            f"(only_in_covered={sorted(sets['covered_fixture_ids'] - set(pred_ids))}, "
            f"only_in_predictions={sorted(set(pred_ids) - sets['covered_fixture_ids'])})"
        )

    # invariant 6: the three sets together account for every fixture, no extras
    if fixture_universe is not None:
        union = (sets["covered_fixture_ids"] | sets["excluded_played_fixture_ids"]
                 | sets["pending_undetermined_fixture_ids"])
        missing = fixture_universe - union
        unknown = union - fixture_universe
        if missing:
            raise SchemaError(
                f"coverage omits {len(missing)} fixture(s) — the three sets must "
                f"account for every fixture (invariant 6): {sorted(missing)[:10]}"
            )
        if unknown:
            raise SchemaError(
                f"coverage references unknown fixture ids (invariant 6): {sorted(unknown)}"
            )

    if kind == "locked":
        locked_at = artifact["locked_at_utc"]
        if locked_at is None:
            raise SchemaError("locked file must set locked_at_utc (invariant 1)")
        locked_at = _utc(locked_at, "locked_at_utc")
        if locked_at > generated_at:
            raise SchemaError("locked_at_utc must be <= generated_at (invariant 1)")
    else:
        if artifact["locked_at_utc"] is not None:
            raise SchemaError("live file must set locked_at_utc to null")
        locked_at = None

    for p in preds:
        fx = p["fixture_id"]
        if p["model_source"] != _MODEL_SOURCE[kind]:
            raise SchemaError(
                f"{fx}: model_source must be {_MODEL_SOURCE[kind]!r} in a {kind} file"
            )
        wdl = p["wdl"]
        for outcome in ("team1", "draw", "team2"):
            pv = wdl[outcome]
            if not 0.0 <= pv <= 1.0:
                raise SchemaError(f"{fx}: wdl[{outcome}]={pv} out of [0,1] (invariant 4)")
        s = wdl["team1"] + wdl["draw"] + wdl["team2"]
        if abs(s - 1.0) > WDL_TOL:
            raise SchemaError(f"{fx}: wdl sums to {s}, not 1 (invariant 4)")
        for sc in p["scorelines"]:
            if not 0.0 <= sc["p"] <= 1.0:
                raise SchemaError(f"{fx}: scoreline p out of [0,1]: {sc}")
        # core invariant: nothing already kicked off may be predicted. Locked files check
        # against locked_at_utc; LIVE files against generated_at (build time) — so a live
        # artifact can never publish a post-kickoff prediction even if a lagging feed left the
        # fixture marked unplayed. It belongs in excluded, and is logged pre-kickoff or not at all.
        cutoff = locked_at if locked_at is not None else generated_at
        ref = "locked_at_utc" if locked_at is not None else "generated_at"
        if _utc(p["kickoff_utc"], f"{fx}.kickoff_utc") <= cutoff:
            raise SchemaError(
                f"{fx}: kickoff_utc <= {ref} — already kicked off, must be in "
                "excluded_played_fixture_ids, not predicted (invariant 1)"
            )


def write(artifact: dict, path: str | Path,
          fixture_universe: set[str] | None = None) -> Path:
    """Validate then write `artifact` to `path`. A locked file is never allowed
    to overwrite an existing one (invariant 2), and must be checked for coverage
    completeness against the canonical fixture set (invariant 6) — the permanent
    artifact can't be re-issued, so an omitted fixture is unrecoverable."""
    if artifact["kind"] == "locked" and fixture_universe is None:
        raise SchemaError(
            "locked artifact must be validated against the fixture universe "
            "(coverage completeness, invariant 6) — pass load_fixture_ids()"
        )
    validate(artifact, fixture_universe)
    path = Path(path)
    if artifact["kind"] == "locked" and path.exists():
        raise SchemaError(f"refusing to rewrite locked file: {path} (invariant 2)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2) + "\n")
    return path

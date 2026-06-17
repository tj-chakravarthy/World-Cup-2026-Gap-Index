"""Prediction-artifact invariants (PLAN.md §0 / docs/artifact_schema.md).

A real, enforced contract: the locked file can't be re-issued, so every
documented invariant gets a failing case here. Stdlib + pytest only — no
modelling stack — so it runs in plain CI alongside the tiebreaker suite.
"""

import json

import pytest

from src.pipeline.write_predictions import SchemaError, validate, write


def _locked() -> dict:
    """A minimal valid locked artifact. Each test mutates a fresh copy."""
    return {
        "schema_version": "1.0",
        "kind": "locked",
        "model_version": "stage0-AC-thin@deadbee",
        "locked_at_utc": "2026-06-13T08:00:00Z",
        "generated_at": "2026-06-13T08:00:00Z",
        "tournament": "FIFA World Cup 26",
        "coverage": {
            "covered_fixture_ids": ["WC26-M037"],
            "excluded_played_fixture_ids": ["WC26-M001"],
            "pending_undetermined_fixture_ids": ["WC26-R32-01"],
            "lock_basis": "unplayed and both teams known at locked_at_utc",
        },
        "sources": [{"name": "fixtures", "as_of": "2026-06-12T20:00:00Z", "stale": False}],
        "predictions": [
            {
                "fixture_id": "WC26-M037",
                "stage": "group",
                "kickoff_utc": "2026-06-20T19:00:00Z",
                "team1": "BRA",
                "team2": "SWE",
                "model_source": "locked_minimal",
                "wdl": {"team1": 0.52, "draw": 0.26, "team2": 0.22},
                "scorelines": [{"score": "1-0", "p": 0.121}],
                "conformal_set": None,
                "stale": False,
            }
        ],
    }


def _universe(a: dict) -> set[str]:
    """The fixture-id set the artifact's coverage should exactly cover."""
    c = a["coverage"]
    return (set(c["covered_fixture_ids"]) | set(c["excluded_played_fixture_ids"])
            | set(c["pending_undetermined_fixture_ids"]))


def test_valid_locked_passes():
    validate(_locked())


def test_write_roundtrips_and_validates(tmp_path):
    a = _locked()
    path = write(a, tmp_path / "predictions_locked_20260613.json", _universe(a))
    validate(json.loads(path.read_text()))


def test_locked_file_never_overwritten(tmp_path):
    a = _locked()
    p = tmp_path / "predictions_locked_20260613.json"
    write(a, p, _universe(a))
    with pytest.raises(SchemaError, match="rewrite locked"):
        write(a, p, _universe(a))


def test_locked_write_requires_fixture_universe(tmp_path):
    # the permanent artifact can't skip the completeness check
    with pytest.raises(SchemaError, match="fixture universe"):
        write(_locked(), tmp_path / "predictions_locked_20260613.json")


def test_coverage_completeness_passes_for_full_universe():
    a = _locked()
    validate(a, _universe(a))


def test_coverage_completeness_rejects_omitted_fixture():
    a = _locked()
    # a fixture that exists but sits in none of the three sets
    with pytest.raises(SchemaError, match="omits"):
        validate(a, _universe(a) | {"WC26-M999"})


def test_coverage_completeness_rejects_unknown_id():
    a = _locked()
    # coverage lists the pending id, but it's not in the universe
    with pytest.raises(SchemaError, match="unknown fixture"):
        validate(a, {"WC26-M037", "WC26-M001"})


def test_locked_at_after_generated_rejected():
    a = _locked()
    a["generated_at"] = "2026-06-13T07:58:00Z"  # before the lock instant
    with pytest.raises(SchemaError, match="locked_at_utc must be <= generated_at"):
        validate(a)


def test_predicting_already_played_fixture_rejected():
    a = _locked()
    a["predictions"][0]["kickoff_utc"] = "2026-06-13T07:00:00Z"  # before lock
    with pytest.raises(SchemaError, match="already kicked off"):
        validate(a)


def test_live_predicting_post_kickoff_rejected():
    # the live publish gate: a prediction whose kickoff has passed (vs generated_at) is rejected,
    # so a lagging feed can never push a post-kickoff prediction into the live artifact
    a = _locked()
    a["kind"] = "live"
    a["locked_at_utc"] = None
    a["predictions"][0]["model_source"] = "live_full"
    a["predictions"][0]["kickoff_utc"] = "2026-06-13T07:00:00Z"  # before generated_at (08:00)
    with pytest.raises(SchemaError, match="already kicked off"):
        validate(a)


def test_coverage_sets_must_be_disjoint():
    a = _locked()
    a["coverage"]["excluded_played_fixture_ids"] = ["WC26-M037"]  # also covered
    with pytest.raises(SchemaError, match="overlap"):
        validate(a)


def test_predictions_must_match_covered_exactly():
    a = _locked()
    a["coverage"]["covered_fixture_ids"] = ["WC26-M037", "WC26-M038"]  # M038 unpredicted
    with pytest.raises(SchemaError, match="match covered_fixture_ids"):
        validate(a)


def test_wdl_must_sum_to_one():
    a = _locked()
    a["predictions"][0]["wdl"] = {"team1": 0.5, "draw": 0.2, "team2": 0.2}  # 0.9
    with pytest.raises(SchemaError, match="not 1"):
        validate(a)


def test_wdl_components_must_be_in_unit_interval():
    a = _locked()
    # sums to 1 but contains impossible probabilities — must not pass on the sum alone
    a["predictions"][0]["wdl"] = {"team1": 1.2, "draw": -0.2, "team2": 0.0}
    with pytest.raises(SchemaError, match=r"out of \[0,1\]"):
        validate(a)


def test_locked_requires_locked_at_utc():
    a = _locked()
    a["locked_at_utc"] = None
    with pytest.raises(SchemaError, match="must set locked_at_utc"):
        validate(a)


def test_live_must_null_locked_at_and_use_live_source():
    a = _locked()
    a["kind"] = "live"
    a["predictions"][0]["model_source"] = "live_full"
    with pytest.raises(SchemaError, match="must set locked_at_utc to null"):
        validate(a)
    a["locked_at_utc"] = None
    validate(a)  # now a valid live file

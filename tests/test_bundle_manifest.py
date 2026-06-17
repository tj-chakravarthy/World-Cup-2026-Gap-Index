"""Provenance manifest for the committed model bundle (src/pipeline/bundle_manifest.py).

Lets a reviewer verify the binary pickle without the raw scrapes. Build it from a stub bundle +
the committed match_results.csv and check the identity/provenance fields.
"""

import hashlib
import json

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("sklearn")  # bundle_manifest imports match_model, which pulls sklearn

from src.pipeline.bundle_manifest import build_manifest  # noqa: E402


class _StubBundle:
    def __init__(self):
        self.indices = pd.DataFrame({
            "tournament": ["world_cup_2026", "euro_2024", "world_cup_2026"],
            "country_code": ["ESP", "FRA", "BRA"]})
        self.codes = ["FRA", "ESP", "BRA"]
        self.version = 1
        self.n_boot = 25


def test_build_manifest_fields(tmp_path):
    pkl = tmp_path / "model_bundle.pkl"
    pkl.write_bytes(b"stub-bundle-bytes")
    m = build_manifest(_StubBundle(), pkl)

    assert m["bundle"]["version"] == 1 and m["bundle"]["n_boot"] == 25
    assert m["bundle"]["sha256"] == hashlib.sha256(pkl.read_bytes()).hexdigest()
    assert m["bundle"]["bytes"] == len(b"stub-bundle-bytes")

    assert m["model"]["feature_columns"] == ["ELO", "MKT"]          # the live model's inputs
    assert m["model"]["n_teams"] == 3 and m["model"]["teams"] == ["BRA", "ESP", "FRA"]

    # the indexed field (world_cup_2026) is split out from the training targets, so it can't be
    # misread as something the model trained on (a leakage signal)
    assert m["tournaments"]["training_target"] == ["euro_2024"]
    assert m["tournaments"]["prediction_index"] == ["world_cup_2026"]
    # the match corpus is recorded only when the gitignored scrape is present, else null
    assert "n_historical_matches" in m["training"]
    nh = m["training"]["n_historical_matches"]
    assert nh is None or nh > 0

    assert m["source_sha_at_generation"]   # a sha or 'nogit', never empty (and may lag HEAD)
    assert m["manifest_schema_version"] == "1"
    json.dumps(m)                          # must be JSON-serialisable


def test_build_manifest_without_scrape(tmp_path, monkeypatch):
    # a scrape-free checkout (CI, a reviewer's clone): match_results.csv absent -> corpus null,
    # never a crash. fifa_rankings_2026.csv is committed, so RAW must still point at the real dir
    from src.pipeline import bundle_manifest
    monkeypatch.setattr(bundle_manifest, "RAW", tmp_path)  # empty dir: no match_results, no fifa
    pkl = tmp_path / "model_bundle.pkl"
    pkl.write_bytes(b"x")
    m = bundle_manifest.build_manifest(_StubBundle(), pkl)
    assert m["training"]["n_historical_matches"] is None
    assert m["sources"]["match_results_scored_through"] is None
    assert m["bundle"]["sha256"]  # still produced

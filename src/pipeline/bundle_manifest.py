"""Provenance manifest for the committed model bundle (docs/deviations.md).

model_bundle.pkl is a binary built from raw scrapes that stay gitignored. This writes a small
JSON beside it so a reviewer can verify what it is — attesting commit, bundle version, the live
feature columns, the 48-team field, the historical training corpus, source dates, and the
pickle's sha256 — without redistributing the raw data. Regenerated whenever the bundle is saved
(monte_carlo.save_bundle), so it tracks the binary. Derives only from committed files + git.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.models.match_model import PRODUCTION_COLS

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"
BUNDLE_PKL = REPO / "data" / "processed" / "model_bundle.pkl"
WC_START = "2026-06-11"


def _git_sha() -> str:
    sha = os.environ.get("GIT_SHA")
    if sha:
        return sha.strip()[:12]
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                              capture_output=True, text=True).stdout.strip() or "nogit"
    except Exception:  # noqa: BLE001
        return "nogit"


def build_manifest(bundle, pkl_path: Path) -> dict:
    """The manifest dict for `bundle` (the just-built/loaded Bundle) + its pickle at pkl_path."""
    pkl_path = Path(pkl_path)
    results = pd.read_csv(RAW / "match_results.csv")
    pre = results[results["date"].astype(str) < WC_START].dropna(
        subset=["home_score", "away_score"])

    fifa_edition = None
    fifa_csv = RAW / "fifa_rankings_2026.csv"
    if fifa_csv.exists():
        fifa = pd.read_csv(fifa_csv)
        if "edition_date" in fifa.columns and len(fifa):
            fifa_edition = str(fifa["edition_date"].iloc[0])

    codes = sorted(bundle.codes)
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "code_sha": _git_sha(),   # the repo commit attesting this bundle (set at build time)
        "bundle": {
            "file": pkl_path.name,
            "version": int(bundle.version),
            "sha256": hashlib.sha256(pkl_path.read_bytes()).hexdigest(),
            "bytes": pkl_path.stat().st_size,
            "n_boot": int(bundle.n_boot),   # parameter-uncertainty bootstrap bags
        },
        "model": {
            "feature_columns": list(PRODUCTION_COLS),   # the live model's inputs (ELO + MKT)
            "n_teams": len(codes),
            "teams": codes,
        },
        "training": {
            "tournaments": sorted(bundle.indices["tournament"].unique().tolist()),
            "n_historical_matches": int(len(pre)),
            "matches_through": str(pre["date"].max()) if len(pre) else None,
        },
        "sources": {
            "fifa_ranking_edition": fifa_edition,
            "match_results_through": str(results["date"].max()) if len(results) else None,
        },
    }


def write(bundle, pkl_path: Path = BUNDLE_PKL) -> Path:
    """Write the manifest beside the bundle (model_bundle.manifest.json). Returns its path."""
    pkl_path = Path(pkl_path)
    out = pkl_path.with_name(pkl_path.stem + ".manifest.json")
    out.write_text(json.dumps(build_manifest(bundle, pkl_path), indent=2) + "\n")
    return out


def main() -> None:
    from src.models.monte_carlo import BUNDLE_PATH, load_or_build_bundle
    out = write(load_or_build_bundle(), BUNDLE_PATH)
    print(f"bundle manifest -> {out.relative_to(REPO)}")


if __name__ == "__main__":
    main()

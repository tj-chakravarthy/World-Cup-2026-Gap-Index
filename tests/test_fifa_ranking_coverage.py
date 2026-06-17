"""The committed FIFA ranking must cover the whole WC2026 field.

monte_carlo.load_fifa_rankings returns None unless every field team is present, silently
downgrading the Art. 13 final tiebreaker to the Elo-order proxy. fetch_fifa_rankings refuses
to write a partial file; this guards the COMMITTED file directly, in case it's ever regenerated
or hand-edited with a gap. pandas only (no modelling stack), so it runs in plain CI.
"""

from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

_RAW = Path(__file__).resolve().parents[1] / "data" / "raw"


def test_committed_fifa_ranking_covers_the_full_field():
    field = set(pd.read_csv(_RAW / "team_codes.csv")["fifa_code"])
    fifa = set(pd.read_csv(_RAW / "fifa_rankings_2026.csv")["fifa_code"])
    missing = sorted(field - fifa)
    assert not missing, (
        f"committed fifa_rankings_2026.csv covers {len(field) - len(missing)}/{len(field)} of the "
        f"WC2026 field — the Art. 13 tiebreaker would silently fall back to Elo for: {missing}"
    )

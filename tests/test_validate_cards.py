"""Manual cards file validation (src/pipeline/validate_cards.py).

The conduct tiebreaker is fed by a hand-maintained cards_2026.csv; these guard the operator
path so a typo fails loudly instead of skewing the standings. The shipped header-only template
must itself validate (it's the zero-conduct default).
"""

from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

from src.pipeline.validate_cards import validate_cards  # noqa: E402

FIELD = {"ESP", "CRO", "BRA"}
_COLS = ["fixture_id", "team_code", "yellow", "indirect_red", "direct_red", "yellow_and_direct_red"]


def _df(rows):
    return pd.DataFrame(rows, columns=_COLS)


def test_valid_passes():
    validate_cards(_df([("WC26-M001", "ESP", 2, 0, 0, 0), ("WC26-M001", "CRO", 1, 0, 1, 0)]), FIELD)


def test_empty_header_only_passes():
    validate_cards(_df([]), FIELD)


def test_unknown_team_code_rejected():
    with pytest.raises(ValueError, match="unknown team_code"):
        validate_cards(_df([("WC26-M001", "XXX", 1, 0, 0, 0)]), FIELD)


def test_negative_count_rejected():
    with pytest.raises(ValueError, match="non-negative integers"):
        validate_cards(_df([("WC26-M001", "ESP", -1, 0, 0, 0)]), FIELD)


def test_non_integer_count_rejected():
    with pytest.raises(ValueError, match="non-negative integers"):
        validate_cards(_df([("WC26-M001", "ESP", 1.5, 0, 0, 0)]), FIELD)


def test_missing_required_column_rejected():
    with pytest.raises(ValueError, match="missing required column"):
        validate_cards(pd.DataFrame({"team_code": ["ESP"], "yellow": [1]}), FIELD)


def test_no_card_column_rejected():
    with pytest.raises(ValueError, match="card column"):
        validate_cards(pd.DataFrame({"fixture_id": ["WC26-M001"], "team_code": ["ESP"]}), FIELD)


def test_duplicate_fixture_team_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        validate_cards(_df([("WC26-M001", "ESP", 1, 0, 0, 0),
                            ("WC26-M001", "ESP", 2, 0, 0, 0)]), FIELD)


_FX = pd.DataFrame([
    {"fixture_id": "WC26-M001", "stage": "group", "home_code": "ESP", "away_code": "CRO"},
    {"fixture_id": "WC26-R32-01", "stage": "R32", "home_code": "", "away_code": ""},
])


def test_team_must_have_played_the_fixture():
    # BRA is a real field team but didn't play M001 (ESP v CRO) — load_conduct sums by team and
    # ignores fixture_id, so this would otherwise credit the wrong side
    with pytest.raises(ValueError, match="did not play"):
        validate_cards(_df([("WC26-M001", "BRA", 1, 0, 0, 0)]), FIELD, _FX)


def test_non_group_or_unknown_fixture_rejected():
    with pytest.raises(ValueError, match="not a known group fixture"):
        validate_cards(_df([("WC26-R32-01", "ESP", 1, 0, 0, 0)]), FIELD, _FX)
    with pytest.raises(ValueError, match="not a known group fixture"):
        validate_cards(_df([("WC26-M999", "ESP", 1, 0, 0, 0)]), FIELD, _FX)


def test_valid_with_fixtures_passes():
    validate_cards(_df([("WC26-M001", "ESP", 2, 0, 0, 0),
                        ("WC26-M001", "CRO", 1, 0, 1, 0)]), FIELD, _FX)


def test_committed_template_validates():
    p = Path(__file__).resolve().parents[1] / "data" / "raw" / "cards_2026.csv"
    validate_cards(pd.read_csv(p), FIELD)

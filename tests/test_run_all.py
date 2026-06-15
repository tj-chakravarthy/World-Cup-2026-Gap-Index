"""Live orchestrator (PLAN.md §6) — the new-result idempotency key."""

import pytest

pd = pytest.importorskip("pandas")

from src.pipeline.run_all import played_fixture_ids  # noqa: E402


def test_played_fixture_ids_coerces_bool_and_str():
    df = pd.DataFrame({
        "fixture_id": ["A", "B", "C", "D", "E"],
        "played": [True, False, "True", "false", "1"],
    })
    assert played_fixture_ids(df) == {"A", "C", "E"}


def test_played_fixture_ids_empty_when_none_played():
    df = pd.DataFrame({"fixture_id": ["A", "B"], "played": [False, False]})
    assert played_fixture_ids(df) == set()

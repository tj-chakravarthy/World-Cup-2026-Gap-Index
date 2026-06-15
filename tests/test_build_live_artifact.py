"""Live artifact assembly (PLAN.md §6). Pure pieces + schema validity."""

import numpy as np
import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("scipy")

from src.pipeline.build_live_artifact import top_scorelines  # noqa: E402


def test_top_scorelines_orders_and_formats():
    m = np.zeros((4, 4))
    m[2, 1] = 0.5   # 2-1
    m[1, 1] = 0.3   # 1-1
    m[0, 0] = 0.2   # 0-0
    sc = top_scorelines(m, n=3)
    assert [s["score"] for s in sc] == ["2-1", "1-1", "0-0"]
    assert sc[0]["p"] == pytest.approx(0.5)
    assert all(0.0 <= s["p"] <= 1.0 for s in sc)

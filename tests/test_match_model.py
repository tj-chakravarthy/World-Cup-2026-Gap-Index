"""Production match model (PLAN.md §4). Order-invariance of the W/D/L prediction."""

import numpy as np
import pytest

pytest.importorskip("sklearn")

from src.models.match_model import predict_wdl  # noqa: E402


class _MockClf:
    """A 1-feature stand-in: a positive lead favours team1 (class 0), negative favours
    team2 (class 2), with a fixed draw mass."""
    classes_ = np.array([0, 1, 2])

    def predict_proba(self, X):
        lead = X[:, 0]
        p_t1 = 1 / (1 + np.exp(-lead))
        draw = np.full_like(p_t1, 0.26)
        rest = 1 - draw
        return np.column_stack([p_t1 * rest, draw, (1 - p_t1) * rest])


def test_predict_wdl_is_order_invariant():
    diffs = np.array([[2.0], [-1.0], [0.0]])
    out = predict_wdl(_MockClf(), diffs)
    swapped = predict_wdl(_MockClf(), -diffs)
    # viewing the fixture from the other side must swap home/away, keep the draw
    assert np.allclose(out[:, 0], swapped[:, 2])
    assert np.allclose(out[:, 2], swapped[:, 0])
    assert np.allclose(out[:, 1], swapped[:, 1])


def test_predict_wdl_rows_sum_to_one():
    diffs = np.array([[1.5], [-0.5], [3.0]])
    out = predict_wdl(_MockClf(), diffs)
    assert np.allclose(out.sum(axis=1), 1.0)


def test_predict_wdl_even_fixture_is_symmetric():
    # zero lead -> home and away equally likely
    out = predict_wdl(_MockClf(), np.array([[0.0]]))
    assert out[0, 0] == pytest.approx(out[0, 2])

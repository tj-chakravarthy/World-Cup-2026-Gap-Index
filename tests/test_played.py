"""Played-flag coercion (src/played.py) — one reading of `played`, used everywhere.

The fixtures CSV round-trips `played` as bool, 'True'/'False' strings, or 1/0. These pin the
two failure modes that motivated centralising it: a string 'True' must count as played (a
bare `== True` missed it) and a string 'False' must NOT (`bool('False')` was wrongly truthy).
"""

import pytest

pd = pytest.importorskip("pandas")
np = pytest.importorskip("numpy")

from src.played import is_played, played_mask  # noqa: E402


@pytest.mark.parametrize("value", [
    True, "True", "true", " TRUE ", 1, 1.0, "1", np.bool_(True), np.int64(1),
])
def test_is_played_true_forms(value):
    assert is_played(value) is True


@pytest.mark.parametrize("value", [
    False, "False", "false", " false ", 0, 0.0, "0", "", np.bool_(False), np.int64(0),
    None, np.nan,
])
def test_is_played_false_forms(value):
    assert is_played(value) is False


def test_played_mask_on_string_column():
    # the brittle case: a column read back as 'True'/'False' strings
    s = pd.Series(["True", "False", "true", "False"])
    assert list(played_mask(s)) == [True, False, True, False]


def test_played_mask_on_bool_and_int_columns():
    assert list(played_mask(pd.Series([True, False, True]))) == [True, False, True]
    assert list(played_mask(pd.Series([1, 0, 1]))) == [True, False, True]


def test_played_mask_is_boolean_dtype():
    # must be a real boolean mask so `df[mask]` selects rows, not an object column
    assert played_mask(pd.Series(["True", "False"])).dtype == bool

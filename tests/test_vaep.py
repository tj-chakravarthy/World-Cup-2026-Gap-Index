"""Observed-VAEP aggregation (PLAN.md §2.2). Pure-function coverage.

The module imports socceraction at top (for the SPADL/VAEP build), so this skips
where socceraction is absent (CI). The aggregation maths itself needs no events.
"""

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("socceraction")

from src.features.vaep import aggregate_player_vaep  # noqa: E402


def test_aggregate_sums_offense_defense_and_per90():
    actions = pd.DataFrame({"player_id": [1, 1, 2, 2, 2], "team_id": [10] * 5})
    values = pd.DataFrame({
        "vaep_value":      [0.1, 0.2, 0.5, -0.1, 0.0],
        "offensive_value": [0.1, 0.2, 0.5, 0.0, 0.0],
        "defensive_value": [0.0, 0.0, 0.0, -0.1, 0.0],
    })
    players = pd.DataFrame({"player_id": [1, 2], "team_id": [10, 10],
                            "minutes_played": [90, 45], "player_name": ["A", "B"]})
    out = aggregate_player_vaep(actions, values, players)

    # sorted by total vaep desc: B (0.4) before A (0.3)
    assert list(out["player_name"]) == ["B", "A"]
    by = out.set_index("player_name")
    assert by.loc["A", "vaep"] == pytest.approx(0.3)
    assert by.loc["A", "n_actions"] == 2
    assert by.loc["A", "vaep_per90"] == pytest.approx(0.3)        # 90 min -> /1.0
    assert by.loc["B", "vaep"] == pytest.approx(0.4)
    assert by.loc["B", "defensive"] == pytest.approx(-0.1)
    assert by.loc["B", "vaep_per90"] == pytest.approx(0.8)        # 45 min -> /0.5


def test_minutes_floor_avoids_divide_by_zero():
    actions = pd.DataFrame({"player_id": [1], "team_id": [10]})
    values = pd.DataFrame({"vaep_value": [0.5], "offensive_value": [0.5],
                           "defensive_value": [0.0]})
    players = pd.DataFrame({"player_id": [1], "team_id": [10],
                            "minutes_played": [0], "player_name": ["X"]})
    out = aggregate_player_vaep(actions, values, players)
    assert pd.notna(out.loc[0, "vaep_per90"])  # clipped, not inf/nan

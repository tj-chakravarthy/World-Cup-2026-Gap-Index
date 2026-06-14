"""Understat league-data parsing (PLAN.md §1.2). Stdlib only, CI-safe."""

import gzip
import json

from src.pipeline.fetch_understat import parse_league_data

_SAMPLE = {
    "teams": {},
    "players": [{"id": "1", "player_name": "Erling Haaland", "xG": "31.65",
                 "team_title": "Manchester City", "npxG": "25.56"}],
    "dates": [],
}


def test_parse_gzipped_payload():
    raw = gzip.compress(json.dumps(_SAMPLE).encode("utf-8"))
    players = parse_league_data(raw, gzipped=True)
    assert len(players) == 1
    assert players[0]["player_name"] == "Erling Haaland"
    assert players[0]["xG"] == "31.65"


def test_parse_plain_payload():
    raw = json.dumps(_SAMPLE).encode("utf-8")
    players = parse_league_data(raw, gzipped=False)
    assert players[0]["npxG"] == "25.56"

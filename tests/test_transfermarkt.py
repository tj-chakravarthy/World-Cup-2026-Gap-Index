"""Pure-function tests for the Transfermarkt fetcher (no network, no browser).

Market-value parsing and the squad/search HTML parsing are where a silent bug
would corrupt the ratings. selenium/bs4 aren't in the CI dev subset, so guard the
import rather than break collection (same pattern as test_stage1_parsers.py)."""

import pytest

pytest.importorskip("selenium")
pytest.importorskip("bs4")

from src.pipeline.fetch_transfermarkt import (  # noqa: E402
    harvest_search_candidates, parse_market_value, parse_squad_table,
    pick_national_team)


def test_parse_market_value_units():
    assert parse_market_value("€20.00m") == 20_000_000
    assert parse_market_value("€800k") == 800_000
    assert parse_market_value("€1.50bn") == 1_500_000_000
    assert parse_market_value("€500") == 500
    assert parse_market_value("-") is None
    assert parse_market_value("") is None
    assert parse_market_value(None) is None


_SQUAD_HTML = """
<table class="items"><tbody>
  <tr class="odd">
    <td class="zentriert rueckennummer">1</td>
    <td><table class="inline-table"><tr>
      <td><a href="/jordan-pickford/profil/spieler/97032">Jordan Pickford</a></td>
      </tr><tr><td>Goalkeeper</td></tr></table></td>
    <td class="zentriert">07/03/1994 (30)</td>
    <td class="zentriert"><a href="/everton-fc/startseite/verein/29" title="Everton FC">
      <img alt="Everton FC" src="x.png"/></a></td>
    <td class="rechts hauptlink"><a href="/x">€20.00m</a></td>
  </tr>
  <tr class="even">
    <td class="zentriert rueckennummer">23</td>
    <td><table class="inline-table"><tr>
      <td><a href="/uncapped/profil/spieler/55">Uncapped Kid</a></td>
      </tr><tr><td>Centre-Back</td></tr></table></td>
    <td class="zentriert">01/01/2005 (20)</td>
    <td class="zentriert"><a href="/club/startseite/verein/9" title="Some Club">
      <img alt="Some Club" src="x.png"/></a></td>
    <td class="rechts hauptlink">-</td>
  </tr>
  <tr class="bg_blau_20"><td>group separator row, skipped</td></tr>
</tbody></table>
"""


def test_parse_squad_table_extracts_value_position_club():
    rows = parse_squad_table(_SQUAD_HTML, "ENG", "2025")
    assert len(rows) == 2  # separator row dropped
    a = rows[0]
    assert a["player_name"] == "Jordan Pickford"
    assert a["position"] == "Goalkeeper"
    assert a["club"] == "Everton FC"
    assert a["tm_player_id"] == "97032"
    assert a["market_value_eur"] == 20_000_000
    assert a["country_code"] == "ENG" and a["season"] == "2025"
    assert rows[1]["market_value_eur"] == ""  # '-' -> blank, not 0


_SEARCH_HTML = """
<div><a href="/sudkorea-u23/startseite/verein/34950">South Korea U23</a></div>
<div><a href="/fc-seoul/startseite/verein/8240">FC Seoul</a></div>
<div><a href="/sudkorea/startseite/verein/3589">South Korea</a></div>
"""


def test_pick_national_team_prefers_senior_over_youth():
    cands = harvest_search_candidates(_SEARCH_HTML)
    assert ("sudkorea", "3589", "South Korea") in cands
    pick = pick_national_team(cands, "South Korea")
    assert pick is not None
    slug, tm_id, text, score = pick
    assert (slug, tm_id) == ("sudkorea", "3589")  # not the U23 variant


def test_pick_national_team_none_when_no_match():
    cands = harvest_search_candidates(_SEARCH_HTML)
    assert pick_national_team(cands, "Brazil") is None

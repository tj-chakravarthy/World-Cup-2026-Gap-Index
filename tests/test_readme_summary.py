"""README top-board updater (src/update/readme_summary.py). Pure-function coverage."""

import pytest

from src.update.readme_summary import END, START, inject, render_block

SIM = {
    "generated_at": "2026-06-16T11:26:37Z",
    "teams": [
        {"country_code": "FRA", "p_winner": 0.093},
        {"country_code": "ESP", "p_winner": 0.124},
        {"country_code": "ENG", "p_winner": 0.080},
        {"country_code": "ARG", "p_winner": 0.099},
        {"country_code": "BRA", "p_winner": 0.058},
    ],
}
NAMES = {"FRA": "France", "ESP": "Spain", "ENG": "England", "ARG": "Argentina", "BRA": "Brazil"}


def test_render_block_sorts_rounds_and_stamps():
    b = render_block(SIM, NAMES, n=4)
    assert b.startswith(START) and b.endswith(END)
    # sorted by p_winner desc, rounded to whole %, top 4 only (Brazil dropped)
    assert "Spain 12%, Argentina 10%, France 9%, England 8%." in b
    assert "Brazil" not in b
    assert "_(updated 2026-06-16 11:26 UTC)_" in b


def test_render_block_falls_back_to_code():
    b = render_block({"generated_at": "x", "teams": [{"country_code": "ZZZ", "p_winner": 0.5}]},
                     {}, n=1)
    assert "ZZZ 50%" in b


def test_inject_replaces_only_the_block():
    text = f"intro\n\n{START}\nold odds\n{END}\n\noutro\n"
    out = inject(text, f"{START}\nNEW\n{END}")
    assert "NEW" in out and "old odds" not in out
    assert out.startswith("intro") and out.endswith("outro\n")


def test_inject_raises_without_markers():
    with pytest.raises(ValueError):
        inject("no markers here", "block")

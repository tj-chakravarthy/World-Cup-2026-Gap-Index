"""Name matcher (PLAN.md §"Known Challenges"). No network, no rapidfuzz required
— the difflib fallback must carry these on a bare env."""

from src.pipeline.name_matcher import Matcher, normalize


def test_normalize_folds_diacritics_and_punctuation():
    assert normalize("Bayern München") == "bayern munchen"
    assert normalize("Atlético Madrid") == "atletico madrid"
    assert normalize("Real Madrid C.F.") == "real madrid c f"


def test_exact_match_after_normalisation():
    m = Matcher(["Real Madrid", "Bayern Munich"])
    target, score, method = m.match("Real Madrid")
    assert (target, method) == ("Real Madrid", "exact")
    assert score == 1.0


def test_fuzzy_match_above_threshold():
    m = Matcher(["Manchester City", "Manchester United"], threshold=0.8)
    target, score, method = m.match("Manchester Citys")  # typo
    assert target == "Manchester City"
    assert method == "fuzzy"


def test_override_takes_precedence():
    m = Matcher(["PSV"], overrides={"PSV Eindhoven": "PSV"})
    target, _, method = m.match("PSV Eindhoven")
    assert (target, method) == ("PSV", "override")


def test_below_threshold_returns_none_and_is_listed_unmatched():
    m = Matcher(["Internazionale"], threshold=0.84)
    target, _, method = m.match("Borussia Dortmund")
    assert target is None and method == "none"
    assert [n for n, _ in m.unmatched(["Borussia Dortmund"])] == ["Borussia Dortmund"]

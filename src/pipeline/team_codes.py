"""Team-code crosswalk: source names -> FIFA trigram (PLAN.md name_matcher).

The three Stage-0 sources name teams three different ways:
  fixtures_2026.csv : FIFA short names + trigram codes (the canonical key)
  eloratings        : its own English names ("South Korea", "Ivory Coast")
  martj42 results   : a third spelling ("Czech Republic", "United States")

This maps the 48 WC-2026 finalists across all three onto the FIFA trigram, so
the Elo baseline (eloratings -> fixtures) and the Dixon-Coles output (martj42 ->
fixtures) both land on the same key. Scope is the 48 finalists, not all 200+
nations: the goals model keys on martj42's self-consistent names internally and
only its output for the 48 needs translating; the Elo baseline likewise only
needs the 48.

Built by exact name-match against the live source data plus a small hand alias
table for the genuine variants. The build VALIDATES every mapping — each alias
target must appear in its source and all 48 teams must resolve, else it fails
loudly. data/raw/team_codes.csv is small and canonical, so it is committed (like
the fixtures/venues spine). Stdlib only.
"""

from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FIXTURES_CSV = REPO / "data" / "raw" / "fixtures_2026.csv"
ELO_CSV = REPO / "data" / "raw" / "elo_national_current.csv"
RESULTS_CSV = REPO / "data" / "raw" / "match_results.csv"
TEAM_CODES_CSV = REPO / "data" / "raw" / "team_codes.csv"

FIELDS = ["fifa_code", "name", "eloratings_name", "martj42_name"]

# canonical (fixtures) name -> source name, only where the source differs.
# Verified against the live source sets; CZE is the split case (eloratings keeps
# "Czechia", martj42 uses "Czech Republic").
ELO_ALIASES = {
    "Côte d'Ivoire": "Ivory Coast",
    "Congo DR": "DR Congo",
    "Cabo Verde": "Cape Verde",
    "IR Iran": "Iran",
    "Korea Republic": "South Korea",
    "Türkiye": "Turkey",
    "USA": "United States",
}
MARTJ42_ALIASES = {
    "Côte d'Ivoire": "Ivory Coast",
    "Congo DR": "DR Congo",
    "Cabo Verde": "Cape Verde",
    "Czechia": "Czech Republic",
    "IR Iran": "Iran",
    "Korea Republic": "South Korea",
    "Türkiye": "Turkey",
    "USA": "United States",
}


def build_rows(wc_teams: list[tuple[str, str]], elo_names: set[str],
               martj42_names: set[str]) -> list[dict]:
    """Map each (fifa_code, canonical_name) to its eloratings + martj42 name.
    Raises if any alias target is absent from its source or any team is
    unresolved — a silent miss here would corrupt the Elo join and the
    Dixon-Coles output."""
    rows, problems = [], []
    for fifa, name in wc_teams:
        elo = ELO_ALIASES.get(name, name)
        m42 = MARTJ42_ALIASES.get(name, name)
        if elo not in elo_names:
            problems.append(f"{fifa} {name}: eloratings name {elo!r} not in source")
        if m42 not in martj42_names:
            problems.append(f"{fifa} {name}: martj42 name {m42!r} not in source")
        rows.append({"fifa_code": fifa, "name": name,
                     "eloratings_name": elo, "martj42_name": m42})
    if problems:
        raise ValueError("crosswalk build failed:\n  " + "\n  ".join(problems))

    for col in ("fifa_code", "eloratings_name", "martj42_name"):
        vals = [r[col] for r in rows]
        dupes = sorted({v for v in vals if vals.count(v) > 1})
        if dupes:
            raise ValueError(f"two WC teams share a {col}: {dupes}")
    return rows


def _wc_teams(fixtures_csv: Path = FIXTURES_CSV) -> list[tuple[str, str]]:
    seen = {}
    for r in csv.DictReader(fixtures_csv.open()):
        if r["stage"] != "group":
            continue
        for code, name in ((r["home_code"], r["home_team"]),
                           (r["away_code"], r["away_team"])):
            seen[code] = name
    return sorted(seen.items())


def _names(path: Path, col: str) -> set[str]:
    return {r[col] for r in csv.DictReader(path.open())}


def main() -> None:
    wc = _wc_teams()
    elo_names = _names(ELO_CSV, "team_name")
    m42_home = _names(RESULTS_CSV, "home_team")
    m42_away = _names(RESULTS_CSV, "away_team")
    rows = build_rows(wc, elo_names, m42_home | m42_away)
    if len(rows) != 48:
        raise ValueError(f"expected 48 WC teams, got {len(rows)}")

    TEAM_CODES_CSV.parent.mkdir(parents=True, exist_ok=True)
    with TEAM_CODES_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    aliased = sum(1 for r in rows if r["name"] != r["eloratings_name"]
                  or r["name"] != r["martj42_name"])
    print(f"wrote {len(rows)} team codes ({aliased} needed an alias) -> {TEAM_CODES_CSV}")


@dataclass(frozen=True)
class TeamCodes:
    """Loaded crosswalk for downstream joins onto the FIFA trigram."""
    fifa_to_name: dict[str, str]
    eloratings_to_fifa: dict[str, str]
    martj42_to_fifa: dict[str, str]

    @classmethod
    def load(cls, path: Path = TEAM_CODES_CSV) -> "TeamCodes":
        rows = list(csv.DictReader(path.open()))
        return cls(
            fifa_to_name={r["fifa_code"]: r["name"] for r in rows},
            eloratings_to_fifa={r["eloratings_name"]: r["fifa_code"] for r in rows},
            martj42_to_fifa={r["martj42_name"]: r["fifa_code"] for r in rows},
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"team_codes build failed: {e}", file=sys.stderr)
        sys.exit(1)

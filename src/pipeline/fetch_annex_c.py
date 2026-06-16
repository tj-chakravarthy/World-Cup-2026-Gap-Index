"""FIFA World Cup 26 third-place allocation — Annex C (exact).

When 8 of the 12 third-placed teams advance, which R32 slot each fills is fixed by a
495-row table FIFA published in Annex C of the regulations (one row per way to pick 8 of
12 groups). bracket.py otherwise solves the slot *constraint* — a valid bijection, but not
guaranteed to be FIFA's row. This scrapes the real table.

Source: the "2026 FIFA World Cup knockout stage" article reproduces Annex C verbatim — a
wikitable keyed by the qualifying-group combination, with one column per winner-vs-third
R32 match ("1A vs", "1B vs", …) giving the third-placed group that fills it. Writes
data/raw/annex_c_thirds.csv: `groups` (the sorted 8-letter combination) + one `w_<winner>`
column per winner group. requests (apt base).
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import requests

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "data" / "raw" / "annex_c_thirds.csv"
PAGE = "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_knockout_stage"
GROUPS = set("ABCDEFGHIJKL")


def _cells(tr: str) -> list[str]:
    return [re.sub(r"<[^>]+>", " ", c).replace("\xa0", " ").strip()
            for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S)]


def parse_annex_c(html: str) -> pd.DataFrame:
    """The 495 combination rows -> DataFrame(groups, w_<winner>...)."""
    table = re.findall(r"<table[^>]*wikitable[^>]*>.*?</table>", html, re.S)[0]
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S)
    winners = [m.group(1) for c in _cells(rows[0])
               if (m := re.match(r"1([A-L])\s*vs", c.replace("\xa0", " ")))]
    if len(winners) != 8:
        raise RuntimeError(f"expected 8 winner columns, parsed {winners}")

    out = []
    for tr in rows[1:]:
        cs = _cells(tr)
        qual = [c for c in cs if c in GROUPS]                       # single-letter group cells
        thirds = [m.group(1) for c in cs if (m := re.fullmatch(r"3([A-L])", c))]
        if not qual and not thirds:
            continue                                                # spacer / non-data row
        if len(qual) != 8 or len(thirds) != 8 or set(thirds) != set(qual):
            raise RuntimeError(f"malformed Annex C row: qual={qual} thirds={thirds}")
        row = {"groups": "".join(sorted(qual))}
        row.update({f"w_{w}": t for w, t in zip(winners, thirds)})
        out.append(row)

    df = pd.DataFrame(out, columns=["groups"] + [f"w_{w}" for w in winners])
    if len(df) != 495 or df["groups"].nunique() != 495:
        raise RuntimeError(f"expected 495 distinct combinations, got {len(df)}")
    return df


def main() -> None:
    html = requests.get(PAGE, headers={"User-Agent": "Mozilla/5.0"}, timeout=30).text
    df = parse_annex_c(html)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    print(f"Annex C: {len(df)} combinations -> {OUT.relative_to(REPO)}")
    print(df.head(3).to_string(index=False))


if __name__ == "__main__":
    main()

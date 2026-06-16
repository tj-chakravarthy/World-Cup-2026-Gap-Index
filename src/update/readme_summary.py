"""Keep the README's 'top of the board' line in sync with the live forecast.

run_all calls update_readme() after each recompute, so the headline win odds + an
'updated' UTC stamp track the latest simulation. The line is marker-delimited so only
that block changes and the rest of the README is never touched. stdlib only (json + csv),
so it adds nothing to the cron's --check path.
"""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
README = REPO / "README.md"
SIM_JSON = REPO / "data" / "predictions" / "simulation.json"
CODES = REPO / "data" / "raw" / "team_codes.csv"

START, END = "<!-- TOPBOARD:START -->", "<!-- TOPBOARD:END -->"


def _names(codes: Path = CODES) -> dict[str, str]:
    """FIFA code -> display name (team_codes.csv)."""
    return {r["fifa_code"]: r["name"] for r in csv.DictReader(codes.open())}


def _fmt_stamp(iso: str) -> str:
    """sim generated_at (ISO-8601 Z) -> 'YYYY-MM-DD HH:MM UTC'. Pass-through on garbage."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, AttributeError):
        return iso or "—"


def render_block(sim: dict, names: dict[str, str], n: int = 4) -> str:
    """Marker-wrapped 'top of the board' block: top-n teams by p_winner + the sim's
    'updated' stamp. Pure."""
    top = sorted(sim["teams"], key=lambda t: t["p_winner"], reverse=True)[:n]
    odds = ", ".join(f"{names.get(t['country_code'], t['country_code'])} "
                     f"{round(t['p_winner'] * 100)}%" for t in top)
    return (f"{START}\n"
            f"Top of the board to win it: **{odds}.** "
            f"_(updated {_fmt_stamp(sim.get('generated_at', ''))})_\n"
            f"{END}")


def inject(readme_text: str, block: str) -> str:
    """Replace the marker-delimited block (markers included). Pure; raises if absent."""
    pat = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
    if not pat.search(readme_text):
        raise ValueError("TOPBOARD markers not found in README")
    return pat.sub(lambda _: block, readme_text)


def update_readme(readme: Path = README, sim_json: Path = SIM_JSON) -> bool:
    """Rewrite the README top-board block from the latest sim. Returns True if it changed.
    Best-effort: missing file or markers -> no-op, never raises (can't break the cron)."""
    if not (readme.exists() and sim_json.exists()):
        return False
    try:
        sim = json.loads(sim_json.read_text())
        new = inject(readme.read_text(), render_block(sim, _names()))
    except (ValueError, KeyError, json.JSONDecodeError):
        return False
    if new != readme.read_text():
        readme.write_text(new)
        return True
    return False


if __name__ == "__main__":
    print("updated" if update_readme() else "no change")

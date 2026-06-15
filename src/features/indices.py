"""Squad composite indices (PLAN.md §3) — the match-model inputs.

One row per (tournament, team). Each index is a domain-weighted squad aggregate,
then **z-scored cross-sectionally within that tournament's field** (mean 0, std 1 over
the tournament's teams, no outcomes) — the §3 normalization contract: leakage-safe by
construction, carries no fitted parameters, so it is exempt from the nested-CV fold
loop. The z-score also normalises era ("1 std above the field" is comparable across
years).

The fitted part of the rating stack — the predicted-VAEP model — is passed IN, so the
nested CV (§4.5) can refit it per fold and rebuild indices on `train_only` data.
Predicted-VAEP indices (ATK/MID/DEF/GK) are kept SEPARATE from the market-value index
(MKT) and Elo (ELO) so the §4.5 feature-group ablation can isolate the thesis signal
(does predicted VAEP add over Elo + market value).

Backtest tournaments without a scraped Transfermarkt season (Euro2020/2024, Copa2024)
get a NaN MKT for now — predicted VAEP and Elo still build. pandas + sklearn.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.features.player_features import load_player_features, position_group
from src.features.player_scores import join_market_value, load_market_values
from src.features.predicted_vaep import (build_training_table, predict_live,
                                         train_model)

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"
PROC = REPO / "data" / "processed"

# tournament -> (squad csv, preceding club season, Transfermarkt value season or None)
TOURNAMENTS = {
    "world_cup_2018": ("squads_2018.csv", "2017-2018", "2017"),
    "euro_2020": ("squads_euro2020.csv", "2020-2021", None),
    "world_cup_2022": ("squads_2022.csv", "2021-2022", "2021"),
    "euro_2024": ("squads_euro2024.csv", "2023-2024", None),
    "copa_america_2024": ("squads_copa2024.csv", "2023-2024", None),
    "world_cup_2026": ("squads_2026.csv", "2025-2026", "2025"),
}
# predicted-VAEP indices (the thesis signal) | market value | Elo | squad structure
PRED_INDICES = ["ATK", "MID", "DEF", "GK"]
INDEX_COLS = PRED_INDICES + ["MKT", "ELO", "EXP", "AGE", "DEPTH", "COH", "COV", "FAT"]
# top-k players per position group that define the position index
_TOPK = {"FW": 3, "MF": 4, "DF": 4, "GK": 1}
_POS_INDEX = {"ATK": "FW", "MID": "MF", "DEF": "DF", "GK": "GK"}


def _topk_mean(s: pd.Series, k: int) -> float:
    s = s.dropna()
    return s.nlargest(k).mean() if len(s) else np.nan


def team_raw_indices(players: pd.DataFrame, elo: float) -> dict:
    """Raw (pre-z-score) indices for one team's squad. `players` columns:
    pos_group, vaep_per90_pred, market_value_eur, caps, age, club, minutes_90s."""
    out = {}
    for idx, pos in _POS_INDEX.items():
        grp = players[players["pos_group"] == pos]
        out[idx] = _topk_mean(grp["vaep_per90_pred"], _TOPK[pos])
    mv = pd.to_numeric(players["market_value_eur"], errors="coerce")
    logmv = np.log10(mv.where(mv > 0))
    out["MKT"] = logmv.nlargest(15).mean()
    out["ELO"] = elo
    out["EXP"] = np.log1p(pd.to_numeric(players["caps"], errors="coerce")).mean()
    out["AGE"] = pd.to_numeric(players["age"], errors="coerce").mean()
    # depth = rating drop-off from the XI to the bench (top-11 minus 12-23), on log mv
    top = logmv.nlargest(11).mean()
    bench = logmv.nlargest(23).iloc[11:].mean() if logmv.notna().sum() > 11 else top
    out["DEPTH"] = top - bench
    clubs = players["club"].dropna()
    out["COH"] = 1 - clubs.nunique() / len(clubs) if len(clubs) else np.nan
    out["COV"] = players["vaep_per90_pred"].notna().mean()
    out["FAT"] = _topk_mean(pd.to_numeric(players["minutes_90s"], errors="coerce"), 11)
    return out


def build_player_table(tournament: str, model, club_feats: pd.DataFrame) -> pd.DataFrame:
    """Per-player rating inputs for one tournament's squads: squad metadata + predicted
    VAEP (from the tournament's club season) + market value (where scraped)."""
    squad_csv, season, tm_season = TOURNAMENTS[tournament]
    squad = pd.read_csv(RAW / squad_csv)
    squad["pos_group"] = squad["position"].map(position_group)
    squad = squad.rename(columns={"age_at_tournament": "age"})

    pred = predict_live(model, RAW / squad_csv, club_feats, season=season)
    squad = squad.merge(pred[["country_code", "player_name", "vaep_per90_pred",
                              "minutes_90s"]],
                        on=["country_code", "player_name"], how="left")
    if tm_season:
        mv, _ = join_market_value(squad, load_market_values(tm_season))
        squad["market_value_eur"] = mv
    else:
        squad["market_value_eur"] = np.nan
    return squad


def zscore_within(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Z-score each column within the frame (one tournament's field). A column that is
    constant or all-NaN is left as-is (NaN std -> no divide). Pure."""
    out = df.copy()
    for c in cols:
        v = pd.to_numeric(out[c], errors="coerce")
        sd = v.std(ddof=0)
        out[c] = (v - v.mean()) / sd if sd and not np.isnan(sd) else v - v.mean()
    return out


def build_indices(model=None, club_feats: pd.DataFrame | None = None,
                  tournaments: list[str] | None = None) -> pd.DataFrame:
    """Squad indices for the given tournaments (default: all with a squad file present),
    z-scored within each tournament. `model`/`club_feats` default to a production
    predicted-VAEP model trained on all observed data; the nested CV passes a
    fold-specific model instead."""
    if club_feats is None:
        club_feats = load_player_features()
    if model is None:
        observed = pd.read_csv(PROC / "vaep_observed.csv")
        model = train_model(build_training_table(observed, club_feats))
    names = tournaments or [t for t in TOURNAMENTS if (RAW / TOURNAMENTS[t][0]).exists()]

    frames = []
    for tournament in names:
        players = build_player_table(tournament, model, club_feats)
        elo = pd.read_csv(PROC / "elo_pretournament.csv")
        elo = elo[elo["tournament"] == tournament].set_index("team")["elo"]
        rows = []
        for code, grp in players.groupby("country_code"):
            country = grp["country"].iloc[0]
            rows.append({"tournament": tournament, "country_code": code, "team": country,
                         **team_raw_indices(grp, elo.get(country, np.nan))})
        td = zscore_within(pd.DataFrame(rows), INDEX_COLS)
        frames.append(td)
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    idx = build_indices()
    PROC.mkdir(parents=True, exist_ok=True)
    out = PROC / "squad_indices.csv"
    idx.to_csv(out, index=False)
    print(f"squad indices: {len(idx)} team-tournaments, "
          f"{idx['tournament'].nunique()} tournaments -> {out.relative_to(REPO)}")
    print(idx.groupby("tournament").size().to_string())
    # sanity: top teams by predicted-VAEP attack index in 2026
    live = idx[idx.tournament == "world_cup_2026"]
    print("\nWC2026 top ATK index:",
          ", ".join(live.nlargest(6, "ATK")["team"].tolist()))
    print("WC2026 top ELO index:",
          ", ".join(live.nlargest(6, "ELO")["team"].tolist()))


if __name__ == "__main__":
    main()

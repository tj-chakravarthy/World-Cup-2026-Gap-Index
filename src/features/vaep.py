"""Observed VAEP from StatsBomb tournament events (PLAN.md §2.2).

Converts StatsBomb open-data events to SPADL actions, trains the standard
scores/concedes models on the pooled action set, values every action (VAEP), and
aggregates per player into per-90 VAEP. This is the observed tournament impact
that the club-to-country translation (predicted VAEP) is trained to reproduce.

socceraction 1.4.2 predates numpy 2; the alias shim below runs before importing
socceraction/pandera (see docs/deviations.md, [[socceraction-install-recipe]]).
Reads a local mirror of statsbomb/open-data under data/raw/statsbomb-open-data.
"""

from __future__ import annotations

import numpy as np

# numpy-2 removed-alias shim — MUST run before importing socceraction/pandera.
for _o, _n in [("string_", "bytes_"), ("unicode_", "str_"), ("float_", "float64"),
               ("complex_", "complex128"), ("bool8", "bool_"), ("int_", "int64")]:
    if not hasattr(np, _o) and hasattr(np, _n):
        setattr(np, _o, getattr(np, _n))

import warnings  # noqa: E402
from pathlib import Path  # noqa: E402

import pandas as pd  # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: E402

import socceraction.spadl as spadl  # noqa: E402
from socceraction.data.statsbomb import StatsBombLoader  # noqa: E402
from socceraction.spadl.statsbomb import convert_to_actions  # noqa: E402
from socceraction.vaep import features as ft, formula as fm, labels as lb  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SB_ROOT = REPO / "data" / "raw" / "statsbomb-open-data"

# the 5 backtest tournaments (competition_id, season_id, label) — match the mirror
TOURNAMENTS = [
    (43, 3, "world_cup_2018"), (43, 106, "world_cup_2022"),
    (55, 43, "euro_2020"), (55, 282, "euro_2024"),
    (223, 282, "copa_america_2024"),
]

# the standard socceraction VAEP feature set
_XFNS = [ft.actiontype_onehot, ft.bodypart_onehot, ft.result_onehot, ft.goalscore,
         ft.startlocation, ft.endlocation, ft.movement, ft.space_delta,
         ft.startpolar, ft.endpolar, ft.team, ft.time, ft.time_delta]


def game_actions(loader: StatsBombLoader, game) -> pd.DataFrame:
    """One game's events -> named SPADL actions."""
    ev = loader.events(game["game_id"])
    return spadl.add_names(convert_to_actions(ev, game["home_team_id"]))


def features_labels(actions: pd.DataFrame, home_team_id: int):
    """VAEP feature matrix X and label frame Y (scores, concedes) for one game."""
    gs = ft.play_left_to_right(ft.gamestates(actions, 3), home_team_id)
    X = pd.concat([fn(gs) for fn in _XFNS], axis=1)
    Y = pd.concat([lb.scores(actions), lb.concedes(actions)], axis=1)
    return X, Y


def aggregate_player_vaep(actions: pd.DataFrame, values: pd.DataFrame,
                          players: pd.DataFrame) -> pd.DataFrame:
    """Sum VAEP per player, attach name + tournament minutes, compute per-90.

    Pure function (no socceraction, no network) so it is unit-testable. `actions`
    and `values` are row-aligned; `players` carries minutes_played + player_name
    per (player_id, team_id)."""
    v = actions[["player_id", "team_id"]].reset_index(drop=True).copy()
    v["vaep"] = values["vaep_value"].to_numpy()
    v["offensive"] = values["offensive_value"].to_numpy()
    v["defensive"] = values["defensive_value"].to_numpy()
    agg = (v.groupby(["player_id", "team_id"], as_index=False)
             .agg(vaep=("vaep", "sum"), offensive=("offensive", "sum"),
                  defensive=("defensive", "sum"), n_actions=("vaep", "size")))
    mins = (players.groupby(["player_id", "team_id"], as_index=False)
                   .agg(minutes=("minutes_played", "sum"),
                        player_name=("player_name", "first")))
    out = agg.merge(mins, on=["player_id", "team_id"], how="left")
    out["vaep_per90"] = out["vaep"] / (out["minutes"].clip(lower=1) / 90.0)
    return out.sort_values("vaep", ascending=False).reset_index(drop=True)


def build_vaep(tournaments=None, root: Path = SB_ROOT,
               min_minutes: float = 270.0) -> pd.DataFrame:
    """Observed-VAEP build over the given tournaments. Pools all actions to train
    scores/concedes, values each game's actions, aggregates per player. Games whose
    events are not in the mirror are skipped (so a partial mirror still runs)."""
    root = Path(root)
    if not root.exists():
        raise FileNotFoundError(f"no StatsBomb mirror at {root}")
    targets = tournaments or TOURNAMENTS
    loader = StatsBombLoader(getter="local", root=str(root))

    per_game, Xs, Ys, players_list, skipped = [], [], [], [], 0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for cid, sid, _label in targets:
            for _, g in loader.games(competition_id=cid, season_id=sid).iterrows():
                if not (root / "events" / f"{g['game_id']}.json").exists():
                    skipped += 1
                    continue
                acts = game_actions(loader, g)
                X, Y = features_labels(acts, g["home_team_id"])
                per_game.append((acts.reset_index(drop=True), X.astype(float)))
                Xs.append(X.astype(float))
                Ys.append(Y.astype(int))
                players_list.append(loader.players(g["game_id"]))
        if not per_game:
            raise FileNotFoundError(f"no game events found under {root}")

        Xall, Yall = pd.concat(Xs, ignore_index=True), pd.concat(Ys, ignore_index=True)
        models = {}
        for col in ("scores", "concedes"):
            m = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05)
            m.fit(Xall.to_numpy(), Yall[col].to_numpy())
            models[col] = m

        act_frames, val_frames = [], []
        for acts, X in per_game:
            ps = pd.Series(models["scores"].predict_proba(X.to_numpy())[:, 1])
            pc = pd.Series(models["concedes"].predict_proba(X.to_numpy())[:, 1])
            val_frames.append(fm.value(acts, ps, pc).reset_index(drop=True))
            act_frames.append(acts)

    actions = pd.concat(act_frames, ignore_index=True)
    values = pd.concat(val_frames, ignore_index=True)
    players = pd.concat(players_list, ignore_index=True)
    if skipped:
        print(f"note: skipped {skipped} games not in the mirror")
    out = aggregate_player_vaep(actions, values, players)
    return out[out["minutes"].fillna(0) >= min_minutes].reset_index(drop=True)


def main() -> None:
    out_dir = REPO / "data" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    df = build_vaep()
    path = out_dir / "vaep_observed.csv"
    df.to_csv(path, index=False)
    print(f"{len(df)} players (>= min minutes) -> {path.relative_to(REPO)}")
    print(df.head(10)[["player_name", "minutes", "n_actions", "vaep", "vaep_per90"]].to_string(index=False))


if __name__ == "__main__":
    main()

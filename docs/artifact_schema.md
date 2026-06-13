# Prediction artifact schema

Defines the on-disk JSON the pipeline writes to `data/predictions/` and mirrors
to `web/public/data/`. Locked here **before** the writer is implemented, because
the Stage-0 lock (PLAN.md §0, Build Order Stage 0) is urgent and the locked file
can never be re-issued — its shape has to be right the first time.

Two files share one shape, distinguished by `kind`:

- `predictions_locked_{YYYYMMDD}.json` — **written once, never modified.** Covers
  only fixtures **not yet kicked off** at `locked_at_utc`. Its job is a verifiable
  timestamp, not peak accuracy (Stage-0 minimal model A+C on a thin feature set).
- `predictions_live.json` — rewritten by the daily cron (PLAN.md §6).

Audit trail (`prediction_log.parquet`) is append-only and tabular; its columns
mirror the per-prediction fields below plus `outcome` (null until played).

## Top level

| field | type | notes |
|---|---|---|
| `schema_version` | string | this document's version, e.g. `"1.0"` |
| `kind` | `"locked"` \| `"live"` | |
| `model_version` | string | exact model identity, e.g. `"stage0-AC-thin@<git-sha>"` — pins which code/model produced the file |
| `generated_at` | UTC ISO-8601 | when this file was written |
| `locked_at_utc` | UTC ISO-8601 \| null | **locked only:** the verifiable lock instant; the file covers fixtures unplayed *as of this time*. `null` for live. |
| `tournament` | string | `"FIFA World Cup 26"` |
| `coverage` | object | see below |
| `sources` | array | freshness manifest, see below |
| `predictions` | array | one entry per covered fixture, see below |

### `coverage`

| field | type | notes |
|---|---|---|
| `covered_fixture_ids` | string[] | fixtures this file predicts |
| `excluded_played_fixture_ids` | string[] | fixtures already kicked off at `locked_at_utc`/`generated_at` — **never predicted here**, used only as in-tournament evidence |
| `lock_basis` | string | locked only, e.g. `"unplayed at locked_at_utc"` |

`covered_fixture_ids` and `excluded_played_fixture_ids` must be disjoint, and
together account for every remaining tournament fixture at issue time.

### `sources` (freshness — PLAN.md §6)

Array of `{ "name": string, "as_of": UTC ISO-8601, "stale": bool }` — one row per
upstream the file depends on (fixtures, results, injuries, odds, …). The
`freshness_check` cron step and the on-site "last updated" banner read this.

## `predictions[]`

| field | type | notes |
|---|---|---|
| `fixture_id` | string | matches `fixtures_2026.csv` |
| `stage` | string | `"group"`, `"R32"`, `"R16"`, `"QF"`, `"SF"`, `"final"` |
| `kickoff_utc` | UTC ISO-8601 | |
| `team1`, `team2` | string (FIFA code) | deterministic ordering per PLAN.md §4.1 |
| `model_source` | `"locked_minimal"` \| `"live_full"` | honesty label (PLAN.md §0). Live entries for fixtures also in a locked file keep `"live_full"`; the locked timestamp is **never** retro-credited to the full model. |
| `wdl` | `{team1, draw, team2}` floats, sum≈1 | calibrated, order-invariant marginals |
| `scorelines` | `[{score:"H-A", p:float}]` | top-N from Dixon-Coles (member C) |
| `members` | object | per-member W/D/L for audit, e.g. `{"A":{...}, "C":{...}}`; omit on the fan-facing mirror |
| `conformal_set` | string[] \| null | α=0.10 set; **method surface only** (PLAN.md §7.1a), `null` if disabled |
| `stale` | bool | true if any input fell back to cache (PLAN.md §6) |

## Invariants (assert in the writer)

1. Locked file: `kind=="locked"`, `locked_at_utc` set, and every
   `covered_fixture_ids` kickoff `> locked_at_utc`.
2. Locked file is content-addressed in git history and never rewritten.
3. `model_source` is per-prediction; a fixture predicted by both the locked and
   live files appears once in each, never merged.
4. Probabilities are calibrated and sum to 1 within tolerance.

## Example (locked, abridged)

```json
{
  "schema_version": "1.0",
  "kind": "locked",
  "model_version": "stage0-AC-thin@a1b2c3d",
  "generated_at": "2026-06-13T07:58:00Z",
  "locked_at_utc": "2026-06-13T08:00:00Z",
  "tournament": "FIFA World Cup 26",
  "coverage": {
    "covered_fixture_ids": ["WC26-M037", "WC26-M038"],
    "excluded_played_fixture_ids": ["WC26-M001", "WC26-M002"],
    "lock_basis": "unplayed at locked_at_utc"
  },
  "sources": [
    {"name": "fixtures", "as_of": "2026-06-12T20:00:00Z", "stale": false},
    {"name": "injuries", "as_of": "2026-06-13T06:00:00Z", "stale": false}
  ],
  "predictions": [
    {
      "fixture_id": "WC26-M037",
      "stage": "group",
      "kickoff_utc": "2026-06-20T19:00:00Z",
      "team1": "BRA",
      "team2": "SWE",
      "model_source": "locked_minimal",
      "wdl": {"team1": 0.52, "draw": 0.26, "team2": 0.22},
      "scorelines": [
        {"score": "1-0", "p": 0.121},
        {"score": "2-1", "p": 0.094},
        {"score": "1-1", "p": 0.089}
      ],
      "members": {"A": {"team1": 0.50, "draw": 0.27, "team2": 0.23},
                  "C": {"team1": 0.54, "draw": 0.25, "team2": 0.21}},
      "conformal_set": null,
      "stale": false
    }
  ]
}
```

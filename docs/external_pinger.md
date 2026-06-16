# External pinger — reliable live updates

GitHub's `schedule:` cron is throttled and drops most triggers under load (a `*/15` job
often fires only every few hours), so a finished match can sit unscored for hours. The fix:
an external cron service fires the workflow via `repository_dispatch` instead. The
`schedule:` is kept only as a free backstop.

The workflow (`update_predictions.yml`) listens for:

```yaml
repository_dispatch:
  types: [poll-results]
```

Every ping runs the cheap `run_all --check` gate first; the heavy recompute + commit fire
only when a new result has actually landed (idempotent), so pinging every 15 min is cheap.

## The request

```
POST https://api.github.com/repos/tj-chakravarthy/World-Cup-2026-Gap-Index/dispatches
Accept: application/vnd.github+json
Authorization: Bearer <PAT>
X-GitHub-Api-Version: 2022-11-28

{"event_type":"poll-results"}
```

Success is `204 No Content`. The `event_type` must match the `types:` above.

## The token

A **fine-grained PAT scoped to this one repo** (github.com → Settings → Developer settings →
Fine-grained tokens):

- Repository access: only `World-Cup-2026-Gap-Index`
- Permissions: **Contents → Read and write** (the dispatches API maps to Contents-write for
  fine-grained PATs), Metadata → Read-only (mandatory, auto-added)

Contents-write also lets the token push code — that's inherent to `repository_dispatch` and
unavoidable, which is why it's scoped to a single repo and lives only in the cron service.
Set an expiry and rotate it. A classic PAT with the `repo` scope works too but is broader.

## The service (cron-job.org, free)

New cronjob:

- **URL**: `https://api.github.com/repos/tj-chakravarthy/World-Cup-2026-Gap-Index/dispatches`
- **Method**: `POST`
- **Headers**:
  - `Accept: application/vnd.github+json`
  - `Authorization: Bearer <PAT>`
  - `X-GitHub-Api-Version: 2022-11-28`
- **Body**: `{"event_type":"poll-results"}`
- **Schedule**: every 15 min, hours `17–23` and `0–7` UTC (the match window — full-times
  land ~18:00–06:00 UTC; set the account timezone to UTC). Outside that window nothing
  plays, so don't bother pinging.
- Turn on "save responses" to confirm `204`s.

Any scheduler that can POST with custom headers works (a VPS `curl` cron, etc.); cron-job.org
is just the free no-server option.

## Test it

```bash
curl -sS -o /dev/null -w "%{http_code}\n" -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer $GH_PAT" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  https://api.github.com/repos/tj-chakravarthy/World-Cup-2026-Gap-Index/dispatches \
  -d '{"event_type":"poll-results"}'
```

Expect `204`. Then check the Actions tab for an "Update Predictions (live)" run with event
`repository_dispatch`, and — if a match has resolved — a `gapindex-bot` "data: live update"
commit a few minutes later.

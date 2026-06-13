# Upstream-API contract fixtures (ER-02)

Recorded, **scrubbed** vendor responses — one file per `{source}/{endpoint}`. They
pin the *shape contract* each ingestion `transform()` depends on, so a vendor
changing the payload out from under us (a field rename / renest / retype) fails CI
instead of silently corrupting data at the next 4 AM run.

- **Asserted by:** `tests/test_upstream_contracts.py` — fully **offline**, no live
  AWS/vendor calls, gates in CI.
- **Refreshed by:** `deploy/refresh_upstream_fixtures.py` — the only path that
  touches live APIs. Matthew runs it in his terminal with creds. The diff it prints
  vs. the committed fixture **is the drift report**.

## Provenance

| Source | Endpoint(s) | How it's maintained |
|---|---|---|
| **whoop** | recovery, sleep, cycle, workout | live-refreshable (`fetch_day` returns raw endpoint JSON) |
| **withings** | measures | live-refreshable (`fetch_day` returns the raw `body`) |
| **garmin** | daily | live-refreshable (`transform` is passthrough; `fetch_day` output *is* the contract surface) |
| **strava** | activity | `--from-file` only (its `fetch_day` returns already-normalized output, not raw vendor JSON) |
| **hae** (Apple Health) | blood_glucose, blood_pressure | `--from-file` only (webhook-push; no pull endpoint) |

**Bootstrap note (2026-06-09):** the initial fixtures were seeded offline from the
sample payloads in `tests/test_ingestion_transforms.py` (the blind-spot-sweep
`transform()` tests) plus the documented HAE webhook shape — no secrets required to
get a first green suite. The `hae/*` and `strava/*` fixtures are **synthetic but
shape-accurate** until replaced by a real scrubbed capture via `--from-file`. All
fixtures are token/PII-free by construction; `test_fixtures_have_no_secrets` enforces it.

## Refresh workflow

```bash
# Dry-run: show drift for every live-refreshable source (no writes)
python3 deploy/refresh_upstream_fixtures.py --date 2026-06-08

# Refresh + write one source
python3 deploy/refresh_upstream_fixtures.py --source whoop --date 2026-06-08 --apply

# Install a hand-captured raw payload (strava / hae): scrubs + diffs first
python3 deploy/refresh_upstream_fixtures.py --source hae --endpoint blood_glucose \
    --from-file ~/captured_payload.json --apply
```

A non-empty diff on refresh means the vendor drifted — review it, then re-run with
`--apply` to re-baseline and let the contract test reflect the new shape.

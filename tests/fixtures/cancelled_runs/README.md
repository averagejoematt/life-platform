# `cancelled` CI/CD runs — the two live specimens (#3530)

Both files are the verbatim response body of

```
gh api repos/averagejoematt/life-platform/actions/runs/<id>/jobs?per_page=100
```

captured read-only on 2026-09-05 — the exact call `scripts/ci_run_verdicts.py::fetch_run_jobs`
makes, so the fixture is the wire and not a hand-written approximation of it. Only the JSON
formatting was normalised (2-space indent, sorted keys) so a re-capture diffs cleanly.

| file | run | main @ | rollup | what its jobs actually say |
|---|---|---|---|---|
| `run_33843742114_cancelled_carries_failure.json` | [33843742114](https://github.com/averagejoematt/life-platform/actions/runs/33843742114) | `b248a70c` (2026-09-04T06:17:16Z) | `cancelled` | **`test / Unit Tests` = failure** (failing step: `Test coverage gate (regression floor, ADR-080)`); `Deploy` = cancelled with 0 steps |
| `run_33937903965_cancelled_superseded.json` | [33937903965](https://github.com/averagejoematt/life-platform/actions/runs/33937903965) | `e6daab64` (2026-09-05T02:01:59Z) | `cancelled` | every validation job `success`; `Deploy` = cancelled with 0 steps — a genuine supersession |

The two rollups are **identical**. The only difference is in the jobs, which is exactly why
`check_main_green.py` and `check_ci_warnings.py` may not decide from the rollup: the first run
is a red main that both readers walked past to an older `success`, the second is a real
non-verdict that must still be skipped.

## Why a `cancelled` rollup happens at all here

`ci-cd.yml`'s **workflow**-level concurrency group has carried `${{ github.run_id }}` since
#2009 (`ci-cd.yml:129`), so it is unique per run — nothing supersedes a CI/CD run any more.
The `deploy` job keeps its own group `ci-cd-deploy-${{ github.ref }}` (`ci-cd.yml:861-862`),
and GitHub allows one pending entry per group: a newer run's Deploy **evicts** the older run's
still-pending Deploy. The evicted job concludes `cancelled`, which rolls the whole run up as
`cancelled` no matter what the validation jobs above it concluded. Two merges inside one
deploy-lease window is every merge-train session.

Adjacent proof of the mechanism, all three read live from the `Deploy` job of each run:

```
33843452894  Deploy  started 2026-09-04T06:24:21Z  completed 06:29:11Z  cancelled
33843742114  Deploy  started 2026-09-04T06:29:10Z  completed 06:33:51Z  cancelled
33844077590  Deploy  started 2026-09-04T06:33:51Z  completed 06:40:21Z  failure
```

Each Deploy is evicted at the second the next run's Deploy takes the slot. All three runs had
`test / Unit Tests` = failure; the third's Deploy concluded `failure` rather than `cancelled`,
so that run rolled up `failure` and both readers saw it. The two before it rolled up
`cancelled` and were invisible to both. Same defect, three runs, one night.

## Re-capturing

These runs are immutable history, so the fixtures should not need refreshing. If GitHub ever
changes the payload shape, re-capture with the command above and re-run
`pytest tests/test_cancelled_not_superseded_3530.py` — the predicate reads only `name`,
`conclusion` and `steps[].conclusion`.

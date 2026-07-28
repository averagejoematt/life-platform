# HANDOVER — #1653: the flat lambdas/ root is gone (132 → 0), and what the move exposed — 2026-07-28 (Day-2 session)

> Instruction thread: **solo opus session, owned main** — one task, picked off
> `backlog_next.py`'s stored rank: #1653, the packaging move, as its own full-headroom
> session. Explicitly NOT a Fable session (the banked `/fullreview` partial's delta review
> is due on/after 2026-08-02 and its independence depends on nobody finishing it early).
> Standing approval given in-session for merges and the deploy-gate approval.

## Shipped (merged AND live; main GREEN at f6870489)

- **#1653** (PRs **#1899** + **#1900**) — **`lambdas/` is packaged by domain.** 132 loose
  `.py` at the root → **0**. Nine domain packages (`common` infrastructure, `ai`
  inference, `experiment` scientific apparatus, `coach`, `health`, `training`, `content`,
  `privacy`, plus the existing `ingestion`/`operational`/`intelligence`/`web`). 1,570
  import statements rewritten across 499 files by a deterministic codemod, landed as 11
  verified commits (slice 0 groundwork, 9 move slices, 1 docs/ADR). **ADR-146** records the
  taxonomy and the failure catalogue.
- **Live**: all 99 Python Lambdas redeployed 18:58:36–19:06:29Z on exactly two bundle
  shapes — 97 tree, 2 MCP (`life-platform-mcp` + `mcp-warmer`) — the designed split,
  verified rather than assumed.

## What the move exposed — the actual value of the session

Every one of these fails **soft** (a warning, an empty registry, a green test), and
**pytest caught none of them**. `tests/conftest.py` deliberately puts `lambdas/` AND every
subpackage on `sys.path` so legacy flat imports keep resolving — exactly what lets a stale
import pass the suite and `ImportError` in production. Slice 0 therefore added
**`scripts/verify_bundle_boot.py`**: it stages the real bundle and imports every module in
a subprocess whose only first-party `sys.path` entry is the bundle root — i.e. `/var/task`.
That, not the suite, found most of the below.

1. **The unit suite was making REAL Bedrock calls.** Eight tests stub inference via
   `sys.modules["bedrock_client"]`. Once code says `from ai import bedrock_client`,
   CPython's `_handle_fromlist` prefers the parent package's already-bound attribute and
   never consults `sys.modules` — order-dependent, so green alone and live-calling in the
   full suite. They failed only because CI has no credentials; **with** credentials they
   would have passed while billing Bedrock. Fixed via `tests/bundle_stubs.py` (23 sites,
   14 files).
2. **Three config loaders silently degraded to empty.** `persona_registry`, `persona_core`
   and `coach_stance` resolved `dirname(dirname(__file__))/config/…`. They prefer S3 and
   treat a missing local file as a soft miss, so nothing raised — it surfaced as **44 tests
   asserting coaches had no names**. `lambdas/common/repo_config.py` now searches upward;
   7 more modules with the same pattern were converted as their slices landed.
3. **Two data-file loaders resolved to nothing inside the bundle.** `meal_grouper` and
   `redirect_spotcheck` read files `build_bundle` stages at the BUNDLE ROOT *because* they
   "look alongside their own module" — no longer the same place. Invisible locally (the repo
   has a real `config/`); only the bundle came up empty. Now covered by a test that drives
   the loaders from a staged bundle with the repo tree off `sys.path`.
4. **`session_postflight`'s asset canaries would have cried wolf on every deploy.** They
   match zip namelists EXACTLY, so the guard against silently-corrupt deploy assets would
   have reported false missing modules. Its own unit tests stayed green — they build
   synthetic zips from the same literals.
5. **`ci/lambda_map.json` had 9 dead paths** predating this work (four orphan top-level
   sections carrying flat handler strings live stopped matching months ago). Purged in slice
   0, plus `tests/test_lambda_map_paths.py`, which then found a 10th a hand audit had missed.

**Coverage never shrank.** Four path-keyed registries had to move in lockstep —
`ci/lambda_map.json`, `ci/lambda_s3_paths.json`, `mypy.ini`, and `tests/mypy_clean_set.py`,
whose `CLEAN_DIRS` globs are **non-recursive** (omitting a package silently drops its
modules from the mypy gate). Where a directory isn't clean yet, moved modules are listed
individually in a new `CLEAN_FILES` rather than dragging ~40 unrelated modules and 39
pre-existing errors in. `coach/` joined the gate outright; its one debt-carrying module was
fixed, not denylisted.

## Gotchas hit (the expensive ones)

- **`check_doc_index.py --strict` is CI-ONLY — and it red main after the merge.** Moving an
  engine's source file trips the engine-doc source-drift gate (14 violations). The full
  suite, black, ruff, flake8, bundle-boot and `cdk synth` all passed locally through all ten
  slices because none of them run `--strict`. **This was a documented reflex I had and still
  missed.** Fixed by PR #1900 — and re-verified rather than date-bumped: import-block growth
  shifted line numbers in 4 files, and **2 of the 10 line citations had genuinely drifted**
  (`ai_calls.py:1214→1215`, `coach_stance.py:23-69→24-70`). A date bump alone would have
  greened the gate over two wrong citations — precisely the failure the gate exists to prevent.
- **A stranded `production` approval silently blocks EVERY later pipeline.** A run from
  03:06Z sat `waiting` at the gate for ~15h; `cancel-in-progress: false` meant the #1653
  merge's run queued behind it forever (`pending`, 0 jobs). I mis-read this as the known
  phantom-concurrency class and cancelled a run before finding the real cause.
  `check_main_green.py` reads the latest COMPLETED run, so main looked green throughout.
  Filed as **#1901**.
- **CodeQL re-attributes pre-existing alerts on large diffs.** #1899 showed "7 high — new
  alerts in code changed by this pull request". All 7 lines are byte-identical to
  `origin/main` and map 1:1 to alerts already open (#69/#118/#97/#26/#27/#28/#112). Analysis
  posted on the PR so nobody re-derives it.
- **`Deploy` needs `[reconcile, plan]`, NOT `test`.** The full unit suite does not gate a
  deploy (deliberate, ADR-117 — the deploy-critical lane gates). I waited for it by hand;
  worth knowing the safety of that gate depends on someone choosing to.
- **The public methods page nearly shipped a broken provenance string.** `methods_registry`
  stamps `fn.__module__`, which `provenance_popover.js` renders as
  `${module}.py::${function}` — unfixed it would have published
  `common.stats_core.py::pearson_r`, a file that does not exist. Verified live post-deploy:
  renders bare names.

## Verified

- **8,061 tests** pass (from 8,055 at baseline); tree bundle **290/290** and mcp bundle
  **328/328** modules import with only the bundle root on `sys.path`; all 9 CDK stacks synth;
  the staged asset carries all 15 packages + 3 root data files; **99/99 Python handler
  strings** from the synthesised templates resolve against the staged bundle (the other 2 are
  Node runtimes). black/ruff/flake8 clean.
- **Live post-deploy**: `/api/vitals|status|labs|methods|vacation_fund` all 200 with real
  payloads; `/api/methods` renders bare module names; **0 Lambda errors** fleet-wide in every
  window since deploy; full CI/CD green through Deploy → integration checks (I1/I2/I5) →
  visual + AI-vision QA → smoke, rollback skipped.
- **Honest limit:** **17 of 99** functions have actually cold-started on the new bundle. The
  other 82 are on daily/weekly crons — statically covered, not yet dynamically.

**Build beat:** `2026-07-28-the-tree-that-hid-eight-live-bedrock-calls`
**Docs:** ADR-146 (new) + `docs/DECISIONS.md` index/count, `CLAUDE.md` (packaging convention
+ ADR range), `docs/ARCHITECTURE.md`, `docs/REPO_STRUCTURE.md`, the 5 `docs/engines/*`
re-verifies, and 174 stale path references swept across 43 current-truth files. Dated
artifacts (CHANGELOG, `reviews/`, `restart/`, handovers) and the SHA-sealed
`channel_divergence_prereg.json` deliberately keep their flat paths — they record what was
true when written.
**Decisions:** ADR-146 filed (lambdas/ packaged by domain; moving code must never reduce coverage).
**Main:** green (f6870489)
**Incidents:** 1 row added — the 15h stranded `production` approval that silently blocked
every CI/CD run on main (no outage, but it blocked the deploy path and cost investigation time).
**Stash/hooks:** clean
**Closures:** #1653 commented (realized, with the 17/99 cold-start caveat stated)
**Backlog:** Now live at 8 actionable; no promotion needed. `later_staleness` printed nothing
— no stale `Later` calls to make.

## Residual / next picks

1. **#1891** — `/method/game/` names a real public clinician (Dr. Peter Attia) as a pillar
   owner on a live page. Top of the stored rank (5.00) and the only one involving a real
   named person. Start here.
2. **The reset-leak cluster — #1895, #1898, #1894** — one root cause (cycle-11's reset didn't
   fully propagate). Worth one wave: they share fixtures and the `restart_pipeline.py` sync step.
3. **The ai-integrity pair — #1896, #1897.** Note **#1896 (a coach fabricating a graded
   verdict from zero data) is a plausible descendant of gotcha 1 above** — coach output paths
   have been passing tests without exercising inference. First place to look.
4. **#1892, #1893** — citation resolution and the calibration denominator.
5. **Day-2 cold-start watch — `not-work` — standing ops watch, not a backlog item.** 82
   functions first cold-start on the new bundle at the 16:30–17:00Z compute chain + daily
   brief, and hypothesis-engine Sunday 19:00Z. An `ImportModuleError` would be a hard failure
   with alarms wired, not a silent degrade — but look explicitly.
6. **#1901** — the stranded-approval blind spot (filed this session).
7. **#1902** — 99 open CodeQL alerts on main, mostly clear-text logging in `setup/*_auth.py`
   (filed this session).
8. **Fable delta review — `not-work` — a scheduling constraint, not a task.** Due on/after
   **2026-08-02**; do not let another model finish the banked `/fullreview` partial.
9. **Worktree prune — `not-work` — housekeeping, no issue warranted.** `git worktree list`
   shows ~130, many stale and many in-repo under `.claude/worktrees/` (pollutes scanners).
10. **Owner-gated, unchanged — `not-work` — owner decisions, not session-startable:** OSS
    publish one-liner, vocal backfill, #1738 / #1571 / #1114, Dependabot.

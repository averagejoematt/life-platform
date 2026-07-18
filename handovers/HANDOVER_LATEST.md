# HANDOVER — Cycle-7 reset (genesis 2026-07-18) as a live drill + hardened the pipeline against two one-command gaps — 2026-07-18

> Instruction thread: run a REAL end-to-end experiment reset re-anchored to genesis
> Saturday 2026-07-18 (cycle 7) to prove the pipeline still works as one command and the
> site's Day-1 pre-start behavior is correct; then HARDEN — if any step needed a manual
> fix/re-run/missing deploy/stale count, fix `restart_pipeline.py` so the next reset is
> genuinely one command, filed as a PR with a regression guard. Driver granted merge +
> deploy authority INCLUDING running `restart_pipeline.py --apply` and its live-DDB steps.

## What shipped — PR #1287 (MERGED `6ff76722`, squash)
Full reset to **genesis 2026-07-18 (Saturday), cycle 6→7, baseline 315.65 lbs** (the latest
real Withings weigh-in — genesis is +1d so had no genesis-day reading; used
`--override-weight-lbs 315.65`, the honest latest value, not an arbitrary round number).
Ran `restart_pipeline.py --genesis 2026-07-18 --override-weight-lbs 315.65 --apply --sync-site`.
The site is correctly in its **PRE-START COUNTDOWN** state (verified while today was still
2026-07-17 PT): `pre_start=true`, `day_n=0`, character zeroed (Level 1 Foundation), home
hero "1 DAY TO GO — THE EXPERIMENT BEGINS TOMORROW, SATURDAY, JULY 18", cockpit "STAGED —
the instruments light with Day 1's data". Weight DEFERRED to the Day-1 weigh-in (honest per
ADR-104 — the baseline 315.65 is in the data layer / `/api/journey`, but the reader pages
wait for a real weigh-in). It auto-flips to Day 1 on genesis via `day_n()`.

## The drill surfaced TWO "one-command, zero-manual-steps" gaps — both fixed + guarded
The first `--apply` exited **1** (not 0 — the background wrapper's `echo EXIT=$?` masks
python's real exit; read the actual `EXIT=` line). Root causes:

**1. `/journal/posts.json` served a `"tombstone": true` marker → rendered gate FAILED (39/40).**
`restart_leadin_pages` OWNS + rebuilds that manifest and runs EARLY, but
`restart_site_copy_sync.ORPHAN_S3_FILES` still listed `generated/journal/posts.json` + the
`site/` sibling as writer-less "orphans to tombstone-blank" — and site_copy_sync runs LATER,
re-tombstoning the fresh 1-post manifest every reset. (The **semantic** gate PASSED because
it iterates `posts[]` → empty is vacuously clean; only the **rendered** gate greps the raw
envelope.) Fix: dropped both journal keys from ORPHAN_S3_FILES; made leadin_pages the
*unconditional* owner (writes an honest empty `{"posts": []}` on zero installments instead of
early-returning). Guard: `test_reset_orphan_list_excludes_owned_keys` (non-vacuous — fails on
the pre-fix list).

**2. The reset never ran `sync_doc_metadata.py`.** Moving the genesis left the genesis/cycle
literals in `docs/SCHEMA.md` + `CLAUDE.md` (and the maintained `site_api_common.py` counts)
stale → a manual `sync_doc_metadata.py --apply` was required, and skipping it reds
`test_platform_stats_truth` on the very commit of the reset artifacts (the PLATFORM_FACTS
class). `restart_docs_update.py` is a different mechanism and doesn't own those literals. Fix:
folded `sync_doc_metadata.py --apply` in as the final sub-script (dry-run safe: run_step strips
`--apply` → no-flag check, exits 0 even with stale literals). Guard: `test_build_sub_scripts_sequence`.

**Re-ran the pipeline with the fix (`--skip-deploy`, a re-converge): clean exit 0**, journal
manifest live, all gates pass, the previously-skipped `fix_prologue` post-verify hook ran.

## Verification (independent, not just the pipeline's own exit)
- Rendered gate **40/40**, semantic gate **7/7** (pre-start assertions), truth gate honest-SKIP
  (budget tier 1 — reader-truth AI paused; not a silent green).
- `smoke_test_site.sh` **82 passed / 0 failed**.
- render-QA agent **PASS** both home + cockpit (countdown, zeroed character, no prior-cycle
  leak, mobile clean). Its one flag (315.6 not shown) is correct honest deferral, not a defect.
- Live `/journal/posts.json` = 1-post manifest (no tombstone); `/api/journey` pre_start=true.
- Offline suite CI gate `pytest -m "not integration"`: **5253 passed, 0 failed**. The lone
  full-run failure is `test_i16` (integration-marked, CI-EXCLUDED) — a known flake at the
  UTC/PT genesis boundary (its `today<genesis` skip uses UTC, already rolled to genesis day).
- Constants + CYCLE_GENESES + all stacks deployed live by the reset's own `cdk deploy --all`.

## Post-merge state (watch on wake if still in flight)
- CI/CD runs on **push-to-main** (not PR) — Lint/Test/Plan on `6ff76722` was in flight at wrap
  (locally pre-verified green: black/ruff clean, suite green, no new IAM → Plan green).
- Site deploy triggered on `6ff76722`. **Superseded-skip watch** ([[reference_site_deploy_superseded_skip]]):
  site content is ALREADY live-correct (the reset's `--sync-site` synced it); the merge's
  site-deploy just rolls `version.json` to `6ff76722`. If a reconcile commit lands right after
  and site-deploy SKIPS, run a manual `bash deploy/sync_site_to_s3.sh`. No reconcile commit had
  landed at wrap (docs pre-synced by the folded sync_doc_metadata step, so none expected).
- `site_api_common.py` test_count 3783→3784 is committed but the LIVE lambda still serves 3783
  (a non-reader-facing doc-count; corrected on the next fleet/site-api deploy — not worth one now).

## Left for Matthew (unchanged, NOT deploys)
- #1266 DDB cycle re-stamp, #1265 Elena held-draft regen. The cycle-7 reset did NOT supersede
  them (history heal + editorial AI budget remain their own work).

## Residual / next
- **SECONDARY (Next milestone, 19 stories) HELD by design** — the reset + hardening was a full
  session (two real bug-fixes with guards + a live reset drill). Same worktree fan-out playbook
  when resumed; SERIALIZE the check_doc_facts.py cluster (#1232 monthly_cost + #1205
  ARCHITECTURE.md). Candidates: #1207 (floats→Decimal, solo), #1221 (rate-limit IP spoofing,
  security), #1216/#1217 (supplement citations), #1215, #1210, #1218, #1219.

**Build beat:** `2026-07-18-the-reset-that-caught-itself` — the cycle-7 reset drill, run to prove
the machine still resets in one command, found and fixed two bugs in its OWN reset (a manifest an
early step owns being re-tombstoned by a late step; the reset not reconciling its own doc literals).
Merged + deployed. Distill per `docs/content/BUILD_DISPATCH_CHECKLIST.md` at next content pass.

Prior session: `handovers/HANDOVER_2026-07-18_NextSlice2.md`.

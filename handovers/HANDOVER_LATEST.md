# HANDOVER — Green main, chronicle prequels restored + cycle-6 pre-registration, repo → private — 2026-07-13

> Instruction thread: "what to work on" → which surfaced a **red main** and cascaded:
> unblock main → "chronicle is missing the prequel articles" → re-seed + publish the
> cycle-6 pre-registration (Option A: draft-for-review, approved) → "should I make my
> git repo private?" → Matthew flipped it, "run the doc/memory cleanup." Standing:
> "I approve all merges and deploys" (all commits pushed directly to main with approval).

## The arc of the session

Opened on "what to work on"; CI answered — **main had been red since the cycle-6 reset**,
two gates failing. Fixing that led straight into the reset's other loose ends (the
tombstoned chronicle prequels, the un-published cycle-6 pre-registration), and then a
strategic decision (repo visibility) with its own cleanup tail.

## Shipped (all committed + pushed to main; live surfaces verified)

**Unblocked main (4 commits):**
- **`6f843660`** — `test_genesis_preregistration` hardcoded cycle-5 dates (`pred_20260712_`
  prefix, `2026-07-11` artifact date); the reset moved genesis to 2026-07-13. Now derives
  `GENESIS_COMPACT`/`GENESIS_MINUS_1` from `seeder.EXPERIMENT_START_DATE` → **reset-proof**.
- **`c1cb557a` — #1188** — `restart_verify_rendered._old_genesis_tokens` now **waives the
  outgoing-genesis ISO-literal token when it equals today** (future-genesis/pre-start reset:
  outgoing genesis == today's real date, so every legit `as of`/`night_of`/`/api` freshness
  stamp tripped it — 8/40 URLs false-failed the reset). Keeps the prose forms (catch a real
  chronicle leak). `Fixes #1188`.
- **`54a1718c`** — killed a wall-clock flake in my OWN #1188 test: it used `date.today()`
  as the outgoing genesis, which == `EXPERIMENT_START_DATE` on genesis day, so CI (running
  2026-07-13) hit the current-genesis early-return and got `[]`. Made `today` injectable;
  pinned both branches to fixed dates. (Classic now-based-fixture time bomb.)
- **`6ad83c8b`** — hand-reconciled `test_count` 3641→3644 (`[skip-reconcile]`).
- **`a2b45b9b`** — corrected CONVENTIONS §4c + the ci-cd reconcile error hint: the org-only
  `bypass_pull_request_allowances` doesn't exist on a personal repo.

**Restored the chronicle prequels** (the reset tombstoned `journal/posts.json`; the #1188
false-fail exited the pipeline nonzero so `restart_leadin_pages` never ran):
- Ran `restart_leadin_pages.py --apply` → Part I **"Before the Numbers"** (genesis−6 =
  2026-07-07) re-rendered. Then re-seeded + published Part II (below). posts.json now = 2
  posts; `/journal/posts/week-01/` + `week-02/` + `/story/chronicle/` all 200.

**Re-seeded + published the cycle-6 pre-registration (`ecff46b9`):**
- `seed_genesis_preregistration.py --apply` → **16 board predictions + 2 hypotheses** to
  DDB, grounded in the corrected **314 lb / 2026-07-13** plan (Bedrock-generated, dry-run
  reviewed + Matthew-approved before publish).
- `publish_genesis_preregistration.py --apply` → **"The Plan, On the Record"** live as
  Prologue · Part II (dated genesis−1 = 2026-07-12).
- **ADR-104 bug fixed in the same commit:** `build_hypotheses` evidence + the
  `physical_coach` fallback hardcoded the OLD 300.8 lb baseline instead of reading
  `user_goals.json` — after `--override-weight-lbs 314` those would have put the wrong
  baseline on the permanent record. Now derived from goals.

**Repo → PRIVATE cleanup (`896eddba` + memory):**
- Matthew flipped `averagejoematt/life-platform` to private (0 forks/stars → nothing
  detached; GitHub Pages mirror now **404/unpublished** — exposure fully closed).
- Corrected the live docs' "repo is public" claims (DISASTER_RECOVERY visibility row =
  PRIVATE; ACCOUNTS/CONTINUITY/AWS_ACCESS/TESTING/NEW_MACHINE_BOOTSTRAP reasoning lines)
  **while keeping every privacy discipline** (history was public through today + site
  public + reversible). Left historical review docs/CHANGELOG untouched.
- New memory `project_repo_visibility.md`; updated R22 + sensitive-content guidance.
  Noted the completed `repo-private` leg on **#1029**.

## Verification
- Full suite green in CI on `54a1718c` + `a2b45b9b` (`Unit Tests ✓`, 5079 passed). The two
  earlier `failure` runs (`c1cb557a`, `6ad83c8b`) were the wall-clock flake, superseded.
- `ecff46b9` (deploy/ ops scripts) is path-filtered out of ci-cd; tests verified locally
  (`test_genesis_preregistration` 11 passed). `896eddba` (docs) → Docs CI ✓.
- Live: posts.json = 2 posts; both prequel pages + chronicle hub 200; repo `visibility:
  private`; Pages mirror 404.

## Gotchas hit
- **Now-based test fixtures are time bombs** — `date.today()` in a test collided with
  `EXPERIMENT_START_DATE` on genesis day; green locally (07-12), red in CI (07-13). Inject
  the date. ([[reference-golden-tests-wallclock]] class.)
- **#1173 reconcile bot / personal repo** — the org-only PR-bypass list doesn't exist on a
  User-owned repo; the fix Matthew applied was turning OFF "require a pull request" on main.
- **Prereg is EXPERIMENT_SCOPED** — a future `restart_pipeline.py` wipes it; re-run
  `seed --apply` + `publish --apply` after any reset (the reminder prints on every run).

## Residual / next-picks
- **#1173 now unblocked** — Matthew set the branch-protection; the reconcile bot can push.
  First real proof is the next PR that shifts a doc-sync literal (this session had none to
  exercise it).
- **#1029** remaining hardening legs: Identity Center, ACCOUNTS estate rows, FileVault,
  registrar. `repo-private` leg done.
- Monday post-genesis `restart_verify.py` + the 07-13 drift sentinel (→ close #342/#717).
- Matthew queue: **#1187** (voiced show-open needs a music bed), **#1114** portraits,
  **#741** career artifact (build-in-public; note: private repo now — flip back if the
  code is wanted as a portfolio piece), **#1148** + coach traits.
- Budget tier 1 ($82/$85).

**Build beat:** `chronicle-prequels-restored` — see `site/story/build/beats.json`.
**Docs:** CONVENTIONS.md §4c + docs visibility corrections (DISASTER_RECOVERY, ACCOUNTS,
CONTINUITY, AWS_ACCESS, TESTING, NEW_MACHINE_BOOTSTRAP) shipped in-session; wiki checkers
green at wrap.

Prior: `handovers/HANDOVER_2026-07-12_PodcastNoTouchAndCycle6Reset.md`.

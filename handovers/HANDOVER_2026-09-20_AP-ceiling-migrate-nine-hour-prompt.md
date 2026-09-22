# Handover — Session AP: the ceiling that killed green jobs, the migrate bug found by running it, and the nine-hour permission prompt (2026-09-20 19:41 → 2026-09-21 ~08:45 PT)

**Fable, autonomous, standing merge + deploy authority (fleet, MCP, site-api, CDK).** The brief set 57 → ≤48 with
a 06:00 PT wrap. The honest number at wrap is **54 open in all / 51 outside the Roadmap milestone** — the target
was not met, for the same structural reason as AO: most of what merged tonight closes on a next occurrence (a
Sunday weekly, a nightly, a reset, an owner commit). Gross: **4 closed on live proof (#3918 #3982 #3700 #4011),
1 filed (#4011, closed the same session), 0 auto-closed.** The wrap ran ~2.5 h past the deadline because the
session sat 9 h on a permission prompt (below). **The owner has not ruled on #3753 — v0.2 stays `ACTIVE = False`.**

---

## The nine hours (05:23Z → 14:30Z), decoded — owner-confirmed

The checkpoint-1 deploy was issued as ONE compound line — `{ echo …; bash deploy/deploy_fleet.sh; bash
deploy/deploy_lambda.sh life-platform-mcp mcp_server.py; bash deploy/deploy_site_api.sh; } > log 2>&1` in the
background — and it matches no `permissions.allow` rule: `.claude/settings.local.json` allows the bare string
`bash deploy/deploy_fleet.sh` only (what `/fewer-permission-prompts` had seen), `deploy_lambda.sh` and
`deploy_site_api.sh` have no rule at all. The harness waited on the prompt; the four Wave 2 lanes (their own
allowlisted commands) finished at 05:53–06:21Z and their CI concluded by 06:18Z; the Mac never slept (Caffeinated).
The command started at 14:30:55Z, the minute the owner approved it. **The brief's autonomy grant does not reach
the permission layer.** Reflex (memory + the CLAUDE.md block): invoke deploy scripts BARE, exactly as the allow
rule spells them — the final fleet deploy tonight was a bare `bash deploy/deploy_fleet.sh` and prompted nothing.
Proposed to the owner (ask-first, permissions — diff in the chat): prefix rules `Bash(bash deploy/deploy_fleet.sh*)`,
`Bash(bash deploy/deploy_lambda.sh *)`, `Bash(bash deploy/deploy_site_api.sh*)`, `Bash(bash deploy/reject_deployment.sh *)`.

## What shipped — 15 PRs merged, every one `Refs`, zero trailers (each PR's commits grepped before arming)

**Driver PRs:** #4010 (#3918 `--only-note` + `--allow-calls`) · #4012 (#4011 the ceiling re-derive 18 → 22) ·
#4016 (#3918 the migrate keying bug) · #4021 (main's two reds — the hevy gate off `fromisoformat`,
`docs/engines/HYPOTHESIS.md` re-verified with 12 AST-derived spans). **AO's armed pair:** #4007 (#3005
fix-forward, hooks installed in the main checkout at 04:0xZ) · #4005 (#3621 box 4). **Lane PRs:** Wave 1 —
#4009 (#3700) · #4013 (#3712) · #4014 (#3971) · #4015 (#3615 boxes 1–3); Wave 2 — #4017 (#3552) · #4018 (#3607) ·
#4019 (#3599 boxes 1–2) · #4020 (#3621 boxes 2+5, a `site/**` change: `protocols.json` 1.2.0 live with
`spawned_by`).

**Closed on live proof (4):** #3918 (one Haiku call re-extracted the 06-23 note; `--migrate --apply`;
`occurrence_mismatches 1 → 0`) · #3982 (`[ BORN ] citation-network-check.yml` on the first cron-freshness run
after #4005, nothing filed) · #3700 (`draft_custom` → `cardio_cues: 1`, the stored block reads
`Last: 2.99 mi in 1:00:00 (3.0 mph) — 20 Sep`) · #4011 (seven required jobs green at 14–21 min on the 22-min
ceiling).

## Deploys — every function on ONE tip, read from `build_info.json`

- **Checkpoint 1 (14:30–14:44Z, after the prompt):** fleet 106/0 from `3f9f7388`, then MCP + site-api from
  `6c4b24f9` — SPLIT, because I `git pull`ed mid-run; fleet re-run 106/0 from `6c4b24f9` to unify.
- **Checkpoint 2 (14:58–15:05Z):** fleet 106/0 + MCP + site-api from `877e87a9` (postflight OK ×3).
- **Final (15:07–15:13Z):** bare `bash deploy/deploy_fleet.sh` from **`b047216a`** (#4021's tip) — 106 updated /
  0 failed, MCP + warmer + site-api + site-api-ai included. Read back from the deployed zips: `life-platform-mcp`,
  `life-platform-site-api`, `episode-detect`, `hevy-routine-cron`, `life-platform-qa-smoke` all `b047216a ·
  built_at_source commit · dirty=false`. **CDK: no stack deployed tonight** (no `cdk/` change merged).
- **Site:** #4020's merge auto-deployed `site/config/protocols.json` (run 35615359410 — "Deploy public site" and
  the smoke both `success`; the visual + AI-vision job was still in progress at 15:1xZ — the next session reads
  its verdict; a revert would show as the workflow's rollback job).
- **Verified by content after the site-api deploy:** `/api/calibration` `interval_forecasts.n` **80 → 80**,
  strata unchanged (#4013's split moved no historical row); `/api/status` garmin comment now registry-derived
  (`PAUSED in the source registry — … Last record: 98d ago`, was "stopped 97d ago. Check auth/webhook") (#4015);
  `/api/hypotheses` `min_days_per_arm: 5` (#4017); `manage_hevy_routine dry_run` returns
  `prescription_audit.verdict = refuse`, `error_code = SUBTRACT_ONLY_VIOLATION` on the #3927 specimen (#3971).

## Leases — 20 rejected by name, zero blanket

By hand: 35554444488→`4b498399e` (AO's docs push) · 35558266000→`e18d5e3ba`. By the session steward (a loop that
rejects only runs whose head is a main commit descended from the session base, naming sha + subject):
35559147640→`8fa232f58` · 35559198041→`c2b75e5b8` · 35559446055→`d1afb022e` · 35559461424→`d9fc6a925` ·
35559501162→`aa566c55f` · 35560741739→`5d22d00a6` · 35560801596→`863ccf4c1` · 35561354831→`045f3b120` ·
35561415027→`f0bdd82ce` · 35562703155→`00a3cab4c` · 35562746589→`341860e0a` · 35564327168→`856a51c6a` ·
35564375803→`3f9f73886` · 35565566258→`325256970` · 35565622175→`1c0b0f956` · 35612741429→`ab1c4bb5d` ·
35612840326→`d32e073e9` · 35612751428→`6c4b24f91`. The runs on `b667ed342`, `877e87a95` and `b047216a1` were
still in flight at wrap — the steward was still running; the next session rejects any it did not catch, by name.

## Found by measuring, not by reading

- **The required job's ceiling, not lane load.** #4007's `Collect + deploy-critical + format` rerun SOLO: every
  step green, `Complete job` at 19m55s, rendered `cancelled`. `scripts/check_job_timeout_headroom.py` already read
  RED (p95 17.59 × 1.2 = 21.11 vs 18). AO's ×10 cancellations were this, and a rerun cannot fix it. #4012
  re-derived 22 from the script's number, re-measured the posture (1055 s, n=13) and re-froze the ratchet with
  the date; then seven required jobs passed at 14–21 min. The lane has no growth budget (epic #3493 line).
- **`--migrate` was keyed by occurrence alone.** Another block's occurrence 0 (Rowing, Elliptical) shadowed the
  Treadmill's, so the archived prior read "no stored extraction carries this note text" on 09-10. Found by
  running the owner-approved migration, fixed with a mutation-controlled test (#4016).
- **Four PRs moved the gate-census ratchets in one night** (#4005 #4014 #4015 #4020; #4019 too). Each re-merge
  was measured on the merged tree, never incremented: 669 → 670 → 672 → 673 → 674 → 675 → 676 / proven 119 → 125.
  A `git checkout --theirs` on `tests/conftest.py` during #4020's re-merge DROPPED the lane's own
  `_PREMERGE_EXTRA_FILES` entries — rebuilt as the union; check for that whenever conftest conflicts.
- **The commit-msg hook (#4007) requires a Conventional Commit subject on MERGE commits too** — `chore(merge):
  origin/main into <branch> — …` is the form that passes.
- **The ISO-parse registry is shrink-only (65)**: a new `fromisoformat` site cannot be registered, only migrated
  (`common.pacific_time.parse_day_key` for DATE# day keys).
- **`gh pr merge --auto` on an already-green PR merges instantly** — #4018/#4019 merged at 14:31Z the moment I
  re-armed them after the prompt, not when their checks finished (06:1xZ).
- **Lane findings on live surfaces:** `/api/status` narrated a PAUSED source as a broken pipe on a third surface
  (#4015 fixed both producers); `/api/protocols` `count=0` is the phase filter over nine archived cycle-5 rows,
  not an empty table (#4020); the one served hypothesis carried an unlabelled `min_effect: 0.05` (#4017); the
  #2119 scoped-writer guard sees 44 of 186 `put_item` sites (#4019, recorded as `xfail(strict=True)`).

## Residual / next picks (every line cites)

- **Owner, morning:** #3753 approve/redline v0.2 (then a one-line `ACTIVE = True` PR + MCP deploy — the build
  beat) · #3761 box 1 (the 2026-09-06 photo set — no keys tonight) · #3599's amendment publish (attended) ·
  #3945's register (0 posted by hand) · the permissions diff above (not-work — his settings, ask-first).
- **Next occurrence:** #3712 (Sun 17:00Z `episode-detect`: `committed_target.available`; the week after: the first
  `CALIB#…#prescription-week-…` grade) · #3615 (18:30Z nightly: `hooks:liveness_matrix` + the `weeks:*` legs,
  `qa_hook_matrix` row; boxes 4–5 residual) · #3971 box 4 (the first chat-COMMITTED routine's stored IR
  `load_floors.status == applied` — not done tonight on purpose, a test commit is litter in his Hevy) · #3621
  boxes 2b/5 (next attended reset; next `seed_protocols_to_dynamodb.sh --apply`) · #3607 (next `/review` header
  carrying `sha256 af9f9589…`) · #3552 (next freeze — `min_effect_provenance`) · #3599 (next reset's Step [0]
  census print; the ten waived writers expire 2026-12-31) · #3563 · #3830 · #3900 + #3915 (the 18:31Z nightly) ·
  #3601 (October close) · #3671 (next reset) · #3972 (a clean pre-flight).
- **Not started (design, not tonight):** #3436 · #3754 boxes 3–4 · #3620 boxes 3–4 · #3760 (the private
  photo viewer) · #3759 (promoted to Now tonight by stored rank; fable; waits on #3760).
- **Alarm board:** `qa-smoke-warnings` citation EXPIRES 2026-09-22 — not-work — the 09-21 18:30Z nightly clears
  it or the next session files the defect it names.
- **Site auto-deploy verdict for #4020** (run 35615359410, visual + AI-vision QA in flight at wrap) — not-work —
  read `gh run view 35615359410` at boot; a rollback would need the `site/**` re-publish per
  `docs/SITE_UPLEVEL_PLAYBOOK.md`.
- **Worktrees:** every merged lane released (`lane_worktree.py release` ×12); `issue-4014-main-red-fixforward`
  is merged and unreleased — not-work — release at the next boot. 51 older locked worktrees pre-date this session.
- **Lease steward** (a scratchpad loop) was still running at wrap — not-work — it dies with the terminal; the
  three in-flight main runs above may park after that and want rejection by name.

**Build beat:** none — the red-teamed plan is still owner-gated (#3753 unruled, `ACTIVE = False`); a merge drain plus two CI structural fixes is not a beat.
**Docs:** `docs/engines/HYPOTHESIS.md` re-verified against #4017 with 12 AST-derived spans (#4021) · `docs/SCHEMA.md` protocols row (#4020) · `docs/reviews/anchors/ANCHORS.json` + sha sibling (#4018) · `docs/INCIDENT_LOG.md` +1 row (Patterns regenerated) · `docs/OPERATING_KNOWLEDGE_LEDGER.md` +17 rows (13 inherited from AM–AO, snapshot regenerated, the 18-test CI check green) · the doc-sync literals by `sync_doc_metadata.py --apply` in this commit.
**Decisions:** none needed — the ceiling re-derivation follows #3678's existing rule (measured p95 × 1.2), and every other change is an implementation of an existing ADR.
**Main:** red — main's full suite was red 04:56Z → 15:00Z on two NON-required gates (`test_iso_parse_site_registry_3609` on #4014's `mcp/hevy_prescription_gate.py`; the Docs CI drift gate on `docs/engines/HYPOTHESIS.md` after #4017); fix-forward #4021 merged 15:00:50Z at `b047216a1`, whose CI/CD run 35616034654 was still in progress at the wrap commit — `check_main_green.py` therefore reads the prior red; the next session confirms green on that run. Every deploy tonight was direct from the main checkout and content-verified; no lease was used.
**Incidents:** 1 row added — main's full suite red ~10h on the two non-required gates, aggravated by the 9-hour permission-prompt wait (P3, no reader impact; Patterns block regenerated).
**Stash/hooks:** clean — no stash; the installed pre-commit/commit-msg hooks are #4007's (`session_postflight` hook freshness 🟢).
**Closures:** #3918, #3982, #3700, #4011 commented (Outcome / Live proof / Residual each) · DoD: scanned=7 window=closed>=2026-09-21 hits=0 findings=0 dispositioned=0 mode=warn blocking=none (one `unhomed-residual` hit on #3700 fixed by editing the closing comment before the sweep re-ran).
**Backlog:** Now 3 live stories after promoting #3759 by stored rank (milestone + score line both edited); 57 → 54 open (51 non-Roadmap); 1 filed (#4011, closed same session); hygiene: 0 violations, 2 advisories (`now_lane_coverage`, the #3540 grounding specimen — both grandfathered); Later sweep — no stale Later issues.
**Alarms:** ✅ every lit alarm cites an OPEN issue or a dated self-clearing state (`check_alarm_citations.py` green at 14:4xZ; `qa-smoke-warnings` citation expires 2026-09-22).
**CI warnings:** none triaged — the latest completed main run was red (see Main), so `check_ci_warnings.py` had no green run to read; the next session triages the annotations on `b047216a1`'s run.
**Ledger:** omitted — the only standing machinery that shipped rides existing rent: the #4015 census legs are two steps inside the existing qa-smoke nightly (21 key-bounded reads), the #4019 scoped-writer guard is a premerge test, the #4018 anchor seal is a BUILDER with no schedule; the #4005 citation cron's row lands with its first run (October), as AO recorded. `docs/PROPORTIONALITY.md` was regenerated by the reconcile bot after every merge (gate census 669 → 676).

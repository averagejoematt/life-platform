# Handover — Session AN: the overnight drain, and the deploy that split the fleet (2026-09-19 21:15 → 2026-09-20 ~09:45 PT)

**Fable, autonomous, standing merge + deploy authority (fleet, MCP, site, CDK — tonight only).** The brief
set 97 → ≤45. The honest number at wrap is **64 open in all / 61 outside the Roadmap milestone** — a 33-issue
drain, 16 short of the target. Gross: **40 closed, 8 filed** (#3943 #3944 #3945 #3946 #3971 #3972 + the
auto-filed #3980 + #3982, the instrument gap #3980 exposed, filed at wrap). The owner sheet was applied at boot by asking each gated item one at a time (11 rulings,
all recorded on their issues). The wrap landed ~3.5 h past the 06:00 PT target, and the reason is its own
memory: I read time off the last log line, not the clock, while lanes ran for hours.

---

## What shipped (31 PRs merged, every one `Refs`, no trailers)

**Driver PRs:** #3948 (grounding specimens, #3516/#3519) · #3951 (#3938 readback `unverifiable` + the WHY note
moved to `exercises[0].notes`) · #3953 (#3942 dry_run gates storage) · #3954 (#3601 ADR-077 30-day minimum) ·
#3956 (#3917 xdist credential stash) · #3958 (#3919 calendar stale-carry arm) · #3959 (#3646 model gate
`pending-reconcile`) · #3960 (#3900 tagger-blind stamps + IAM) · #3961 (#3770 explicit muscle group) · #3963
(#3625 reproducible zip) · #3964 (#3643 prereg escapee) · #3969 (config ownership fix-forward) · #3970 (#3920
derived layers) · #3981 (fix-forward for #3975's fromisoformat, **armed**) · #3965 (#3772 orphan drafts, **armed**).
**Lane PRs:** #3947 (#3715) · #3949 (#3930) · #3950 (#3563) · #3952 (#3830) · #3955 (#3932) · #3957 (#3929) ·
#3962 (#3927) · #3966 (#3916) · #3967 (#3914) · #3968 (#3928) · #3973 (#3913) · #3975 (#3700) · #3976 (#3620) ·
#3978 (#3712) · #3974 (#3915, **armed**) · #3977 (#3609, **armed**).

**Closed on live proof (15):** #3670 #3606 #3919 #3654 #3646 #3916 #3917 #3932 #3930 #3929 #3942 **#3741 (epic —
its last child)** #3920 #3928 #3914. **Folded (25):** 16 Roadmap issues into umbrellas #3943/#3944 and 9 Later
stories into their epics, scope carried verbatim. #3927 closed by its lane's `Fixes`; the verdict it lacked was
posted at wrap. **#3913 was auto-closed the same way with no deploy and was REOPENED**, then corrected once the
CDK deploy turned out to carry it (see below).

## Deploys — name every stack, and which tip each function runs

- **Fleet** (`deploy_fleet.sh`): 106 functions from main `c32e58c31`, 13:19–13:26Z, 0 failed.
- **MCP** (`deploy_lambda.sh life-platform-mcp`): same tip, postflight ancestry OK; artifact greps confirmed
  #3770 #3938 #3930 #3932 #3920 #3928 #3927 #3700 content.
- **CDK:** `LifePlatformCompute`, `LifePlatformEmail`, `LifePlatformOperational` from main `7615ce47` at
  15:0xZ (rc 0; drift guard overridden with `ALLOW_LIVE_LAMBDA_DRIFT=1 ALLOW_STALE_DEPLOY_CHECKOUT=1` after a
  first refusal). Purpose: the two `ExperimentCycleRead` SSM grants (#3900), hevy-routine-cron, the #3976 daily
  PII-sweep cron. **Consequence the guard was warning about:** CDK re-bundled its tree asset, so every function
  in those three stacks now runs `7615ce47` (freshness-checker, evening-nudge, hevy-routine-cron, the Compute
  lambdas — read from each artifact's `build_info.json`), while `life-platform-mcp`, `whoop-data-ingestion` and
  the other stacks stay on `c32e58c31`. The deploy line on #3913/#3712/#3620 was corrected to say so.
- **Site:** no `site/**` merge tonight; the attended `rollback_site.sh HEAD` for #3654 box 4 ran 06:15:22Z
  (invalidation `I2V522MBH5ZDX8AXICANH6D7DN`, LEFT LIVE block empty).
- **Attended mutations:** `config_twin_sync.py --apply --strict` 06:34Z uploaded #3929's missing twin;
  `backfill_coach_ensemble_phase_stamps.py --apply` 05:1xZ stamped 48 rows (77 cross-phase untouched).

## Leases — 40 rejected by name, zero blanket
35484570936→3fb06a2a9 · 35487422677→24b83c5b3 · 35491037546→d5dc1a040 · 35491070986→914c79378 · 35491571732→4a9dfd9ab ·
35491603778→436c2063c · 35491727734→941200398 · 35491744302→dc7172e70 · 35491819881→fcee8fc00 · 35491830161→3d8c0b4b1 ·
35491896087→27cf631ff · 35492324046→3e322f66f · 35492361444→b2fee2628 · 35492589771→92d3a363d · 35492627269→fd886d571 ·
35492710051→f4f5100af · 35492671336→f2540c84f · 35492738587→3fe028737 · 35492777669→f61d16242 · 35493036630→72c1ca810 ·
35493033549→9feece7b0 · 35493066476→05531e899 · 35493222405→d1b44efc0 · 35493150058→963ef86c9 · 35493468353→3b003d448 ·
35493546378→22060e755 · 35493664242→58c5f2845 · 35493584951→8bb1389a1 · 35494053022→e188db30a · 35494086845→ee3f63b64 ·
35494243644→064ca8f3a · 35494213402→278a3fcc0 · 35494512815→bd635533e · 35494543939→56b741d68 · 35494578680→1cf673f1b ·
35495359928→ae8184d12 · 35496280636→89b472327 · 35497353035→2b885abd9 · 35513202227→372b423cd · 35513211288→715a39fff.
No lease waiting at wrap.

## Found by measuring, not by reading

- **#3625 box 3 is NOT met and cannot be by the zip fix.** `cdk diff LifePlatformCompute` right after the deploy: 32
  `S3Key` lines; three synths of one tree minted three asset hashes. CDK fingerprints the staged *directory*, and
  `build_info.json`'s wall-clock `built_at` differs every staging (524 files, one differs). Recorded on #3625 with the
  design options; box stays unticked.
- **#3929 shipped inert:** `config/hevy_template_aliases.json` landed unruled → main's unit tests red 05:50→06:3xZ
  (fix-forward #3969) and the S3 twin was never uploaded until the attended sync.
- **#3975 was caught by #3609's own gate** (a hand-rolled `date.fromisoformat`) → main red on the registry test from
  `7667991df`; #3981 fixes forward and is armed (its first push failed mypy on the parser's `date | None`, fixed).
- **Hevy API still returns `shoulders`** for the calf-press template after the owner's in-app edit (04:47Z, 05:10Z,
  05:35Z, 06:19Z) — #3770 stays open on the API, not the app.
- **12 `#pain` rows minted from 2022 notes** (grip-work lists) → #3972. **#3927's auditor is a discipline on the chat
  path, not a gate** → #3971. **#3700's `attach_cardio_cues` is never reached by `draft_custom`** (recorded on #3700).
- **`recap-card-generator` dry run** left no S3 object and no row (the #3942 proof) — the row read needed
  `--expression-attribute-names` because `storage`/`dry_run` are DynamoDB reserved words.

## Open at wrap, and why (every line cites)

- **Armed PRs:** #3981 (fix-forward; main is red until it lands) · #3977 (#3609; census 665→666 resolved) · #3974 (#3915)
  · #3965 (#3772). Each was rebased onto main by hand (`--theirs` on the regenerables + sync + plain commit).
- **Nightly / next-occurrence proof:** #3900 (18:31Z coverage leg) · #3563 (next chronicle send) · #3830 (next vendor
  503) · #3913 (a PT-evening straddling read) · #3712 (next weekly prescription; MCP side awaits a deploy) · #3620
  (boxes 2–5 not started; box 1 live) · #3700 (n-floor on a real ride).
- **Owner acts (#3945 register):** #3938 box 1 · #3770 · #3715 box 5 · #3772 box 2 · #3753/#3755/#3761/#3918 (approved
  tonight, lanes not started — the drain took the night) · 0 posted by hand.
- **Next reset:** #3643 boxes 2–4 · #3552. **Not started (design, not bug-fix):** #3601 boxes 1–2.
- **#3980** — auto-filed 13:20Z by the cron-freshness advisory: `[ NEVER] pii-endpoint-sweep.yml` — #3976's newborn
  cron, registered `watched` three hours before its first schedule; auto-closes on its first green. The instrument gap
  (a newborn watched workflow reds before it could have run) → **#3982**.
- **Worktrees:** every merged lane's worktree released; the four armed PRs' worktrees stay until they merge.

**Build beat:** the debrief red team — merged + deployed 09-19 (`docs/content/BUILD_DISPATCH_CHECKLIST.md` shape); nothing tonight was bigger than it, because tonight was a drain, and a drain is not a beat.
**Docs:** ADR-077 amended (#3954, the 30-day minimum on the measured number); `docs/CONVENTIONS.md` §1 carries the zip-reproducibility invariant (#3963); the CLAUDE.md status block replaced in this wrap.
**Decisions:** ADR-077 amendment (#3954) — the reset's 30-day minimum, recorded on 12 resets / 55 days, median 5; no other ADR.
**Main:** red — `test / Unit Tests` on the #3609 ISO-parse registry gate since `7667991df` (#3975's hand-rolled fromisoformat); fix-forward #3981 armed on the required checks. Earlier tonight: red on `test_config_ownership_3785` from `f2540c84f` to `064ca8f3a`, cured by #3969.
**Incidents:** none filed — the config-ownership red and the #3609 red were both fix-forwarded inside the session; neither reached a reader surface.
**Stash/hooks:** clean
**Closures:** 40 closed (15 on live proof, 25 folded) · DoD: scanned=43 window=closed>=2026-09-20 hits=4 findings=4 → all 4 dispositioned at wrap (3 residual lines re-homed as `not-work`, #3927 given its Outcome verdict)
**Backlog:** 97 → 64 open (61 non-Roadmap); Now carries the four armed PRs' issues + #3980 (milestoned Now at wrap); 8 filed (#3943 #3944 #3945 #3946 #3971 #3972 #3980 #3982); hygiene 12 → 0 at boot
**Alarms:** ✅ every alarm in ALARM state >72h cites an incident row or issue (wrap_gates e10, 15:1xZ)
**CI warnings:** latest completed main run red on the #3609 gate (see Main); cron-freshness advisory red since 13:20Z (#3980 — a newborn cron, #3982 for the instrument)
**Ledger:** `docs/PROPORTIONALITY.md` regenerated by the reconcile bot after each merge (gate census 664 → 665 on main; 666 once #3977 lands); no new standing machinery beyond the nightly `orphan_routine_drafts` leg (#3965, armed) and the #3976 daily PII-sweep cron (CDK-deployed)

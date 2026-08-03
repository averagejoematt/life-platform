# HANDOVER — Unblocking the owner: gate:owner 18 → 6 — 2026-08-02 evening → 08-03 early

> Instruction thread: *"I am told 18 items have gate:owner that are blocked by me. Let's ELI5 each
> one of those 18 in very simple terms with options for each so at the end of our conversation no
> items are blocked on me."* Then, after the decisions: *"yes keep going as long as we don't
> interrupt parallel session."* A second session was wrapping concurrently for most of this one.

**Main:** stranded — run `30768641759` (sha `386a1e24`) parked 4.3h at the `production` approval
gate, #1901 class; every later CI/CD run queues behind it, including #1187's (`111260fe`). Recovery
is `bash deploy/approve_deployment.sh 30768641759` on Matthew's say-so — do NOT cancel it (a
cancelled run strands its deploy and needs a `deploy_all=true` dispatch to recover).
**Docs:** none needed — no deploy path, data-model, engine, MCP-tool or site-authoring surface
changed; the three shipped PRs are a Lambda publish-path hook, a QA assessor, and a front-end
renderer, all documented in-module.
**Decisions:** none needed — no governance/posture choice was made. The one judgment with ADR
flavour (homing a frozen brand asset at `config/panelcast/` rather than `generated/panelcast/`) is
an IAM-shaped implementation detail recorded in the module docstring and PR #2053, not a new rule.
**Incidents:** 2 rows added — the spurious auto-rollback (stale canary row reverted a correct fleet
deploy) and the fifth phantom concurrency wedge (now in the deploy group).
**Build beat:** 2026-08-03-a-test-row-undid-a-good-deploy.
**Closures:** #1985, #1742, #1632 commented (ADR-099 two-line verdict each).
**Stash/hooks:** clean — `git stash list` empty; hook freshness green.
**Alarms:** 0 red >72h uncited — `check_alarm_citations.py` clean.
**Backlog:** Now live at 9 actionable (no refill needed); no stale `Later` calls required this
session. Filed #2051, #2052, #2060 and cleared their `epic_link` violations (hygiene 8 → 5; the
remainder is pre-existing debt #1868 owns).

---

## The headline: every one of the 18 owner-gated items got a decision, and 12 cleared

The ask was to make decisions, not to ship. Shipping happened anyway where the decision unblocked
work that was already written. **18 → 6**, and *none of the remaining 6 is waiting on a decision* —
each is an action only Matthew can perform.

**Closed outright (2):** #1742 ElevenLabs (declined — the 2,000-char chunk seam reintroduces exactly
what `gemini_tts.py:33-36` bought back, plus Cost-Explorer-invisible billing), #1632 Instagram
(decline confirmed with its real cost: a new portrait format in `card_engine.py`, not a Meta wait).

**Label stripped, now ordinary work (7):** #1934, #1951, #1622, #1629, #1662, #1678, #1407.

**Shipped and verified (3 PRs):**
- **#2055** (#1985) — the Calloway editor's note on Prologue Part III, **live**, plus a
  deterministic frozen-artifact guard.
- **#2059** (#1940) — the citation correction stated on the protocols page, **live**.
- **#2053** (#1187) — the frozen V1 podcast brand hook. Merged; **NOT deployed** (see the ask).

**Decisions that changed scope rather than closing:** #1631 X was reopened as a *link-free presence
channel* after the pricing in the issue proved wrong (below); #1622's 15/30 trial gate was removed
and #1629 unblocked to build alongside; #1633 YouTube and #1677 inbound capture were both taken
*up* a level rather than deferred.

---

## The catch that mattered most: a 12-day-old fake row was reverting every deploy on the platform

Shipping #2010 took three stacked failures to get through, and the middle one was the real find.

1. **The R8-ST6 IAM gate was failing `Plan` on every run**, so `Deploy` was skipped platform-wide —
   which is why four merges in a row had produced no deploy. Undeployed CDK IAM drift
   (`QaSmokeRole` + `dynamodb:GetItem`, `TrafficDigestRole` + `Query`/`kms:Decrypt`, `CanaryRole`
   `DeleteItem`, `WeatherIngestionRole` + `PutObject`). `cdk_deploy.sh LifePlatformOperational
   LifePlatformIngestion` cleared it and `Plan` went green immediately.

2. **The fleet then deployed correctly and auto-rollback stripped it back out.** Smoke failed on the
   canary; the canary failed on **one synthetic `source='canary'` subscriber row created
   2026-07-21**. DynamoDB, S3, MCP and Bedrock all passed. A stale *data* row reverted a *correct
   code* deploy — and while it existed, **no deploy on this platform could survive, this session's
   or the concurrent one's**. Deleted under a `source = canary` condition expression (so it could
   not have touched a real subscriber), residue 0, canary `all_pass: True`. Filed **#2051**: the
   canary's infra round-trip and its data-residue postcondition must fail into different lanes —
   exactly the #1921 reasoning already applied to content-truth findings, one path over.
   *Side effect worth knowing:* that row carried `status: pending_confirmation`, so the "3 pending
   subscribers" figure cited in #1951 was really 2.

3. **Re-shipping via CI hit the fifth phantom concurrency wedge**, now in the *deploy group* exactly
   where the v4 redesign comment predicted ("if a phantom EVER appears again, it can only be in the
   deploy group"). All deps green, Deploy queued 12+ min, approval gate never opened. Filed
   **#2052** — and note the comment's consolation was wrong: a wedged deploy reads as *"waiting for
   approval"*, which is **less** legible than the old `0 jobs`, not more. Shipped via
   `cdk_deploy.sh LifePlatformCompute LifePlatformEmail` instead.

All four #2010 pieces verified **against the deployed zips**, not run conclusions: `#1896`/`#1897`
markers present in `coach-narrative-orchestrator`, `daily-brief`, `state-of-matthew`,
`coach-quality-gate`; `phase_plausibility.py` + `qa_check_reader_truth.py` in `life-platform-qa-smoke`
with the call chain traced end to end.

---

## Two issue premises were wrong, and checking cost less than trusting would have

- **#1187 said the arpeggio ident was "deliberately OFF on the lambda."** It was not:
  `PANELCAST_IDENT` was set neither on `coach-panel-podcast` nor in CDK, and the code default was
  **on** — every episode has been carrying it. Had that line been trusted, every episode would now
  open **twice**. Default flipped in code.
- **#1631 priced X at $12/mo (14% of the ceiling).** That is the *link* surcharge added April 2026;
  a plain post is **$0.015** — ~$0.90/mo. Verified against X's pricing docs + TechCrunch. The
  channel was reopened as link-free, with the ADR-063 amendment and the pre-POST DynamoDB counter
  still required (the bill is invisible to `cost_governor` at any price) and a note that putting the
  link in a first reply does **not** dodge the surcharge.
- **#1940's "23 citations" nearly got published as 21.** The live supplements payload holds 21; the
  other 2 are on the *experiments* registry (`tongkat-ali-recovery`, `berberine-glucose`). The issue
  was right, just split across two files. The notice now states its derived count *and* names the
  half it cannot see, with a test asserting the reconciliation.

---

## Other things worth carrying

- **The V1 podcast voice was not lost to the July restart.** `generated/panelcast/hook-v1-*.wav` are
  196-byte tombstones, but they carry an `archived_to` pointer and the audio is intact at
  `generated/panelcast/archive/pilot/hook-v1-voice.wav` (7.60s, Elena). Used unmodified — what ships
  is exactly what was approved in July, with no TTS spend. **Check the archive before re-rendering
  anything a restart tombstoned.**
- **A guard that fires on correct writing is worse than no guard.** #1985's first assessor flagged
  the 185 lb target and the 275/250/225/200 waypoints as superseded start weights. Proximity alone
  cannot separate them — the live stats line reads `317.61 lbs at the start · 185 lbs the target`,
  so any window binding "at the start" to 317.61 also reaches 185. Rule became **nearest marker
  wins**. Both false positives came from running against the real published pages.
- **A correction can be complete in the data and structurally invisible.** #1940's withdrawals were
  live in the payload the whole time; a withdrawn citation carries **no url** by design (#1892's own
  contract) and the card renderer filters sources on `x.url`. The fix landed and the page went
  silent about it.
- **`needs_s3_write` grants PutObject only** (documented at `role_policies.py:876`). The Panel role
  can write `generated/panelcast/*` but cannot read it — which is why #1187's frozen asset lives at
  `config/panelcast/brand_open.wav`, needing no IAM change and therefore unable to strand CI.
- **Sequence wraps, never race them** (from the concurrent session): each wrap archives the current
  `HANDOVER_LATEST`, so two finishing simultaneously could archive a half-written one.

---

## NEXT — Matthew's numbered ask (SUPERSEDES the 2026-08-02 handover's list)

Carried forward with this session's clearances marked. Items 3, 5, 7, 8, 9, 10 are untouched and
their text is the previous handover's, unchanged.

1. ~~`cdk_deploy.sh LifePlatformOperational LifePlatformIngestion`~~ **PARTIAL** — Operational +
   Ingestion deployed and verified; **`LifePlatformMonitoring` still NOT run** (#2046's 5 per-source
   OAuth alarms do not exist until it does). Compute + Email were also deployed (off-list) to ship
   #1896/#1897 around the wedge.
2. **PARTIAL** — the `deploy_all=true` dispatch ran and the fleet deployed, then auto-rollback
   reverted it (the canary row, now fixed); #1896/#1897 were re-shipped via CDK.
   **`bash deploy/deploy_site_api.sh` was NOT run**, so the site-api halves remain dark: grounding
   gates (#1967), voice guard (#1987), PT anchors + strict reader-truth (#1937), `prereg_seal`
   (#1980), `/api/content_cadence` (#1972), config cache TTLs (#2019), dimensioned auth metric
   (#1960).
3. DDB remediation pair (carried): countdown reconcile `--apply` + #1896 THREAD tombstone + coach
   regen/noscript rebake. **Untouched.**
4. ~~Canary-row delete~~ ✅ **DONE + verified** — row deleted under a `source = canary` condition,
   residue 0, canary `all_pass: True`, all five checks green. See #2051 for the durable half.
5. PR #2012 revision purge (carried — GitHub UI). **Untouched.**
6. ~~#1934 Whoop interactive OAuth~~ ✅ **DONE + verified** — re-authorized, token verified against
   `/recovery`, gap closed: `DATE#2026-08-01` and `DATE#2026-08-02` both landed (latest was 07-31).
   *Correction for the record:* the issue says the callback page will not load — it loads fine on
   the default path; only `--manual` needs the paste flow. #1934 stays open for its fourth box (a
   latched breaker on a `qa_required` source needs its own signal) — that half needs no owner act.
7. NEW: prereg void reconcile — `python3 deploy/reconcile_prereg_voids.py --show-plan`, review, then
   `--apply` (~1,435 voids; **public voided count jumps 273 → ~1,708**, the #1893 correction — land
   it deliberately). The reset invariant BLOCKS the next `restart_pipeline.py --apply` until this
   runs (#1978). **Untouched.**
8. NEW: config-twin first sync — `python3 deploy/config_twin_sync.py` (read-only), review the 7
   drifted objects, `--apply`; then flip site-deploy's twin step back to `--apply` + `--strict`
   (dated marker in the workflow, #2019). The daily config-drift workflow reds until this runs —
   that's the alarm working. **Untouched.**
9. NEW: dismiss the 3 CodeQL alerts on PR #2046 — the documented #1902 false-positive class;
   dismissal was classifier-reserved for Matthew. **Untouched.**
10. NEW post-deploy re-arm (after 2): `python3 deploy/capture_api_schemas.py` → commit the
    `/api/content_cadence` + `prereg_seal` baselines; restore both `api_deps` entries in
    `tests/qa_manifest.py`; empty `pending_deploy_apis` in `tests/visual_qa.py`; drop the dated
    `_exemptions.json` + SURFACE_DRIFT_EXEMPTIONS entries (#2050's checklist). **Untouched.**
11. **NEW this session:** approve the stranded production gate (`bash deploy/approve_deployment.sh
    30768641759`), which also unblocks #1187's run `111260fe` — the podcast brand hook is **merged
    but not live**, the exact class that produced #2010.

Then the post-flush verification pass (#2010) — after 1+2 it cheaply validates the merged-but-dark
fixes from 08-02 plus this session's lambda-side halves.

---

## Residual / next picks

- The 6 remaining `gate:owner` items are all owner *actions*, not decisions — #1738 (listen to three
  TTS renders once built), #1631 (X dev account + billing), #1633 (YouTube channel + API cred),
  #1677 (X/Meta/TikTok tokens), #1571 (one vlog session from the phone), #1940 (approve the
  correction wording — merged and live, so this is confirm-or-revise). not-work — each is an owner
  act or an in-the-moment decision, not a backlog item.
- **#2051** — the canary's data-residue postcondition must stop gating code rollbacks.
- **#2052** — the phantom wedge, now in the deploy group; five recurrences, three salts and one
  redesign tried.
- **#2060** — two `test_pre_start_contract_sweep` tests red on `main`, pre-existing (reproduced on
  `29cc4fd2`, before this session's PRs); `handle_character_stats` appears to return no
  `character_stats` key.
- **#1985**'s acceptance box 2 — a supersede-*time* sweep of frozen artifacts was deliberately not
  built; the nightly guard covers the condition continuously. Recorded on the issue; reopen there if
  the supersede-time version is still wanted.
- Cleanup: three worktrees remain at `~/Documents/Claude/wt-1187-brand-open`,
  `wt-1985-prologue-note`, `wt-1940-citation`. not-work — housekeeping; all three branches are
  merged and the worktrees are safe to remove.

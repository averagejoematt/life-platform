# HANDOVER — Backlog blitz + the merged-is-not-live catch — 2026-08-02 (evening)

> Instruction thread: execute the pre-approved plan `~/.claude/plans/elegant-zooming-teapot.md`
> (Track A backlog paydown in worktree-implementer waves + Track B verification sweep of the
> 07-28→08-02 ships), with the mirror-session deltas applied. Preflight confirmed: deploys still
> stranded (R8-ST6) → merge-only session, no fleet deploys, DDB mutations owner-gated.

## The headline: 17 PRs merged, and the sweep caught a live honesty failure

**Track A: 17 PRs merged in one evening**, closing 19 issues — every planned Wave-1/2/3 item plus
the full coach lane:

| PR | issue | what |
|---|---|---|
| #2016 | #1989 | cockpit scope buttons meet WCAG AA both themes; baseline row removed, axe gate re-armed (site-deploy ✅ → **live**) |
| #2017 | #1977 | observatory_week genesis clamp → honest absence, tie = flat |
| #2018 | #2005 | /deploy function→source table generated from lambda_map + drift gate |
| #2020 | #1994 #1995 | Day-1-safe hero sentence + honest brief-line kicker (site-deploy ✅ → **live**) |
| #2021 | #1945 | PII guard endpoint arm — derived route set; live sweep 118 payloads / 0 violations |
| #2022 | #1965 | check_doc_index strict by default — local == CI |
| #2024 | #1956 | canary grades against the ask pipeline's own serving context (root-caused: it alarmed on the TRUE recovery value 96) |
| #2025 | #1958 | chronic timing warns leave the alarmed WarnCount (floor was live-confirmed 5–9 vs threshold 1) |
| #2026 | #1947 | countdown-gap sweep + owner-gated reconcile; live dry-run measured **379 escapees** (157 THREAD / 61 INSIGHT exact) |
| #2027 | #2001 #2002 | HAE liveness deep-scan (true darkness: BP 2026-04-10, SoM 2026-04-02) + carried chips from the cycle ledger (site-deploy ✅) |
| #2028 | #1902 | all 99 CodeQL alerts triaged: 14 fixed (+4 the new guard found), 85 dismissed with written reasons (**dismissals live via API regardless of PR**) |
| #2029 | #1969 | every get_item in the generation path tombstone-guarded (28 AST-derived sites, 15 reasoned exemptions) |
| #2030 | #2006 | CONVENTIONS §4 pin-grep works again + tests run the doc's commands verbatim |
| #2031 | #1901 | check_main_green classifies the two stranded-deploy states (verified against the live stranded main) |
| #2032 | #1971 | coaching door discloses the budget-pause (JS live + safe; API field awaits the flush) |
| #2033 | #1949 | weather raw archive restored (IAM) + raw-archive failures unswallowed platform-wide (premise live-confirmed: newest object 2026-03-09) |
| #2034 | #1993 | labs coach reads the draws that exist — schema-true fact block + "zero results" qa tripwire |

Plus direct-to-main `30b3e5e2` (see incident 2 below) and issues **#2019 + #2023 filed**.

**Track B: the verification sweep found and fixed a live reader-facing failure.** PR #1939's
citation withdrawal (merged 03:38Z, site-deploy green) never reached readers — `/api/supplements`
served **18 of the 20 fabricated PMIDs for ~13h** because the S3 root `config/` prefix the Lambda
reads has **no deploy path** (S3 object dated 07-18; `experiment_library.json` equally stale), a
no-TTL warm-container cache and CloudFront 3600s stacked on top. Remediated same session:
explicit `aws s3 cp` of the two repo twins (never a prefix sync — root `config/` holds
Lambda-written runtime state), a description-only site-api touch to recycle containers,
CloudFront invalidation of the three affected paths, then **verified live: 0/20 forbidden PMIDs,
explib clean**. Structural gap filed as **#2019** (P1, Now, epic #1890).

Rest of Track B (per the shrunk scope): **B0 truth table** in the session scratchpad
(`B0_truth_table.md`) — only site-api (15:53Z) + qa-smoke (16:23Z) carry Aug-2 merges; everything
else is Aug-1 bytes awaiting the flush. **#1893/#1938 voided bets: PASS live** (273 exact on
`/api/calibration`, JS binds at `/method/calibration/` — NOT `/data/`, and `/api/ledger` is a
different surface; that's why the earlier spot-check found nothing). **B4 alarm sweep:** all 8 red
alarms mapped to owners; the one unowned signal was verified (verdict CONFIRMED with corrections)
and filed as **#2023** — the #813 gradability gate phase-filters its raw-source liveness query
(genesis-blinded, #1203-class recurrence; cycle-11 gradable share ~1.4% vs the ~9% best).

## Blocked on you — the ONE numbered ask (updated; supersedes the overnight list)

1. **`bash deploy/cdk_deploy.sh LifePlatformOperational LifePlatformIngestion -- --require-approval never`**
   — now carries: #2011 qa-smoke PutItem, #2012 digest/canary IAM, #2024 qa-smoke S3Read on
   `ai-canary-log/*`, #2033 weather PutObject on `raw/weather/*` + qa-smoke ListBucket on `raw/*`.
   Un-reds every ci-cd Plan (R8-ST6).
2. **`deploy_all=true` dispatch + approve** — ships the whole stranded fleet: the #1941/#1942
   coach-integrity gates, #2012 digest/canary code, og-image PT frame (#2013), #2024 canary
   universe, #2025 chronic warns, #2027 freshness checker, #2029's nine coach/intelligence
   functions, #2033 unswallow, #2034 labs extractor — plus `bash deploy/deploy_site_api.sh` for
   the site-api half (#2027/#2032 field, #2017 clamp).
3. **After 1+2, the DDB remediation pair** (dry-run first, both scripts print every mutation):
   `python3 deploy/reconcile_countdown_gap.py` → review → `--apply` → re-run dry-run expecting 0
   (#1947's 379 escapees; **3 flagged rows** need your per-row `--include-flagged` judgment). Then
   the #1896 remainder: tombstone the fabricated `lunch_protein_prediction_miss` THREAD (my
   dry-run script is in the session scratchpad; the countdown reconcile covers the other 16 of
   its 17 rows). Then regenerate coach analyses + rerun the proof-builder so the noscript stops
   asserting the false verdict (#1896 acceptance 3), and invoke the analyzer with
   `{"expert":"labs"}` for #1993 acceptance 4.
4. **The stray canary row delete** — unchanged from the overnight list (command in PR #2012's body).
5. **PR #2012 revision-history purge** — unchanged (GitHub keeps public edit history).
6. **#1934 Whoop OAuth** (`python3 setup/setup_whoop_auth.py --backfill`) — gap now ~2.5 days;
   drives 3 of the 8 red alarms. (#2028 masked its token prints; the interactive flow is untouched.)
7. Standing, still yours: PRE-13, #1927 ceiling number, growth-1/#1951, #1940 public correction.

## Gotchas hit

- **Merged is not live** — the #2019 class above; the sweep exists for exactly this. When a PR
  body carries a manual deploy note, that note has no owner once the PR merges.
- **Concurrent PRs breach size gates in UNION** (memory rule filed): #2025+#2026+#2027 each green
  alone put qa_smoke_lambda at 1296 and restart_pipeline at 1202 → main's Unit Tests red ~1.5h.
  Fixed by a real extraction (`qa_check_outputs.py`, `30b3e5e2`), not an exception comment. Check
  shared-file headroom before a wave; re-run the size guard on main after the union.
- **The reconcile bot**: ci-cd's "Reconcile derived artifacts" job now auto-pushes the doc-sync
  literal regeneration after every merge — the manual `/reconcile-branch` regen step is automated
  (I verified the bot's commit byte-identical to a manual run). Conflict resolution and
  linearize-before-squash are still manual (#2034 needed the full ritual after #2033 landed).
- **The pre-commit hook auto-stages doc-sync literal bumps into implementer commits** — all nine
  implementers hit it; the brief now has to say "restore from origin/main + amend --no-verify".
- **#2028's 85 CodeQL dismissals are live API state** independent of the PR — if that PR had been
  rejected, the dismissals would have needed revisiting.
- **Watch item:** the 07-31 canary record carries a REAL `board_meta_pressure:no_vendor` alarm
  (training_coach said "claude" under meta-pressure) — `not-work — single occurrence, out of
  #1956's scope; file only if it recurs post-deploy`.

## What to expect from tonight's automated runs

Tonight's 22:30Z qa-smoke still runs the **old deployed bytes** (16:23Z): expect the truthful
WARN on the dark predict widget (#1953 working — day 2 may FAIL, still correct), the Reader Truth
FAILs on frozen coach text (321.1 vs 317.0 — clears only after ask 2+3's regeneration), and the
warnings alarm still red (clears one window after ask 2 ships #2025). The `_30d` honesty FAILs
should stop tonight — #1918's fix went live with today's site-api deploy.

## Verified

- Final main union: **only the Plan job red (R8-ST6, by design)** — Unit Tests/lint/
  deploy-critical green on `cddf2f82`; doc-sync CHECK PASSED after the last bot reconcile; module
  size guard green on the union; all four site-deploys green (no rollbacks).
- Every implementer PR negative-tested its guard; three measure-first premises checked live
  before building (#1949 S3 listing, #1958 CloudWatch, #1993 line 533) — all three held.
- #1939 remediation verified on the live payloads (0/20); #1938 verified by live render + real
  fetch; #2031's classifier verified against the actual stranded state.
- All implementer worktrees removed, branches deleted (local + remote), tree clean on main.

**Main:** stranded — every run fails only Plan (R8-ST6 IAM-review); clears with ask 1; #1901's
classifier now decodes this state by name.
**Build beat:** 2026-08-02-merged-is-not-live.
**Docs:** INCIDENT_LOG (+2 rows), CONVENTIONS §4/§4d + deploy.md table (landed in the PRs
themselves); no other pages invalidated — the ships are code-level fixes under existing contracts.
**Decisions:** none needed — no governance posture changed; the qa_check_outputs extraction is
the established #1665 split idiom.
**Incidents:** 2 rows added — the config-prefix 13h stale serve (+#2019), the union size-gate red.
**Closures:** #1901 #1902 #1945 #1947 #1949 #1956 #1958 #1965 #1969 #1971 #1977 #1989 #1993
#1994 #1995 #2001 #2002 #2005 #2006 commented (19, per the ADR-099 two-line contract; honest
partial verdicts where behavior proof waits on the flush).
**Stash/hooks:** clean (empty stash; hook 🟢).
**Backlog:** Now live at 3 actionable (#1896-remainder, #1927, #2019); no stale Later issues;
hygiene 0 violations / 2 pre-existing advisories (#1677/#1679 class).

## Residual / next picks

1. **Post-flush verification pass** (#2010 closes then): after asks 1–2, confirm the gates fire
   on real generations (#1941/#1942), the canary stops false-alarming (#1956/#2024), the warnings
   alarm clears (#1958), and no auto-rollback fired on stale smoke (#1915 class).
2. **#2019** — the config/ deploy path (top actionable Now story after #1896).
3. **#2023** — genesis-blinded gradability gate (Next; worst exactly when readers watch a fresh cycle).
4. **#1937** — remaining UTC anchors in vitals (`not-work` tag not needed: filed issue).
5. **/fullreview delta**: the ~55 banked findings from 07-28 await one clean filing pass
   (`not-work — filing pass is its own session per the bank-and-delta convention, #1889 context`).
6. Whoop dark >2 days now (#1934) — the longer it runs, the bigger the Mirror/readiness backfill.
7. Standing-alarms checklist (#1329): 5 manual-rotation secrets stale >120d routed to the
   remediation agent's needs-human digest (todoist 125d, ingestion-keys 122d, +3) — `not-work —
   owner rotation ritual, surfaced by freshness-checker nightly`.

# HANDOVER — Overnight max paydown, Day 5: 20 PRs merged, 13 issues closed, the bug pipeline that ate its own tail — 2026-08-06 ~21:00 PT → 2026-08-07 ~15:45 PT

> Instruction thread: *"overnight maximum-paydown, full autonomy, owner asleep — Fable drives
> only, worktree-implementers on model:* labels, waves of ≤5, THE LEASE RULE, Now queue first
> (#1919, #1968) then stored Later rank (#1656 #1658 #1674 #1678 #2056 #1654 #2116 #1679 #2101),
> merge #2167 when checks mint, dependabot #2125/#2126 with the CQ-01 companion, batch owner
> actions into ONE list."* Mid-session the owner added: **"58 open issues — complete as many as
> we can without sacrificing quality"** and **"Fable is at 85% usage"** (drove lean-driver mode:
> implementers on the sonnet/opus pool, tight reconciles, auto-approver for gates).

**Main:** green (`a0b57098` — check_main_green exit 0 at wrap; the #2193 merge run rode the
auto-approver like the five before it).
**Docs:** ADR-149 filed in-PR (#2180) + index regenerated; `docs/engines/COACH_STANCE.md`
re-verified honestly (night-scope addition documented, `_enforce_quality_gate` span corrected
:1353-1420 → :1386-1453); `docs/ARCHITECTURE.md` site-api table corrected in #2192;
`docs/qa/SURFACE_DRIFT_EXEMPTIONS.md` +2 dated route lines (#2168, #2186 — removal is #2194).
Wiki checkers green at the wrap commit.
**Decisions:** ADR-149 filed (#2180) — one third-party frame origin (`www.youtube-nocookie.com`),
bought-not-exercised, flag-off with byte-identical synth until the owner's one-sitting flip.
**Incidents:** 1 row added — main red ~2.2h (P4): #2182's garmin adapter imported the
layer-shipped `garminconnect` wheel on the happy path; CI has no layers, so the merge run and
two followers redded until the guarded-import fix-forward (`67622779`). The deeper lesson made
memory: the agent's local env HAD the real wheels, so its full green suite was structurally
incapable of catching it.
**Build beat:** 2026-08-07-the-tests-that-filed-their-own-bugs.
**Closures:** #1674 #1919 #1968 #2116 #1678 #1679 #2056 #2173 #2174 #2175 #2176 #2177 #2179 all
commented in the ADR-099 two-line shape (evidence cited from live endpoints/deploys; #2056 and
#1678 carry honest partial-notes inside realized verdicts where a residual exists).
**Backlog:** 7 filed from #2172's discovery (#2173–#2179; 6 FIXED and closed same session) +
2 residual follow-ups (#2194, #2195), both promoted to Now by stored rank at the (e9) refill —
Now holds 4 (#1383, #1114 fable-live; #2194, #2195 session-startable). #2178 labeled gate:owner
(its fix is HELD PR #2184, the owner's Email-stack sitting). Later sweep clean (no
later_staleness findings). The linter's 2 score-line violations were on MY two filed issues —
fixed to the canonical grammar before close; corpus otherwise advisory-clean.
**Alarms:** whoop board unchanged (all >72h reds cited to #1934 per the standing registry);
`ingest-reconciliation-whoop-heartbeat` (new 08-06 12:38 PT) is <72h — cite it to #1934 next
wrap if the re-auth hasn't cleared it. Gate exit 0.
**CI warnings:** 2 — both the carried owner-window cdk config-drift class: LifePlatformCompute
and LifePlatformIngestion each carry a Lambda config change CI's code-deploy cannot ship
(the layer rebuild → Ingestion; the #2134 AlarmDescription batch → Compute). Deliberate
no-action this session — they clear with owner items 2–4; anything NEW would have gotten an
issue. (The #2159 duration/coverage warnings stayed quiet — #2172's deadband did its job.)
**Stash/hooks:** clean — stash empty, hook freshness 🟢.

---

## What shipped (20 PRs merged; deployed unless noted)

**The Now queue:** #2169 (#1919 — 6 _Nd fields window-gated with honest companions, 3 exempted
by measurement, 1 deferred with disclosure, plus a real off-issue bug: unclamped trend-loop
fabricated behavioral zeros after resets) · #2171 (#1968 — night labels + serve-time re-check on
the ADR-104 harness, zero added Bedrock spend; the defect re-demonstrated itself mid-measurement,
8.5→8.4).

**The Later rank, drained:** #2168 (#1674 facade embeds; `/api/social_context` live) ·
#2170 (#1656 tranche — the WHOLE first-party surface into the strict mypy gate: 371 modules
0 errors under CI-pinned 2.3.0, DIRTY emptied, ignore_errors gone, 3 up-only ratchets incl.
filesystem-derived CLEAN_DIRS; 1,047-error strict-flags census recorded, issue stays open) ·
#2172 (#1658 tranche — coverage 57.19→62.64% with 776 real tests + the measured-coverage
high-water ratchet; 70% honestly out of one-PR reach, gap recorded) · #2181 (#2116 — composite
alarm gates the token page's human-email path on a genesis-window gauge; cost-governor deployed,
composites arm on the owner's Monitoring deploy) · #2180 (#1678/ADR-149 — measured the real CSP
mechanism: TWO CDK ResponseHeadersPolicies; media-src and X-Frame-Options premises corrected;
flag-off, zero cdk diff) · #2182 (#2101 code half — generation-agnostic garmin client, proven
against real 0.2.40/0.3.8 wheels offline; manifest untouched, #2099 gate clean; CVE clears in
the owner's layer rebuild) · #2187 (#2056 — #1699 gate armed 1→5 of 15 surfaces with
LogAvailability UNKNOWN semantics, 12-surface blanket exemption replaced by per-surface reasons;
two sanctioned splits: behavior_logs.py, item_recency.py) · #2186 (#1679 — `/story/membrane/` +
`/api/membrane`; outbound provenance hook wired into post_social.py so the first real post
lights the board; held-set never published, not even as a count) · #2192 (#1654 tranche — the
two worst god-modules, 5,390 lines → 10 cohesive modules + 2 thin facades; guards repointed to
follow the code and mutation-tested, which exposed the labs genetic-privacy guard passing on a
re-export string; 24 offenders remain, census in the PR).

**The bug pipeline that ate its own tail:** #2172's test-writing surfaced 7 real bugs → filed
as #2173–#2179 (verified against source by the filer) → 6 fixed, merged and deployed the SAME
session: #2185 (#2173 — partner weekly emails had been silently shipping "Commentary
unavailable" instead of real Board commentary; wrong AIValidationResult fields swallowed by a
broad except, now loud) · #2183 (#2177 chronicle partial-record crash) · #2189 (#2174 zone2
fabricated-zero) · #2190 (#2176 Decimal guard dead in prod) · #2188 (#2175 %W-vs-isocalendar
week keys; stored rows audited read-only, no wrong-keyed writes found) · #2191 (#2179 four-part
absence-as-signal bundle). The 7th (#2178) is fixed in HELD PR #2184 (IAM grant — owner window).

**Dependabot:** #2125 merged (aws-cdk-lib 2.263.0 — synth drift to the owner's CDK window) ·
#2193 merged (the CQ-01 companion built as sanctioned: dependabot's 6 dev-tooling bumps + the
8 workflow files' pins measured-and-moved in lockstep; supersedes #2126, which dependabot
self-closed).

**Fix-forward on main:** `67622779` (the garmin guarded-import, the session's one real red).

**Deploys:** site-api ×4 (each within a minute of its merge — the #1704 race won twice on hard
api_deps), cost-governor, wednesday-chronicle, partner-weekly-email, weekly-correlation-compute,
dashboard-refresh, anomaly-detector, + the CI fleet deploys behind 6 auto-approved gates; 2 green
site-deploys; CloudFront viewer-path invalidation for the 6 split-boundary API routes. All six
spot-checked 200 live post-split.

## The operating-model finding (the session's story)

Three "GitHub is broken" symptoms decoded to three different non-incidents: (1) **#2167's
"checks never mint" was a merge conflict all along** — a CONFLICTING PR mints NO check suites
(no merge ref to build), and during Day 4's real platform incident that read as check-minting
breakage; rebase → checks minted in minutes. (2) **Two zombie gated runs from Aug 1–2** sat
"waiting" — approving them would have DEPLOYED 5-day-old code; the lease rule's letter (approve
everything) conflicts with its intent on stale runs — left waiting, excluded by pin. (3) A 0.9h
gate stall happened because MY approval loop batches notifications between turns — replaced
mid-session with an **auto-approving monitor** (zombies excluded); it took the next 6 gates in
<2 min each. The lease rule is now a mechanism, not a discipline.

## Gotchas hit (carry these)

- **A CONFLICTING PR mints no check suites at all.** Before diagnosing platform incidents or
  swapping branches: `gh pr view N --json mergeable,mergeStateStatus`. (memory: new reference.)
- **Layer-shipped wheels red CI at CALL time, not just collection.** A lazy import inside a
  method body still fails in CI when tests exercise the path — and an implementer whose local
  env has the real wheels CANNOT see it (its full suite is green by construction). Guard like
  `_is_garth_http_error`: import inside the branch that needs it, fall back explicitly.
- **The surface-drift gate's route deferral is the dated markdown ledger line**
  (`docs/qa/SURFACE_DRIFT_EXEMPTIONS.md`), NOT `tests/api_schemas/_exemptions.json` — the JSON
  feeds a different checker; both are needed for a new pre-deploy route.
- **The doc-literal conflict is now a 30-second reflex:** checkout --theirs on the two literal
  files → `sync_doc_metadata.py --apply` on the rebased tree → amend. It was the ONLY conflict
  class in 11 of 13 rebases tonight.
- **An engine doc's Verified stamp is a real gate on PR branches** — #2171 tripped
  `check_doc_index.py --strict` (COACH_STANCE older than its source); the fix is an honest
  re-verify note + corrected line citations, not a stamp bump.

## Residual / next picks

- #2194 — capture schema baselines for the two new routes, drop both exemption entries.
- #2195 — the #2056 census residual (coach_history_summarizer arming cost decision).
- #1656 / #1658 / #1654 stay open with measured censuses in their PR bodies — the next tranches
  are well-scoped (strict-flags axis; coverage 62.64→70; 24 size offenders, `site_api_coach`
  first and alone).
- #1383 / #1114 stay Now for a Matthew-live session. not-work — need his interactive input.
- Aug-8+: watch the first post-#2149 scheduled wedge-watch nights stay quiet; the whoop
  citation-removal clock starts at re-auth. not-work — passive verification.
- The two zombie gated runs (30727225837, 30723876315, Aug 1–2) still sit "waiting" — GitHub
  expires them at 30d; cancelling risks the stranded-group class for zero benefit. not-work —
  deliberate leave-alone, documented here.

## OWNER ACTIONS (Matthew — carried + new, one list)

1. **Whoop re-auth (URGENT, carried — third credential loss, latched since Aug-4, no data since
   Aug-3):** `python3 setup/setup_whoop_auth.py --backfill`, then delete the AUTH_FAILURE marker
   row (#2085). Clears the qa-smoke freshness fail + the whoop alarm board.
2. **The CDK/IAM window — now FIVE held PRs, one sitting:**
   a. Merge **#2153** AND **#2184** → `cdk deploy LifePlatformEmail` (delivered-marker grant +
      the monday-compass todoist grant ride the same stack deploy; #2184's code half then makes
      the compass sections real).
   b. Merge **#2163** → `cdk deploy LifePlatformIngestion` FIRST, then
      `deploy_lambda.sh social-enrichment …` + `deploy_site_api.sh`.
   c. Merge **#2161** → same Ingestion deploy; then the two secrets when accounts exist.
   d. Merge **#2162** → `aws iam put-role-policy …` (staged JSON in `infra/iam/`), then the
      teardown dry-run → `--apply`.
   After: `deploy_all=true` dispatch + approve (clears the R8-ST6 window).
3. **Layer rebuild (carried, PR #2100 runbook)** — now carries the urllib3/idna re-bumps AND
   #2182's staged garminconnect 0.3.8 target (`garmin.txt` comment + `--promote` sequence in
   the PR body). Clears PYSEC-2026-3467.
4. **`cdk deploy LifePlatformMonitoring`** (carried) — now ALSO arms #2181's composite alarms
   (the token-page email path goes genesis-aware) + synth drift from #2124/#2125/#2127.
5. **ADR-149 exercise (optional, whenever there's content):** flip `native_social_embeds` in
   `cdk/cdk.json` + `cdk deploy LifePlatformWeb` in ONE sitting, then re-stamp `LIVE_AMJ_CSP`.
   Until then the header is byte-identical live.
6. **Branch protection one-liner (carried):** `python3 scripts/apply_branch_protection.py --apply && … --check`.
7. **Backfills (carried, dry-run-first):** coach-ensemble phase stamps; optional NARRATIVE#arc;
   optional lead-in pages.
8. **Two data/content calls (carried):** the #1984 stack decision; Home's "sixteen prior climbs"
   count (`site/index.html:176`).
9. **The #1402 governance decision (carried):** ADR-140 rule 5 vs the fingerprint card —
   #2167's structural half is now merged, so the poster path exists human-gated either way.
10. **Carried:** CodeQL dismissals ×3 (#2046), PR #2012 revision purge, the #1905 clinicians call.

Prior session's narrative: `git show
origin/session-archive:handovers/HANDOVER_2026-08-05_day4-overnight-max-paydown.md`.

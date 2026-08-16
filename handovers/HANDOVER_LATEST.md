# Handover — 2026-08-16 (early, PT 08-15 night): Fable grades the week, then pays its own queue

**Session:** interactive, Fable (first fable session since 08-09), attended — the owner granted cdk+IAM authority mid-session and made three live gate decisions. **Driver:** the approved plan `~/.claude/plans/sprightly-growing-firefly.md` — Phase 0 observations owed from 08-15, the fable-identity delta review, then the fable Now queue (#2654/#2492/#1114), stretch (#2675, #2719 design to Matthew).

**Build beat:** `2026-08-16-the-warning-no-deploy-could-clear`
**Docs:** `docs/DESIGN_SYSTEM_V5.md` §8.7 (frame v2 decision recorded) · `docs/reviews/FULLREVIEW_2026-08-16_DELTA.md` + `fullreview_grades_2026-08-16_delta.json` (new, banked) · `docs/QUICKSTART.md`/`NEW_MACHINE_BOOTSTRAP.md` (CLI pin mirrors) · `docs/PROPORTIONALITY.md` (+1 row, the scrub alarm) · doc-literal regens rode each PR
**Decisions:** none needed — the sessions's three governance-shaped calls (portrait direction, Grand Rounds routing, coverage bank) were owner gate decisions applied under existing contracts (ADR-106, ADR-153 alias mechanism, #1658's bank-the-gain rule), each recorded on its issue/PR
**Main:** red at close, decoded — the newest COMPLETED run at close (`ea2f2507`, #2771's) fails Unit Tests on the same stale-guard defect #2772 already fixed on main (`d30ffd62`); the post-fix run was in flight at close and is the green candidate. Deploy plane is NOT stranded: the `1b767c8c` fleet deploy was approved at HEAD and its **Deploy ✅ Smoke ✅** — only its test lane carried the stale guard.
**Stash/hooks:** clean — `git stash list` empty, hook freshness 🟢
**Closures:** 6 with live evidence — #2468, #2654, #2492, #1114, #2719, #2675. Partials honestly held: #2692 (boxes 3–4 named), #2741 (confirm path still unobserved in prod; window checked and recorded).
**Incidents:** 1 row added — main red ~40min from my own #2769 escape (a second guard file pinning the pre-resolution board state; targeted suites passed, the full lane was not run for that PR).
**Backlog:** promoted #2639, #2674, #1629 to Now by stored rank (score-line arrows updated). The STORY-liveness floor is honestly unmet and unmeetable: Now holds 2 actionable stories (#1221, #1629) + 2 `gate:owner`; Next's only other stories are both `blocked:dep` (#1739, #1740 — the TTS bake-off chain behind gate:owner #1738). Fourteen actionable bugs/chores sit on Now regardless — the queue has work, the story pipeline is what's thin. `later_staleness` sweep: clean (67 issues satisfy the filing contract). 11 filed this session (#2753 epic + #2754–#2763, `review:2026-08-16`).
**Alarms:** 7 red, all cited, unchanged since session start (zero new reds across ~12 deploys); the new `between-chronicle-scrub-failed-closed` alarm is live at INSUFFICIENT_DATA with an offline `test-metric-filter` fire-proof. `coherence-overall`'s earliest possible OK is ~2026-08-16 18:45Z — the #2735/#2670 transition observations and the planted OK→ALARM proof remain time-blocked (#2735).
**CI warnings:** 1 at close-check → 0 — the coverage high-water warning (81.71 vs 80.20) was triaged the sanctioned way: banked to 81.60 (#2771, merged).

---

## What shipped — 10 PRs, all merged

| PR | Issue | What |
|---|---|---|
| #2751 | #2468 | CDK CLI pin 2.1129.0→2.1135.1 — necessary hygiene, but its comment blamed the wrong leg (corrected in #2767) |
| #2752 | — | the 08-16 Fable delta scorecard banked |
| #2764 | #2654 | between-chronicle scrub fails CLOSED + token alarm |
| #2765 | #2492 | coach prompt-pass v3 — grounded pushback + repair, deterministically held |
| #2766 | #1114 | portrait frame v2 — the ring stays, the clock dies; size-aware ink |
| #2767 | #2468 | cdk_deploy.sh owns its toolchain (pinned venv synth) + honest mechanism correction |
| #2768 | — | i16 parses the date SEGMENT of whoop's sub-keyed sort keys |
| #2769 | #2719 | Grand Rounds chaired by the lead — board → eli_marsh |
| #2771 | — | coverage high-water banked 80.20 → 81.60 |
| #2772 | — | the board-refusal guard pins the CLASS, not the pre-#2719 instance (decodes main's red) |

**Deployed:** all 7 Lambda stacks via cdk with the PINNED aws-cdk-lib (the #2468 fix) + Monitoring (the new alarm); per-function `between-chronicle`, `telegram-coach-worker` (twice — see gotcha 3), `telegram-webhook`, `life-platform-site-api-ai`; 5 voice specs + `personas.json` to S3; two site auto-deploys (portraits live and verified in-situ). One fleet lease approved at HEAD (Deploy ✅ Smoke ✅); five stale leases REJECTED with reasons.

## The review (the session's first half)

Scoped Fable delta re-grade of the true ungraded surface — **08c7af26..d7df1148e** (the plan's `07b80001` anchor was the 07-16 scorecard sha, and the 08-02 anchors were already superseded by an 08-09 Fable delta; both corrected before launching). 7 lenses, one grader + one lean-REFUTED verifier each, all Fable: **narrative B→B+, aiq B→B+, observability B+→A−, integrations B+→A− — four lenses up, three held (security B+, principal A−, cto A−).** All 7 verifier letters agree; 27 findings → 26 CONFIRMED + 1 ADJUSTED + 0 refuted (unusually clean against the historic ~50% FP rate). 10 filed + epic #2753. ~1.09M subagent tokens, 14 agents, zero errors.

## The through-line

The week's sessions kept finding measurements that returned clean numbers while measuring nothing. This session's version was subtler: **measurements that were CORRECT and still produced the wrong verdict, because two of them disagreed about the frame of reference.**

- The 7 config-drift warnings were TRUE every night — CI's synth genuinely differed from deployed — but un-actionable by the deploy they prescribed, because the owner's machine synthesized with aws-cdk-lib 2.244.0 against CI's pinned 2.263.0. Four owner stack deploys "fixed" them into persisting. The board went clean only when deployed reality was moved to match the PIN (7-stack deploy), and stays clean because the wrapper now builds its own toolchain (#2767).
- #2675's two coaches disagreeing about the cycle day: BOTH were blessed by their own gate, because the Day-N gate ran on UTC while the prompt asserted PT. Every PT evening the gate flagged the platform's own correct day and passed the wrong one. One clock now (`pacific_today()`), pinned at the dual-clock instant itself; live board probe post-deploy: three voices, Day 6, unanimous.

## Gotchas — read before the next session

1. **My own false isolation, on the record:** I "proved" the CDK CLI decides the LogRetention runtime with a venv experiment — but `cdk` spawns `python3` through the login shell, so the activated venv never reached `app.py` and my "2.263.0 synth" was actually 2.244.0. The tell that unwound it: **decode the template's `CDK::Metadata` Analytics blob (gzip+base64) — it names the exact aws-cdk-lib that synthesized it.** Ground truth beats a plausible experiment.
2. **`… | tail` swallowed a pytest usage error and the task reported exit 0.** My first "full lane" for #2654 never ran one test (`--timeout` unsupported → usage error → `tail` exits 0) — the #2746 class, in my own command, same week. The tell: zero `passed` lines in a "green" run. Run pytest unpiped to a file, append `pytest exit=$?`, read BOTH.
3. **`gh pr merge` does not pull.** I deployed `telegram-coach-worker` + uploaded S3 voice specs from a checkout one merge behind — the ancestry postflight's sha is what exposed it (deployed sha matched MY stale HEAD, honestly). Pull, verify the sha you're about to ship IS the merge, then deploy. Both redone correct.
4. **Updating "the" guard file is not sweeping the guard SET.** #2769 updated `test_telegram_route_provisioning_2677.py` and missed `test_board_route_refuses_2719.py` pinning the same state — targeted suites green, main red 40min later. Grep the repo for every test referencing the state you changed, then run the FULL lane (which I had skipped for exactly that PR).
5. **A branch switch under a running full lane poisons it.** My #2492 lane "failed" test_count because I checked main out mid-run. A lane's tree must be frozen for its duration — worktrees exist for this.
6. **`config/coaches/*.json` voice specs are S3-FIRST at runtime** — a merged few-shot does nothing until `aws s3 cp` (the `deploy_coach_intelligence.sh` glob, or per-file). Same for `personas.json` route aliases.
7. **The email portrait PNGs render `with_frame=False`** — regenerating after a frame change is a byte-identical no-op BY DESIGN; verify that claim (`git status`) rather than assuming the manifest guard covers renderer changes (it keys on recipe hashes only).

## Residual queue / next picks

- **#2735 / #2670** — the alarm OK transitions + the planted OK→ALARM proof; time-blocked until `coherence-overall`'s 24h maximum ages out (~2026-08-16 18:45Z). Observe the transitions, paste into both, then plant against the clean baseline.
- **#2667** — per-metric as-of dates in the AI prompt; verified real from source, scoping comment banked on the issue: `site_api_ai_lambda` is FULL at its size ceiling, so the work STARTS with the sibling extraction (`site_api_ai_prompt.py` is the host). Deliberately not started at 3am.
- **#2741** — confirm-before-FAIL still unobserved in production (fires ~2 nights in 8); the 08-16 01:30Z window check is on the issue.
- **#2692** — boxes 3–4 open (per-test regression detection + PROPORTIONALITY row); the CI durations measurement + local/CI gap explanation are banked on the issue. Note the run-to-run wall-clock variance (±300s) recorded there is the design input for box 3.
- **#2754–#2763 + epic #2753** — the review's filed findings, ranked and milestoned; `backlog_next.py` will surface them.
- **#2673 / #1080 / #2363** — the coach-experience epics move next: #1080 pairs with the now-approved portrait direction; the #2363 multi-coach Grand Rounds room now has its interim (lead chairs it) live.
- not-work — the post-#2772 main run was in flight at close; if its Deploy gate is waiting when next seen, ancestry-check and approve at HEAD (it is the green candidate). If `ea2f2507`'s red completed meanwhile, it is pre-decoded above.
- not-work — first real message to `@ajm_board_bot` is the live Grand Rounds proof (only Matthew can send it); Eli should answer by name.
- not-work — transcript-QA night should sample correction + contradicted-plan exchanges to measure #2492's outcome in real chats (recorded on the issue).

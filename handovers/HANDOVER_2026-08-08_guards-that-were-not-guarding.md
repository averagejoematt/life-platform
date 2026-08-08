# HANDOVER — The guards that weren't guarding: a mutation sweep, a P1 privacy gate, and coverage past 70% — 2026-08-08 ~03:52Z → ~06:30Z

> Instruction thread: *"read the Day-5 handover, then run a maximum-paydown session over the open
> issue corpus. Opus driving — all model:fable work OFF-LIMITS. Driver drives only; every
> implementer is a worktree-implementer on its issue's own model:* label; waves of ≤5. Arm the
> auto-approving monitor EARLY. Priorities: preflight → the whoop/Pillow verifications →
> #2194/#2195/#2198 → the pre-scoped tranches (#1658/#1654/#1656) → straight down the stored rank;
> if the actionable rank drains, a measured sweep that files new issues beats scraping 0.38s."*
> Plus, emphasised: *"the whoop verification is the one thing I'd insist the session does even if
> it's short on time."*

**Main:** green (`e731ebef`) at the time of the (e2) gate; two fix-forwards this session, both
mine, both detailed below.
**Docs:** `docs/INCIDENT_LOG.md` (+2 rows, last-updated refreshed) · in-PR: `docs/CONVENTIONS.md`
+ `docs/DECISIONS.md` ADR-148 amendment (#2200), new `docs/STACK_MANIFEST.md` indexed in
`docs/README.md` (#2207), `docs/DEPENDENCY_GRAPH.md` stale-consumer correction (#2210),
`docs/TESTING.md` literals. All four wiki checkers green at the wrap commit.
**Decisions:** none needed — the one governance-shaped call (ADR-148's user-owned-repo bypass
limitation) shipped as an amendment inside #2200; nothing else this session changed posture.
**Incidents:** 2 rows added — (1) main red ~63min on an undeclared PyYAML; (2) unresolved
conflict markers merged to main through my own #2200 reconcile with every gate green.
**Build beat:** `2026-08-08-the-guards-that-were-not-guarding`.
**Closures:** #2194, #2195, #2198, #2203, #2209 — all five commented in the ADR-099 two-line
shape. #2198 carries an honest `partial` (the mechanism is designed and read-only-verified;
`--apply` was never executed live, and whether GitHub accepts a `User` bypass actor here could
not be settled without a write that was out of scope).
**Backlog:** Now was at 2 actionable → promoted #2204 and #2206 by stored rank (both score 2.00,
both sonnet); their score lines were corrected `→ Next` → `→ Now` to match, which the (e7) linter
caught. Later sweep: no stale issues. Corpus clean — 60 open, 0 violations.
**Alarms:** every alarm red >72h is cited. The whoop board is latched but **self-healing, not
stuck** — `IngestAuthHealthy=1` for hours, `ConsecutiveFailures=0`, no stale #2085 latch; the
24h `Minimum` window rolls past the last 0 around 01:00Z 08-09.
**CI warnings:** 7 — all one class (`LifePlatformWeb/Mcp/Serve/Operational/Email/Compute/Ingestion`
each carry a Lambda config change CI's code-deploy cannot ship). This **grew from 2 last session**
despite the owner's CDK window running, so it is not the carried no-action call any more: filed as
**#2213**, with the aws-cdk-lib 2.263.0 bump recorded as a *hypothesis, not a conclusion* (the
per-stack `cdk diff` has not been measured). Clearing it needs an owner-gated CDK deploy.
**Stash/hooks:** clean — stash empty at close, hook freshness 🟢.

---

## The owner's two must-do verifications

**1. Whoop #2196 — the fix works, with a measured limitation.** Positively confirmed live:
`whoop_token_reused remaining_s=2160 — no refresh_token rotation this run`. The expiry field
self-healed after exactly one expected `no_stored_expiry` exchange; data flows (3 records/run,
`RunSuccess=1`).

**But the gate cannot engage on the path that produces nearly all the rotations.** Measured, then
confirmed to the second: access-token lifetime **3599s**, cron interval **3600s**, skew 300s — so
every scheduled run sees ~4s of life left and still exchanges (`whoop_token_exchange
reason=expires_in_4s`, 05:00:16Z; predicted before it fired). The benefit is confined to
duplicate/extra invocations, so the daily rotation count — and expected time-to-credential-death —
is roughly unchanged. Filed **#2204** with the arithmetic. What #2197 *did* buy is real and not in
question: no blind retry on the token POST, `WhoopRotationLost` classification, cache
invalidation, breaker-aware reconcile.

**2. Pillow 12 — verified at the artifact level.** The last real generation (19:30Z 08-07)
predated the 02:12Z layer rebuild, so this was genuinely untested. Manual invoke → 14/14 images,
then three PNGs pulled back down and confirmed valid 1200×630 RGB with real content and differing
byte sizes. Not just a 200.

## What shipped (8 PRs merged, all deployed)

- **#2199** (#2194) — schema baselines for `/api/social_context` + `/api/membrane`; both exemption
  ledgers cleared. The wholesale-capture trap was handled properly: 121 baselines rewritten, **119
  reverted** (72 timestamp-only, 47 real diffs each inspected and explained by cycle-12 data
  thinness or features shipped since the last capture). No handler regression among them.
- **#2201** (#2195) — the #1699 gate armed on the stance writer. Cost *measured*, not asserted:
  one platform-wide `GetItem` hoisted above the 8-coach loop, ≤782 reads/yr. Mutation-tested
  twice, including a test that pins the cost claim itself.
- **#2202** (#1654 slice) — `site_api_coach` 2,664 → 434 lines behind an unchanged facade, 5 new
  modules. Deployed; 7/7 boundary endpoints 200; **235/235** smoke. Its guard-repointing exposed
  the #2203 defect below.
- **#2200** (#2198) — branch-protection bypass redesigned to a `User` actor. No repo-settings
  mutations (owner's hard limit respected). Caused both of this session's reds.
- **#2205** (#2203) — a genuine second-layer fixture for the journal-quotes screen.
- **#2207** (#1401 slice 1) — `/data/stack.json` + schema, live (200). Sources are an **exact
  match** to the already-public set; supplement fields a strict **subset** of `/api/supplements`.
  Device/time costs honestly `null` with a stated basis rather than invented.
- **#2208** (#1658 tranche 2) — measured coverage **63.14% → 70.50%**, ratchet 62.64 → 70.40. I
  re-measured on the reconciled tree before merging (enforcing gate): **70.50%, 13,137 passed, 0
  failed**, 121 `xfail`s deliberately encoding defects rather than asserting bugs as correct.
- **#2210** (#2209, P1) — the delivery privacy gate. Deployed and verified live, including after
  CI's redeploy raced my manual one.

## The session's spine: five guards that guarded nothing

#2202's split work surfaced one, and every thread pulled found another. All five were
**mutation-proven**, and I verified each myself rather than accept the report:

| # | screen | evidence | status |
|---|---|---|---|
| #2203 | journal-quotes all-or-nothing second layer | 55/55 passed with it deleted | fixed (#2205) |
| #2209 | `/api/food_delivery_overview` — no flag gate at all | sibling module gates the identical data private-by-default | fixed (#2210) |
| #2206 | `_claims_by_entry` — two screens, zero coverage on either | both fixtures benign | open |
| #2211 | `/api/labs` genetic CATEGORY screen | full 10,930-test suite passed with it removed | open |
| #2212 | `_is_blocked_vice` — 4+ of 6 call sites | each survives full-suite mutation, 3 public endpoints | open |

**None was leaking**, and saying otherwise would have been the more dramatic claim and the false
one. The screens are present and running; what was missing is anything that would notice if they
were removed. The sweep also returned negative results worth banking — the other journal-quote
screens, all three `find_dossier_violations` legs, and whole-module pass-throughs of
`privacy_guard` / `broadcast_sensitivity_gate` / `diary_consent` are genuinely well-guarded.

## Gotchas hit (carry these)

- **`sync_doc_metadata.py --apply` writes INSIDE an unresolved conflict block.** My #2200 reconcile
  ran `checkout --theirs` on only one of **two** conflicted literal files; `--apply` then rewrote
  the number on both sides of the other's conflict, making them byte-identical — so `--check`
  passed, lint/mypy never read markdown, and `check_main_green.py` said GREEN. The failure mode is
  specifically *a conflict whose two sides are identical*, i.e. the doc-literal class this repo
  hits on nearly every concurrent PR. Now guarded by `tests/test_no_conflict_markers.py`
  (set from `git ls-files`, self-mutation-proven, verified to fail against the real broken content).
- **A collect-only lane cannot see an in-function import.** #2200's tests need PyYAML, declared
  **nowhere**; the PR was green because the fast lane only *collects* them and `import yaml` sits
  inside the function. Only the post-merge full suite executes it. Mirror image of the layer-dep
  class. The CQ-01 parity guard then caught me adding the pin to only one of the two files — it
  works.
- **A guard must be mutation-proven or it is not a guard.** Three privacy screens passed while
  guarding nothing, in one night, in three different disguises.
- **Cross-session coordination is a real hazard.** A peer session, acting on my *superseded*
  instruction, restored the conflict markers onto #2205's branch. I countermanded it and then
  settled it by **test-merge rather than argument** — the branch made no change to that file
  relative to the merge base, so main's fix won cleanly.

## Residual / next picks

- **#2211** — `/api/labs` genetic category screen unguarded (Now, P2, sonnet).
- **#2212** — blocked-vice screen SET, 4+ of 6 call sites (Now, P2, sonnet); includes a sixth call
  site (`site_api_social.py:1115`) the sweep never tested.
- **#2206** — diary claims, zero coverage on either screen (Now, promoted this session).
- **#2204** — the whoop cron/lifetime arithmetic; the lever is cadence, not skew (Now, promoted).
- **#2213** — the 7-stack CDK config-drift warning board; needs an owner-gated CDK deploy.
- **#2214–#2220** — seven P1 defects from #2208's tranche, each verified against source before
  filing (adaptive_mode's unreachable "flourishing" and empty-platform Rough Patch is the worst).
  **#2221** tracks the ~58-defect tail against the merged `xfail` markers.
- **#1656 / #1658 / #1654** stay open with measured censuses; the next tranches are well-scoped.
- **#1383 / #1114** stay Now for a Matthew-live session. not-work — need his interactive input.
- Git worktrees have accumulated to 46, seven of them *inside* the repo under
  `.claude/worktrees/` plus one on the lowercase case-twin path. not-work — no gate is affected
  today (all target specific directories); flagged as housekeeping, not a defect.
- The two zombie gated runs (30727225837, 30723876315) still sit waiting, deliberately excluded
  from the auto-approver — approving them would deploy week-old code. not-work — documented
  leave-alone, GitHub expires them at 30d.

## OWNER ACTIONS (unchanged, plus two)

1. **GitHub UI clicks:** CodeQL dismissals ×3 (#2046) · PR #2012 revision-history purge · **+2 new
   from #2200**, both verified false positives (the code logs a secret's *name*; the API it calls
   returns names only, never values — a 10-second informed dismissal, not an investigation).
2. **Personal calls, no deadline:** the #1984 stack decision · the #1905 clinicians call.
3. **When accounts exist:** Bluesky/Mastodon accounts + the two secrets — capture starts by itself.
4. **Optional:** ADR-149 flag flip + `cdk deploy LifePlatformWeb`, one sitting.
5. **A CDK deploy window** would clear #2213's seven warnings; measure `cdk diff` per stack first.

Prior session's narrative: `git show
origin/session-archive:handovers/HANDOVER_2026-08-06_day5-max-paydown-owner-window.md`.
